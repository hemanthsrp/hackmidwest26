"""PR #17 review (hbot): "an invalid House trade date still produced a buying
signal through the endpoints". End to end through the API with an in-memory
store: House rows are ingested via /ingest/run (adapter network replaced),
next to a live fresh price and a live discretionary Form 4 sale, then
/divergence, /evidence and /briefing (fake agent driving the real tools) are
checked so no path counts the invalid-dated purchases as congressional
buying."""

import functools
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from scraper_analysis.agents import synthesis_agent as sa
from scraper_analysis.api import app
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.models.signal import Signal
from scraper_analysis.pipeline import ingest
from scraper_analysis.sources import house_clerk as h
from scraper_analysis.sources import market_signals
from scraper_analysis.sources.base import SourceUnavailableError
from scraper_analysis.storage import store as store_module

NOW = datetime.now(timezone.utc)
MIDNIGHT = NOW.replace(hour=0, minute=0, second=0, microsecond=0)


def _d(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%m/%d/%Y")


def _house_row(tx, notified, owner):
    return {"ticker": "AAPL", "asset_name": "Apple Inc.", "asset_type_code": "ST", "transaction_type": "Purchase",
            "transaction_date": tx, "notification_date": notified, "amount_range": "$1,001 - $15,000",
            "owner": owner}


# Every way the adapter rejects a trade date; all are purchases filed 10 days
# ago, so the filing date (published_at) is inside the divergence window.
INVALID_ROWS = [
    _house_row("02/30/2026", _d(12), "Self"),  # impossible calendar date
    _house_row(_d(-5), _d(-5), "Spouse"),  # after retrieval
    _house_row(_d(5), _d(5), "Joint"),  # after the filing date
    _house_row(_d(15), _d(20), "Dependent Child"),  # after the notification date
]


@pytest.fixture
def stored(monkeypatch):
    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    h._pdf_cache.clear()
    filing = h.HouseFiling("777", NOW.year, NOW - timedelta(days=10), "Jane Example")
    monkeypatch.setattr(h, "_load_index", lambda client, year: [filing])
    monkeypatch.setattr(h, "_load_transactions", lambda client, f: [dict(r) for r in INVALID_ROWS])
    monkeypatch.setattr(ingest, "build_adapters", lambda: [h.HouseClerkAdapter()])
    monkeypatch.setattr(market_signals, "fetch_live",
                        lambda sym: (_ for _ in ()).throw(SourceUnavailableError("offline in tests")))
    resp = TestClient(app).post("/ingest/run?symbol=AAPL&fallback=false&tag=false")
    assert resp.status_code == 200, resp.text
    (src,) = [x for x in resp.json()["sources"] if x["name"] == "house_clerk"]
    assert src["status"] == "live" and src["count"] == len(INVALID_ROWS)

    # A live, fresh price and a live discretionary Form 4 sale: with any
    # congressional "buying" this would raise congress_buying_insiders_selling.
    s.save_signals([Signal(symbol="AAPL", name="30-day price change", value=8.0, unit="percent", window="30d",
                           as_of=MIDNIGHT, source="yf", data_mode="live")])
    s.save_evidence([Evidence(symbol="AAPL", title="Form 4 sale", source_name="SEC EDGAR", source_type="sec_filing",
                              retrieved_at=NOW, observed_at=NOW - timedelta(days=5),
                              published_at=NOW - timedelta(days=4), data_mode="live",
                              details={"buy_shares": 0, "sell_shares": 1000, "buy_value_usd": 0.0,
                                       "sell_value_usd": 500_000.0, "is_10b5_1": False, "other_codes": {}})])
    yield s
    monkeypatch.setattr(store_module, "_store", None)


def test_divergence_endpoint_never_counts_invalid_house_dates(stored):
    body = TestClient(app).get("/divergence", params={"symbol": "AAPL"}).json()
    assert body["legs"]["insider"]["direction"] == "selling"  # the rest of the pipeline is live and working
    assert body["legs"]["congress"]["direction"] is None
    assert all(f["id"] != "congress_buying_insiders_selling" for f in body["flags"])
    house_ids = {e.id for e in stored.query_evidence("AAPL") if e.source_name == "House Clerk"}
    assert not house_ids & {i for f in body["flags"] for i in f["evidence_ids"]}
    assert not house_ids & set(body["legs"]["congress"]["evidence_ids"])
    assert body["excluded"]["invalid_date"] == len(INVALID_ROWS)


def test_evidence_endpoint_marks_invalid_house_dates(stored):
    body = TestClient(app).get("/evidence", params={"symbol": "AAPL"}).json()
    house = [e for e in body["evidence"] if e["source_name"] == "House Clerk"]
    assert len(house) == len(INVALID_ROWS)
    for e in house:
        assert e["observed_at"] is None and e["reporting_lag_days"] is None
        assert e["details"]["date_issue"] and e["details"]["timing"] is None
        # The record still says what was reported, but flags that its date is unusable.
        assert "invalid trade date" in e["title"]


def test_briefing_tools_never_present_invalid_house_dates_as_buying(stored, monkeypatch):
    seen = {}

    class ToolAgent:
        def __init__(self, tools):
            self.tools = {t.tool_name: t for t in tools}

        def __call__(self, _prompt):
            seen["divergences"] = json.loads(self.tools["get_divergences"]())
            seen["evidence"] = json.loads(self.tools["get_evidence"]("congressional_disclosure"))
            ids = [r["id"] for r in seen["evidence"]]
            return json.dumps({"headline": "h", "overall_tone": "mixed", "conflicts": [], "data_gaps": [],
                               "uncertainty": "u",
                               "points": [{"theme": "congressional", "text": "t", "direction": "neutral",
                                           "evidence_ids": ids}]})

    monkeypatch.setattr(sa, "generate_briefing", functools.partial(
        sa.generate_briefing, agent_factory=lambda system_prompt, tools=None: ToolAgent(tools)))
    resp = TestClient(app).post("/briefing", params={"symbol": "AAPL"})
    assert resp.status_code == 200, resp.text

    div = seen["divergences"]
    assert div["legs"]["congress"]["direction"] is None
    assert all(f["id"] != "congress_buying_insiders_selling" for f in div["flags"])
    assert div["excluded"]["invalid_date"] == len(INVALID_ROWS)
    # get_evidence still lists the rows (they are real filings), but each is
    # explicitly marked as having no usable trade date and no direction.
    assert len(seen["evidence"]) == len(INVALID_ROWS)
    for r in seen["evidence"]:
        assert r["observed_at"] is None
        assert r["date_valid"] is False and r["direction_usable"] is False
    assert "invalid" in sa.SYSTEM_PROMPT and "date_valid" in sa.SYSTEM_PROMPT
