"""Owner review of A-J4 / A-J5: optional Jev enrichment must never be able to
abort an ingest or crash a read. Every test here failed on the unreviewed code.
Offline: no network, in-memory store."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from scraper_analysis.config import get_settings
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.pipeline import grade, ingest, jev_judge
from scraper_analysis.sources.base import sanitize_error
from scraper_analysis.storage import store as store_module

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(store_module, "_store", store_module.InMemoryEvidenceStore())
    settings = get_settings()
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", "test-key")
    monkeypatch.setattr(settings, "jev_relevance_gate", 0.3)
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(jev_judge, "_tool", None)
    yield
    monkeypatch.setattr(store_module, "_store", None)


def article(i: str, source="CNBC") -> Evidence:
    return Evidence(id=i, symbol="AAPL", title=f"Apple story {i}", summary="s", source_name=source,
                    source_type="general_news", retrieved_at=NOW)


def judgment(**over):
    base = dict(engine="jev", model="m", question_set_version="v", request_id="r", error=None,
                relevant=0.9, direction="positive", direction_confidence=0.8, content_type="news_report",
                content_type_confidence=0.9, event_type="other", event_type_confidence=0.5, upcoming_event=0.1,
                sensational=0.1, usable_content=0.9, materiality=1.0, materiality_confidence=0.7)
    base.update(over)
    return SimpleNamespace(**base)


def echo_ids(items, results):
    """Like jev_tool's judge_evidence_items, echo each payload id back as evidence_id
    (the real tool always does) unless the test set one explicitly."""
    for item, result in zip(items, results):
        if isinstance(result, SimpleNamespace) and getattr(result, "evidence_id", None) is None:
            result.evidence_id = item["id"]
        elif isinstance(result, dict) and result.get("evidence_id") is None:
            result["evidence_id"] = item["id"]
    return results


class Tool:
    def __init__(self, judgments, pairs=None):
        self.judgments, self.pairs = judgments, pairs or []

    def judge_evidence_items(self, items, companies):
        return echo_ids(items, self.judgments)

    def same_story(self, items, pairs):
        return SimpleNamespace(engine="jev", pairs=self.pairs)


BAD_VALUES = [None, float("nan"), float("inf"), "high", True]  # noqa: the tool types every field "float | None"


@pytest.mark.parametrize("field", ["relevant", "sensational", "usable_content", "materiality"])
@pytest.mark.parametrize("bad", BAD_VALUES, ids=repr)
def test_incomplete_judgment_is_stored_as_unavailable_not_as_a_real_one(field, bad):
    items = [article("a"), article("b", "MarketWatch")]
    jev_judge.judge_evidence(items, tool=Tool([judgment(**{field: bad}), judgment()]))
    broken, fine = (i.details["jev"] for i in items)
    assert broken["engine"] == "unavailable" and field in broken["error"]
    assert fine["engine"] == "jev"  # one bad record doesn't poison its neighbours


def test_optional_fields_may_be_empty():
    item = article("a")
    jev_judge.judge_evidence([item], tool=Tool([judgment(direction=None, direction_confidence=None)]))
    assert item.details["jev"]["engine"] == "jev"
    grade.grade_evidence([item])
    assert item.details["grade"]["basis"] == "jev"


def test_a_malformed_judgment_no_longer_loses_the_whole_ingest():
    """Before: TypeError out of grade_evidence -> nothing saved, same failure on every retry."""
    jev_judge._tool = Tool([judgment(materiality=None) for _ in range(20)])
    stored = ingest.run_ingestion("AAPL", allow_live=False, tag=False)
    assert stored, "records must still be ingested"
    assert len(store_module.get_store().query_evidence("AAPL")) == len(stored)
    news = [e for e in stored if e.source_type in jev_judge.JUDGED_SOURCE_TYPES]
    assert news and all(e.details["jev"]["engine"] == "unavailable" for e in news)


def test_a_broken_post_processing_step_cannot_abort_ingest():
    pair = SimpleNamespace(a=0, b=999, same=0.9)  # index out of range inside same-story marking
    jev_judge._tool = Tool([judgment() for _ in range(20)], pairs=[pair])
    stored = ingest.run_ingestion("AAPL", allow_live=False, tag=False)
    assert stored


def test_grade_evidence_isolates_one_bad_record():
    good, bad = article("good"), article("bad")
    good.details["jev"] = dict(vars(judgment()))
    bad.details["jev"] = {**dict(vars(judgment())), "materiality": None}  # as if stored by older code
    grade.grade_evidence([bad, good])
    assert good.details["grade"]["basis"] == "jev"
    # Re-validated at grading (PR #19 review): unknown, graded on the source alone, not a crash.
    assert (bad.details["grade"]["basis"], bad.details["grade"]["jev_status"]) == ("source_only", "malformed")


def test_grade_evidence_still_isolates_a_record_that_raises(monkeypatch):
    good, bad = article("good"), article("bad")
    real = grade.grade_record
    monkeypatch.setattr(grade, "grade_record", lambda e, gate, *rest: 1 / 0 if e.id == "bad" else real(e, gate, *rest))
    grade.grade_evidence([bad, good])
    assert "grade" in good.details and "grade" not in bad.details


@pytest.mark.parametrize("direction", [None, "unknown", "bullish!!"])
def test_news_tone_tolerates_a_missing_or_unknown_direction(direction):
    def graded(i, d="positive"):
        e = article(i, source=f"o{i}")
        e.details["jev"] = dict(vars(judgment(direction=d)))
        e.details["grade"] = grade.grade_record(e, 0.3)
        return e

    items = [graded(str(i)) for i in range(3)] + [graded("odd", direction)]
    result = grade.news_tone(items)
    assert result["label"] == "positive" and result["stories_used"] == 3
    assert result["records_without_direction"] == 1
    assert result["records_gated"] == 0  # not mislabeled as gated


def test_gated_and_directionless_are_counted_separately():
    gated = article("g")
    gated.details["jev"] = dict(vars(judgment(relevant=0.0)))
    gated.details["grade"] = grade.grade_record(gated, 0.3)
    nodir = article("n")
    nodir.details["jev"] = dict(vars(judgment(direction=None)))
    nodir.details["grade"] = grade.grade_record(nodir, 0.3)
    r = grade.news_tone([gated, nodir])
    assert (r["records_gated"], r["records_without_direction"]) == (1, 1)


def test_sentiment_fill_ignores_an_unknown_direction(monkeypatch):
    monkeypatch.setattr(get_settings(), "jev_fill_sentiment", True)
    monkeypatch.setattr(get_settings(), "aws_access_key_id", None)
    item = article("a")
    jev_judge.judge_evidence([item], tool=Tool([judgment(direction="sideways", direction_confidence=0.9)]))
    assert item.sentiment.direction is None and "filled_sentiment" not in item.details["jev"]


def test_jev_api_key_is_redacted_from_error_text(monkeypatch):
    monkeypatch.setattr(get_settings(), "typesafe_api_key", "ts_live_abcdef123456")
    out = sanitize_error("401 Unauthorized: invalid credential ts_live_abcdef123456 for model jev-1")
    assert "ts_live_abcdef123456" not in out and "redacted" in out


def test_required_fields_are_exactly_the_ones_grading_multiplies():
    assert set(jev_judge.REQUIRED_NUMERIC_FIELDS) == {"relevant", "sensational", "usable_content", "materiality"}
