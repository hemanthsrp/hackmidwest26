"""Evidence grading: stored strength, off-topic labelling, ranking and gated tone. Offline."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from scraper_analysis.agents import jev_guard, synthesis_agent
from scraper_analysis.api import app
from scraper_analysis.config import get_settings
from scraper_analysis.models.briefing import Briefing, BriefingPoint
from scraper_analysis.models.evidence import Credibility, Evidence, Sentiment
from scraper_analysis.pipeline import grade
from scraper_analysis.storage import store as store_module

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(store_module, "_store", store_module.InMemoryEvidenceStore())
    yield
    monkeypatch.setattr(store_module, "_store", None)


@pytest.fixture
def jev_on(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", "test-key")
    monkeypatch.setattr(settings, "jev_relevance_gate", 0.3)


def judgment(**overrides) -> dict:
    base = {
        "engine": "jev", "relevant": 0.98, "direction": "positive", "direction_confidence": 1.0,
        "content_type": "news_report", "event_type": "earnings_or_guidance", "upcoming_event": 0.05,
        "sensational": 0.05, "usable_content": 0.97, "materiality": 2.0, "materiality_confidence": 0.9,
    }
    return {**base, **overrides}


def make(evidence_id: str, jev: dict | None = None, *, credibility=0.8, source_type="general_news",
         published=NOW, sentiment=None) -> Evidence:
    return Evidence(
        id=evidence_id, symbol="AAPL", title=f"title {evidence_id}", summary="summary", source_name="CNBC",
        source_type=source_type, published_at=published, retrieved_at=NOW,
        credibility=Credibility(overall_score=credibility), sentiment=sentiment or Sentiment(),
        details={"jev": jev} if jev else {},
    )


def test_strength_is_the_product_of_stored_factors():
    record = grade.grade_record(make("a", judgment()), relevance_gate=0.3)
    assert record["basis"] == "jev" and record["gated"] is False and record["gate_reasons"] == []
    # 0.98 relevance x 0.8 credibility x 1.0 news x 1.0 major x 1.0 confident x no hype x no duplicates
    assert record["strength"] == pytest.approx(0.784, abs=1e-3)
    product = 1.0
    for value in record["factors"].values():
        product *= value
    assert record["strength"] == pytest.approx(product, abs=1e-3)


def test_each_factor_lowers_or_raises_strength_as_documented():
    base = grade.grade_record(make("a", judgment()), 0.3)["strength"]
    weaker = {
        "opinion": judgment(content_type="opinion_or_analysis"),
        "social": judgment(content_type="social_media_post"),
        "routine": judgment(materiality=0.0),
        "unsure": judgment(direction_confidence=0.2),
        "hype": judgment(sensational=0.9),
    }
    for name, jev in weaker.items():
        assert grade.grade_record(make("a", jev), 0.3)["strength"] < base, name
    assert grade.grade_record(make("a", judgment(sensational=0.6)), 0.3)["strength"] == base  # below the hype bar
    assert grade.grade_record(make("a", judgment(same_story_as=["b", "c"])), 0.3)["factors"]["same_story"] == 1.2


def test_off_topic_and_unusable_records_are_labelled_not_removed():
    off = grade.grade_record(make("a", judgment(relevant=0.05)), 0.3)
    junk = grade.grade_record(make("a", judgment(usable_content=0.1)), 0.3)
    assert off["gated"] and off["gate_reasons"] == ["off_topic"] and off["strength"] < 0.05
    assert junk["gated"] and junk["gate_reasons"] == ["unusable_content"]
    assert grade.grade_record(make("a", judgment(relevant=0.31)), 0.3)["gated"] is False


def test_unjudged_records_are_graded_on_credibility_and_never_gated():
    filing = make("f", None, credibility=1.0, source_type="sec_filing")
    failed = make("u", {"engine": "unavailable", "error": "timeout"}, credibility=0.6)
    for evidence, expected in ((filing, 1.0), (failed, 0.6)):
        record = grade.grade_record(evidence, 0.3)
        assert (record["basis"], record["strength"], record["gated"]) == ("source_only", expected, False)


def test_grading_is_a_no_op_when_jev_is_off(monkeypatch):
    monkeypatch.setattr(get_settings(), "jev_enabled", False)
    evidence = make("a", judgment())
    before = evidence.model_dump()
    grade.grade_evidence([evidence])
    assert evidence.model_dump() == before
    assert grade.agent_view(evidence) == {} and grade.is_gated(evidence) is False


def test_grade_is_stored_and_tagging_is_left_alone(jev_on):
    tagged = Sentiment(direction="Bearish", score=0.6)
    off_topic = make("a", judgment(relevant=0.02, direction="neutral"), sentiment=tagged)
    grade.grade_evidence([off_topic])
    assert off_topic.details["grade"]["gate_reasons"] == ["off_topic"]
    assert off_topic.sentiment == tagged  # the tagging agent's output is untouched
    assert grade.agent_view(off_topic) == {
        "strength": off_topic.details["grade"]["strength"],
        "off_topic_for_symbol": True,
        "relevance_to_symbol": 0.02,
    }


def test_freshness_halves_every_three_days_and_is_not_stored(jev_on):
    fresh, old = make("new", judgment()), make("old", judgment(), published=NOW - timedelta(hours=72))
    grade.grade_evidence([fresh, old])
    assert fresh.details["grade"]["strength"] == old.details["grade"]["strength"]
    assert grade.current_strength(old, NOW) == pytest.approx(grade.current_strength(fresh, NOW) / 2, abs=1e-3)
    assert [e.id for e in grade.rank([old, fresh], NOW)] == ["new", "old"]


def test_news_tone_ignores_off_topic_and_counts_a_story_once(jev_on):
    items = [
        make("p1", judgment(direction="positive", same_story_as=["p2"])),
        make("p2", judgment(direction="positive", same_story_as=["p1"])),  # same story as p1
        make("n1", judgment(direction="negative")),
        make("m1", judgment(direction="mixed")),
        make("off1", judgment(relevant=0.02, direction="negative")),
        make("off2", judgment(relevant=0.02, direction="negative")),
        make("filing", None, source_type="sec_filing"),
    ]
    grade.grade_evidence(items)
    tone = grade.news_tone(items, NOW)
    assert (tone["records_judged"], tone["records_gated"], tone["stories_used"]) == (6, 2, 3)
    assert tone["by_direction"] == {"positive": 1, "negative": 1, "mixed": 1}
    assert tone["label"] == "mixed_or_neutral" and abs(tone["tone"]) < 0.25
    assert "off1" not in tone["evidence_ids"] and "filing" not in tone["evidence_ids"]


def test_news_tone_needs_enough_stories(jev_on):
    items = [make("p1", judgment()), make("p2", judgment())]
    grade.grade_evidence(items)
    assert grade.news_tone(items, NOW)["label"] == "insufficient_data"


def test_evidence_endpoint_default_is_unchanged_and_views_are_opt_in(jev_on):
    items = [make("strong", judgment()), make("weak", judgment(materiality=0.0, content_type="social_media_post")),
             make("off", judgment(relevant=0.02))]
    grade.grade_evidence(items)
    store_module.get_store().save_evidence(items)
    client = TestClient(app)

    plain = client.get("/evidence", params={"symbol": "AAPL"}).json()
    assert set(plain) == {"symbol", "status", "evidence"} and len(plain["evidence"]) == 3
    assert all("strength_now" not in e for e in plain["evidence"])

    ranked = client.get("/evidence", params={"symbol": "AAPL", "ranked": True}).json()
    assert [e["id"] for e in ranked["evidence"]] == ["strong", "weak", "off"]
    assert ranked["hidden_as_off_topic"] == 0 and ranked["news_tone"]["records_gated"] == 1

    relevant = client.get("/evidence", params={"symbol": "AAPL", "relevant_only": True}).json()
    assert {e["id"] for e in relevant["evidence"]} == {"strong", "weak"} and relevant["hidden_as_off_topic"] == 1
    assert len(store_module.get_store().query_evidence("AAPL")) == 3  # nothing was deleted


def test_briefing_agent_rows_show_the_grade_up_front(jev_on):
    graded = make("a", judgment(relevant=0.05))
    grade.grade_evidence([graded])
    row = synthesis_agent._evidence_row(graded)
    assert row["off_topic_for_symbol"] is True and row["relevance_to_symbol"] == 0.05
    assert "off_topic_for_symbol" not in synthesis_agent._evidence_row(make("b"))  # ungraded: row unchanged
    assert "off_topic_for_symbol" in synthesis_agent.SYSTEM_PROMPT


class _Checker:
    def __init__(self):
        self.calls = []

    def check_explanation(self, text, items):
        from types import SimpleNamespace

        self.calls.append((text, items))
        return SimpleNamespace(
            engine="jev", model="jev-1.13.0", question_set_version="explanation-v1",
            claims=[SimpleNamespace(text=text, supported=0.35)], personal_advice=0.02, promises_outcome=0.02,
        )


def test_briefing_review_skips_filing_points_and_warns_only_below_the_floor():
    news = make("n", judgment())
    filing = make("f", None, source_type="sec_filing")
    briefing = Briefing(
        headline="h", overall_tone="mixed", uncertainty="u",
        points=[
            BriefingPoint(theme="news", text="A news point.", direction="neutral", evidence_ids=["n"]),
            BriefingPoint(theme="insider", text="An insider sold shares.", direction="neutral", evidence_ids=["f"]),
        ],
    )
    checker = _Checker()
    review = jev_guard.review_briefing(briefing, [news, filing], tool=checker)
    assert review["points"][0]["status"] == "checked" and review["points"][0]["supported"] == 0.35
    assert review["points"][1] == {"index": 1, "status": "not_checked", "reason": "cites no news or social records"}
    assert review["warnings"] == []  # 0.35 is above the 0.3 floor
    assert [text for text, _ in checker.calls] == ["A news point.", "h u"]
