"""Jev review of a briefing: advisory only, off by default, offline here."""

from datetime import UTC, datetime
from types import SimpleNamespace

from scraper_analysis.agents import jev_guard
from scraper_analysis.config import get_settings
from scraper_analysis.models.briefing import Briefing, BriefingPoint
from scraper_analysis.models.evidence import Evidence

NOW = datetime(2026, 10, 10, tzinfo=UTC)


def evidence(evidence_id: str, title: str) -> Evidence:
    return Evidence(
        id=evidence_id, symbol="AAPL", title=title, summary=None, source_name="CNBC",
        source_type="general_news", retrieved_at=NOW,
    )


def briefing(*points: BriefingPoint) -> Briefing:
    return Briefing(
        headline="Mixed picture for Apple", overall_tone="mixed", points=list(points), uncertainty="Limited data."
    )


def point(text: str, *ids: str) -> BriefingPoint:
    return BriefingPoint(theme="news", text=text, direction="neutral", evidence_ids=list(ids))


class FakeJev:
    def __init__(self, supported=0.9, advice=0.02, promise=0.03, engine="jev"):
        self.supported, self.advice, self.promise, self.engine = supported, advice, promise, engine
        self.calls = []

    def check_explanation(self, text, items):
        self.calls.append((text, items))
        if self.engine != "jev":
            return SimpleNamespace(engine="unavailable", error="timeout token=SECRET")
        supported = self.supported(text) if callable(self.supported) else self.supported
        return SimpleNamespace(
            engine="jev", model="jev-1.13.0", question_set_version="explanation-v1",
            claims=[SimpleNamespace(text=text, supported=supported)],
            personal_advice=self.advice, promises_outcome=self.promise,
        )


EVIDENCE = [evidence("e1", "Apple raises forecast"), evidence("e2", "Apple supplier warns of constraints")]


def test_disabled_by_default_returns_none(monkeypatch):
    monkeypatch.setattr(get_settings(), "jev_enabled", False)
    assert jev_guard.review_briefing(briefing(point("Apple raised its forecast.", "e1")), EVIDENCE) is None


def test_each_point_is_checked_against_only_its_cited_evidence():
    fake = FakeJev()
    b = briefing(point("Apple raised its forecast.", "e1"), point("A supplier warned of constraints.", "e2"))

    review = jev_guard.review_briefing(b, EVIDENCE, tool=fake)

    assert review["engine"] == "jev" and review["warnings"] == []
    assert [p["status"] for p in review["points"]] == ["checked", "checked"]
    assert fake.calls[0] == ("Apple raised its forecast.", [{"id": "e1", "title": "Apple raises forecast", "summary": None}])
    assert fake.calls[1][1][0]["id"] == "e2"
    assert fake.calls[2] == ("Mixed picture for Apple Limited data.", [])  # framing check, no evidence


def test_unsupported_point_and_advice_become_warnings_without_editing_the_briefing():
    fake = FakeJev(supported=lambda text: 0.1 if "buyback" in text else 0.9, advice=0.8, promise=0.7)
    b = briefing(point("Apple raised its forecast.", "e1"), point("Apple announced a buyback.", "e2"))
    before = b.model_dump()

    review = jev_guard.review_briefing(b, EVIDENCE, tool=fake)

    assert b.model_dump() == before
    assert review["points"][1]["supported"] == 0.1
    assert any("point 2" in w and "buyback" in w for w in review["warnings"])
    assert any("personal investment advice" in w for w in review["warnings"])
    assert any("outcome as certain" in w for w in review["warnings"])
    assert len(review["warnings"]) == 3


def test_points_citing_only_signals_are_not_checked():
    fake = FakeJev()
    review = jev_guard.review_briefing(briefing(point("Price rose 8.8 percent in 30 days.", "signal-1")), EVIDENCE, tool=fake)
    assert review["points"] == [
        {"index": 0, "status": "not_checked", "reason": "cites no news or social records"}
    ]
    assert len(fake.calls) == 1  # only the framing check


def test_unavailable_is_reported_and_sanitized():
    review = jev_guard.review_briefing(briefing(point("Apple raised its forecast.", "e1")), EVIDENCE, tool=FakeJev(engine="unavailable"))
    assert review["engine"] == "unavailable" and review["warnings"] == []
    assert "SECRET" not in review["error"]


def test_a_crashing_check_returns_none():
    class Boom:
        def check_explanation(self, text, items):
            raise RuntimeError("boom")

    assert jev_guard.review_briefing(briefing(point("x.", "e1")), EVIDENCE, tool=Boom()) is None


def test_generate_briefing_attaches_review_and_warnings(monkeypatch):
    from scraper_analysis.agents import synthesis_agent as sa
    from scraper_analysis.storage import store as store_module

    store = store_module.InMemoryEvidenceStore()
    store.save_evidence(EVIDENCE)
    fake = FakeJev(supported=0.2)
    monkeypatch.setattr(jev_guard, "review_briefing", lambda b, e: jev_guard._review(b, e, fake))

    class Agent:
        def __init__(self, tools):
            self.tools = tools

        def __call__(self, _prompt):
            self.tools[0]()  # get_evidence, so the ids count as retrieved
            return (
                '{"headline": "h", "overall_tone": "neutral", "uncertainty": "u", "conflicts": [], "data_gaps": [],'
                ' "points": [{"theme": "news", "text": "Apple announced a buyback.", "direction": "positive",'
                ' "evidence_ids": ["e1"]}]}'
            )

    out = sa.generate_briefing("AAPL", store=store, agent_factory=lambda prompt, tools=None: Agent(tools))

    assert out["status"] == "ok" and len(out["briefing"]["points"]) == 1  # nothing dropped
    assert out["meta"]["jev_review"]["points"][0]["supported"] == 0.2
    assert "warnings" not in out["meta"]["jev_review"]
    assert any("point 1" in w for w in out["warnings"])
