"""Review findings on the scheduler: status must say what was actually written,
and an all-empty "live" run is not a clean success. Offline, in-memory store."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from scraper_analysis import api as api_module
from scraper_analysis import scheduler as sch
from scraper_analysis.pipeline import ingest
from scraper_analysis.sources import market_signals
from scraper_analysis.sources.base import FetchResult, SourceUnavailableError
from scraper_analysis.storage import store as store_module


@pytest.fixture
def store(monkeypatch):
    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    yield s
    monkeypatch.setattr(store_module, "_store", None)


def run_scheduler(live=False, fallback=True):
    """One scheduled attempt through the REAL ingest_symbol."""
    def real_ingest(symbol, allow_live, tag, fb, **kw):
        return ingest.ingest_symbol(symbol, live, False, fallback, **kw)

    async def go():
        s = sch.Scheduler(["AAPL"], tag=False, ingest_fn=real_ingest)
        await s.run_once()
        return s.status()["symbols"]["AAPL"]

    return asyncio.run(go())


# --- evidence saved, then the signals step fails ----------------------------

def boom_signals(monkeypatch, message="yfinance exploded"):
    def boom(*a, **k):
        raise RuntimeError(message)
    monkeypatch.setattr(ingest, "ingest_signals", boom)


def test_scheduler_reports_what_was_persisted_before_the_signal_failure(store, monkeypatch):
    boom_signals(monkeypatch)
    status = run_scheduler()
    saved = len(store.query_evidence("AAPL"))
    assert saved > 0
    assert status["new_evidence"] == saved  # was 0 while `saved` rows were in the store
    assert status["ok"] is False and status["partial"] is True
    assert "saved" in status["error"] and "yfinance exploded" in status["error"]
    assert status["consecutive_failures"] == 1
    assert status["sources"]  # the evidence step's per-source report survives


def test_partial_failure_is_a_distinct_error_carrying_what_was_saved(store, monkeypatch):
    boom_signals(monkeypatch)
    with pytest.raises(ingest.IngestPartialFailure) as caught:
        ingest.ingest_symbol("AAPL", allow_live=False, tag=False)
    assert len(caught.value.evidence) == len(store.query_evidence("AAPL"))
    assert isinstance(caught.value.__cause__, RuntimeError)


def test_cancellation_still_passes_through_unwrapped(store, monkeypatch):
    stop = {"now": False}

    def cancelling_signals(symbol, allow_live, fallback, should_stop, evidence_saved):
        raise ingest.IngestCancelled("stop", evidence_saved=evidence_saved)

    monkeypatch.setattr(ingest, "ingest_signals", cancelling_signals)
    with pytest.raises(ingest.IngestCancelled) as caught:
        ingest.ingest_symbol("AAPL", allow_live=False, tag=False)
    assert caught.value.evidence_saved > 0 and stop["now"] is False


def test_secrets_in_the_underlying_error_are_redacted_in_status(store, monkeypatch):
    boom_signals(monkeypatch, "401 for url 'https://api.example.com/x?api_token=SUPERSECRET99'")
    status = run_scheduler()
    assert "SUPERSECRET99" not in status["error"]


# --- the API reports the same truth -----------------------------------------

def test_ingest_endpoint_returns_the_saved_evidence_with_a_warning_not_a_bare_500(store, monkeypatch):
    boom_signals(monkeypatch, "boom https://x.example/y?token=TOPSECRET77")
    r = TestClient(api_module.app).post("/ingest/run", params={"symbol": "AAPL", "live": False, "tag": False})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(store.query_evidence("AAPL")) > 0
    assert body["signals"] == []
    assert any("signals step failed after the evidence was saved" in w for w in body["warnings"])
    assert "TOPSECRET77" not in r.text


# --- an all-empty "live" run -------------------------------------------------

@pytest.fixture
def everything_live_but_empty(monkeypatch):
    class Empty:
        def __init__(self, name):
            self.name = name

        def fetch_result(self, symbol, allow_live=True, fallback=True):
            return FetchResult([], "live", "live")

    monkeypatch.setattr(ingest, "build_adapters", lambda: [Empty("a"), Empty("b")])
    monkeypatch.setattr(market_signals, "fetch_result", lambda *a, **k: FetchResult([], "live", "live"))


def test_every_live_source_returning_nothing_is_not_a_clean_success(store, everything_live_but_empty):
    status = run_scheduler(live=True, fallback=False)
    assert status["fetched"] == 0
    assert status["ok"] is False and status["partial"] is True
    assert any("returned zero items" in n for n in status["notes"])
    assert "partial coverage" in status["error"]


def test_zero_new_rows_is_still_healthy_when_sources_returned_data(store, monkeypatch):
    # Second run: everything already stored -> 0 new rows, but real data came back.
    from datetime import datetime, timezone

    from scraper_analysis.models.signal import Signal
    from scraper_analysis.sources.base import RawRecord

    class Up:
        name = "up"

        def fetch_result(self, symbol, allow_live=True, fallback=True):
            record = RawRecord(source_name="up", source_type="general_news", symbol=symbol,
                               payload={"title": "Apple story"}, url="https://x/1")
            return FetchResult([record], "live", "live")

    price = Signal(symbol="AAPL", name="30-day price change", value=1.0, unit="percent", window="30d",
                   as_of=datetime(2026, 10, 9, tzinfo=timezone.utc), source="yf", data_mode="live")
    monkeypatch.setattr(ingest, "build_adapters", lambda: [Up()])
    monkeypatch.setattr(market_signals, "fetch_result", lambda *a, **k: FetchResult([price], "live", "live"))
    run_scheduler(live=True, fallback=False)
    again = run_scheduler(live=True, fallback=False)
    assert again["new_evidence"] == 0 and again["fetched"] == 2
    assert again["ok"] is True and again["partial"] is False and again["notes"] == []


def test_a_down_source_is_still_reported_as_before(store, monkeypatch):
    class Down:
        name = "down"

        def fetch_result(self, symbol, allow_live=True, fallback=True):
            return FetchResult([], "live", "unavailable", "upstream 503")

    class Up:
        name = "up"

        def fetch_result(self, symbol, allow_live=True, fallback=True):
            from scraper_analysis.sources.base import RawRecord
            return FetchResult([RawRecord(source_name="up", source_type="general_news", symbol=symbol,
                                          payload={"title": "Apple story"}, url="https://x/1")], "live", "live")

    monkeypatch.setattr(ingest, "build_adapters", lambda: [Down(), Up()])
    monkeypatch.setattr(market_signals, "fetch_result", lambda *a, **k: FetchResult([], "live", "live"))
    status = run_scheduler(live=True, fallback=False)
    assert status["partial"] is True and status["fetched"] == 1
    assert any("down" in n for n in status["notes"])
