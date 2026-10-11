"""Jev judgment at ingestion: additive, off by default, never touches the network here."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from scraper_analysis.api import app
from scraper_analysis.config import get_settings
from scraper_analysis.models.evidence import Credibility, Evidence, Sentiment
from scraper_analysis.pipeline import ingest, jev_judge
from scraper_analysis.storage import store as store_module

NOW = datetime(2026, 10, 10, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    # Same isolation as tests/test_api.py: in-memory store, reset per test.
    monkeypatch.setattr(store_module, "_store", store_module.InMemoryEvidenceStore())
    yield
    monkeypatch.setattr(store_module, "_store", None)


def make_evidence(source_type="general_news", **overrides) -> Evidence:
    fields = {
        "id": "e1",
        "symbol": "AAPL",
        "title": "Apple reports record quarterly revenue",
        "summary": "Apple said revenue rose to a record.",
        "source_name": "CNBC",
        "source_type": source_type,
        "retrieved_at": NOW,
        "sentiment": Sentiment(direction="Bullish", score=0.8),
        "credibility": Credibility(overall_score=0.7),
        "details": {"existing": "kept"},
    }
    return Evidence(**{**fields, **overrides})


class FakeJev:
    """Stands in for jev_tool.JevTool.judge_evidence_items."""

    def __init__(self, engine="jev"):
        self.engine = engine
        self.calls = []

    def judge_evidence_items(self, items, companies):
        self.calls.append((items, companies))
        if self.engine != "jev":
            return [SimpleNamespace(engine="unavailable", error="Jev timed out api_key=SECRET") for _ in items]
        return [
            SimpleNamespace(
                engine="jev",
                error=None,
                model="jev-1.13.0",
                question_set_version="article-v3",
                request_id="req_test",
                relevant=0.98,
                direction="positive",
                direction_confidence=0.9,
                content_type="news_report",
                content_type_confidence=0.95,
                event_type="earnings_or_guidance",
                event_type_confidence=0.9,
                upcoming_event=0.05,
                materiality=1.9,
                materiality_confidence=0.8,
            )
            for _ in items
        ]


def test_judgment_is_added_under_details_and_nothing_else_changes():
    evidence = make_evidence()
    before = evidence.model_dump()
    fake = FakeJev()

    jev_judge.judge_evidence([evidence], tool=fake)

    judgment = evidence.details["jev"]
    assert judgment["engine"] == "jev"
    assert (judgment["direction"], judgment["event_type"], judgment["relevant"]) == (
        "positive",
        "earnings_or_guidance",
        0.98,
    )
    assert judgment["question_set_version"] == "article-v3" and judgment["request_id"] == "req_test"
    after = evidence.model_dump()
    assert after["details"].pop("jev") and after == before  # only details["jev"] was added

    items, companies = fake.calls[0]
    assert items == [
        {"id": "e1", "symbol": "AAPL", "title": evidence.title, "summary": evidence.summary}
    ]
    assert companies == {"AAPL": "Apple"}


def test_filings_and_disclosures_are_not_sent_to_jev():
    filing = make_evidence("sec_filing", id="f1")
    disclosure = make_evidence("congressional_disclosure", id="c1")
    post = make_evidence("social_media", id="s1")
    fake = FakeJev()

    jev_judge.judge_evidence([filing, disclosure, post], tool=fake)

    assert [i["id"] for i in fake.calls[0][0]] == ["s1"]
    assert "jev" not in filing.details and "jev" not in disclosure.details
    assert post.details["jev"]["engine"] == "jev"


def test_unavailable_is_recorded_not_faked_and_error_is_sanitized():
    evidence = make_evidence()
    jev_judge.judge_evidence([evidence], tool=FakeJev(engine="unavailable"))

    judgment = evidence.details["jev"]
    assert judgment["engine"] == "unavailable"
    assert "direction" not in judgment
    assert "SECRET" not in judgment["error"]


def test_unknown_symbol_falls_back_to_the_ticker_as_company_name():
    assert jev_judge.company_name("ZZZZ") == "ZZZZ"
    assert jev_judge.company_name("nvda") == "Nvidia"


def test_disabled_by_default_is_a_no_op(monkeypatch):
    monkeypatch.setattr(get_settings(), "jev_enabled", False)
    evidence = make_evidence()
    before = evidence.model_dump()
    assert jev_judge.judge_evidence([evidence]) == [evidence]
    assert evidence.model_dump() == before


def test_a_crashing_judge_leaves_records_untouched():
    class Boom:
        def judge_evidence_items(self, items, companies):
            raise RuntimeError("boom")

    evidence = make_evidence()
    before = evidence.model_dump()
    jev_judge.judge_evidence([evidence], tool=Boom())
    assert evidence.model_dump() == before


def test_ingest_calls_judge_only_when_asked(monkeypatch):
    seen = []
    monkeypatch.setattr(ingest, "judge_evidence", lambda items: seen.append(len(items)) or items)

    ingest.ingest_evidence("AAPL", allow_live=False, tag=False, judge=False)
    assert seen == []
    ingest.ingest_evidence("AAPL", allow_live=False, tag=False, judge=True)
    assert len(seen) == 1


def test_ingest_endpoint_exposes_judgment_when_enabled(monkeypatch):
    fake = FakeJev()
    monkeypatch.setattr(ingest, "judge_evidence", lambda items: jev_judge.judge_evidence(items, tool=fake))

    body = TestClient(app).post("/ingest/run", params={"symbol": "AAPL", "live": False, "tag": False}).json()

    by_type = {}
    for item in body["evidence"]:
        by_type.setdefault(item["source_type"], []).append(item)
    assert by_type.get("general_news"), "fixtures should include news"
    assert all(i["details"]["jev"]["engine"] == "jev" for i in by_type["general_news"])
    assert all("jev" not in i["details"] for i in by_type.get("sec_filing", []))
    assert all(i["details"]["jev"]["engine"] == "jev" for i in by_type.get("social_media", []))

    stored = TestClient(app).get("/evidence", params={"symbol": "AAPL"}).json()["evidence"]
    assert any("jev" in i["details"] for i in stored)  # the judgment is persisted with the record


def test_ingest_endpoint_judge_false_skips_jev(monkeypatch):
    fake = FakeJev()
    monkeypatch.setattr(ingest, "judge_evidence", lambda items: jev_judge.judge_evidence(items, tool=fake))

    body = TestClient(app).post(
        "/ingest/run", params={"symbol": "AAPL", "live": False, "tag": False, "judge": False}
    ).json()

    assert body["count"] >= 1 and fake.calls == []
    assert all("jev" not in i["details"] for i in body["evidence"])
