"""Regression tests for the fifth PR #15 review (hbot on a57796b): time boundaries.

1. The clock-skew allowance must not stack. With the clock at 22:45, an
   `as_of` of 23:35 is accepted (within the 1 h tolerance), but records dated
   00:00 the next day -- 75 minutes after the real clock -- must still be
   excluded as future-dated. Eligibility is capped at the ACTUAL clock + skew,
   not at the request anchor + skew.
2. A record whose event date is in the window but whose `published_at` is in
   the future (it cannot have been published yet) is future-dated, never
   compared.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from scraper_analysis.api import app
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.models.signal import Signal
from scraper_analysis.pipeline import divergence as dv
from scraper_analysis.storage import store as store_module

CLOCK = datetime(2026, 10, 10, 22, 45, tzinfo=timezone.utc)
AS_OF = datetime(2026, 10, 10, 23, 35, tzinfo=timezone.utc)   # 50 min ahead of the clock: accepted
NEXT_MIDNIGHT = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)  # 75 min ahead of the clock
RECENT = CLOCK - timedelta(days=10)


def price(as_of, value=9.0):
    return Signal(symbol="AAPL", name="30-day price change", value=value, unit="percent", window="30d",
                  as_of=as_of, source="yf", data_mode="live")


def form4(when, published=None, sell=500_000.0):
    details = {"buy_shares": 0, "sell_shares": 1, "buy_value_usd": 0.0, "sell_value_usd": sell,
               "is_10b5_1": False, "other_codes": {}}
    return Evidence(symbol="AAPL", title="f4", source_name="SEC EDGAR", source_type="sec_filing",
                    retrieved_at=CLOCK, observed_at=when, published_at=published or when,
                    data_mode="live", details=details)


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(dv, "_clock", lambda: CLOCK)


@pytest.fixture
def store(monkeypatch, frozen_clock):
    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    yield s
    monkeypatch.setattr(store_module, "_store", None)


client = TestClient(app)


# --- 1. skew does not stack ------------------------------------------------

def test_reviewer_case_via_endpoint_records_75_min_ahead_are_future_dated(store):
    store.save_signals([price(NEXT_MIDNIGHT)])
    store.save_evidence([form4(NEXT_MIDNIGHT)])
    resp = client.get("/divergence", params={"symbol": "AAPL", "as_of": AS_OF.isoformat()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["flags"] == [] and body["status"] == "insufficient_data"
    assert body["excluded"]["future_dated"] == 2
    assert body["window"]["historical"] is False
    assert any("future" in w.lower() for w in body["warnings"])


def test_reviewer_case_via_analyze(frozen_clock):
    r = dv.analyze("AAPL", [form4(NEXT_MIDNIGHT)], [price(NEXT_MIDNIGHT)], as_of=AS_OF)
    assert r["flags"] == [] and r["excluded"]["future_dated"] == 2


def test_record_within_skew_of_the_real_clock_still_counts(frozen_clock):
    within = CLOCK + timedelta(minutes=30)
    r = dv.analyze("AAPL", [form4(RECENT)], [price(within)], as_of=AS_OF)
    assert r["legs"]["price"]["direction"] is not None
    assert r["excluded"]["future_dated"] == 0


def test_window_end_never_passes_the_real_clock_plus_skew(frozen_clock):
    r = dv.analyze("AAPL", [form4(RECENT)], [price(CLOCK)], as_of=AS_OF)
    end = datetime.fromisoformat(r["window"]["end"])
    assert end <= CLOCK + timedelta(hours=dv.CLOCK_SKEW_TOLERANCE_HOURS)


def test_default_request_uses_the_same_ceiling(frozen_clock):
    r = dv.analyze("AAPL", [form4(NEXT_MIDNIGHT)], [price(NEXT_MIDNIGHT)])
    assert r["flags"] == [] and r["excluded"]["future_dated"] == 2


# --- 2. future publication date ----------------------------------------------

def test_in_window_trade_with_future_published_at_is_future_dated(frozen_clock):
    filing = form4(RECENT, published=CLOCK + timedelta(days=2))
    r = dv.analyze("AAPL", [filing], [price(CLOCK - timedelta(hours=2))])
    assert r["legs"]["insider"]["direction"] is None
    assert r["flags"] == []
    assert r["excluded"]["future_dated"] == 1


def test_future_published_at_via_endpoint(store):
    store.save_signals([price(CLOCK - timedelta(hours=2))])
    store.save_evidence([form4(RECENT, published=CLOCK + timedelta(days=2))])
    body = client.get("/divergence", params={"symbol": "AAPL"}).json()
    assert body["flags"] == [] and body["excluded"]["future_dated"] == 1


def test_published_within_skew_still_counts(frozen_clock):
    filing = form4(RECENT, published=CLOCK + timedelta(minutes=20))
    r = dv.analyze("AAPL", [filing], [price(CLOCK - timedelta(hours=2))])
    assert r["excluded"]["future_dated"] == 0
    assert r["legs"]["insider"]["direction"] == "selling"
