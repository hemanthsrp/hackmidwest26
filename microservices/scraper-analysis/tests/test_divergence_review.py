"""Regression tests for the PR #15 review findings on /divergence:

1. fixture (data_mode="sample") records can never contribute to a flag;
2. evidence outside a bounded recency window around the price signal does
   not count (stale Form 4 / Senate / news);
3. a filing with no discretionary open-market P/S (10b5-1 plan trades, tax
   withholding, option exercises) does not make the insider leg usable.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from scraper_analysis.api import app
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.models.signal import Signal
from scraper_analysis.pipeline import divergence as dv
from scraper_analysis.storage import store as store_module

# Price freshness is checked against the request time, so fixtures are dated
# relative to today (midnight UTC, like a real daily close) to stay current.
NOW = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
STALE = datetime(2010, 1, 1, tzinfo=timezone.utc)
RECENT = NOW - timedelta(days=10)


def price(value, mode="live", as_of=NOW):
    return Signal(symbol="AAPL", name="30-day price change", value=value, unit="percent", window="30d",
                  as_of=as_of, source="yf", data_mode=mode)


def form4(buy=0.0, sell=0.0, plan=False, mode="live", when=RECENT, other=None):
    return Evidence(symbol="AAPL", title="f4", source_name="SEC EDGAR", source_type="sec_filing",
                    retrieved_at=NOW, observed_at=when, published_at=when, data_mode=mode,
                    details={"buy_shares": 1 if buy else 0, "sell_shares": 1 if sell else 0,
                             "buy_value_usd": buy, "sell_value_usd": sell, "is_10b5_1": plan,
                             "other_codes": other or {}})


def senate(kind, when=RECENT, mode="live"):
    return Evidence(symbol="AAPL", title="s", source_name="Senate eFD", source_type="congressional_disclosure",
                    retrieved_at=NOW, observed_at=when, published_at=when, data_mode=mode,
                    details={"transaction_type": kind})


def news(direction, when=RECENT, mode="live"):
    return Evidence(symbol="AAPL", title="n", source_name="CNBC", source_type="general_news", retrieved_at=NOW,
                    published_at=when, data_mode=mode,
                    sentiment={"direction": direction, "score": 0.8}, credibility={"overall_score": 0.5})


def flag_ids(result):
    return {f["id"] for f in result["flags"]}


# --- Finding 1: fixtures never trigger a flag ------------------------------

def test_sample_only_inputs_never_flag():
    r = dv.analyze("AAPL", [form4(sell=500_000, mode="sample")], [price(9.0, mode="sample")])
    assert r["flags"] == []
    assert r["status"] == "insufficient_data"
    assert any("sample" in w.lower() for w in r["warnings"])
    assert r["excluded"]["sample"] == 2


def test_sample_record_cannot_fill_a_leg_next_to_live_data():
    # Live price, but the only Form 4 is a fixture: the insider leg must stay empty.
    r = dv.analyze("AAPL", [form4(sell=500_000, mode="sample")], [price(9.0)])
    assert r["legs"]["insider"]["direction"] is None
    assert r["flags"] == []


def test_sample_price_cannot_fill_the_price_leg():
    r = dv.analyze("AAPL", [form4(sell=500_000)], [price(9.0, mode="sample")])
    assert r["legs"]["price"]["direction"] is None
    assert r["flags"] == []


@pytest.fixture
def store(monkeypatch):
    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    yield s
    monkeypatch.setattr(store_module, "_store", None)


client = TestClient(app)


def test_endpoint_with_only_fixtures_returns_no_flags(store):
    store.save_evidence([form4(sell=500_000, mode="sample")])
    store.save_signals([price(9.0, mode="sample")])
    body = client.get("/divergence", params={"symbol": "AAPL"}).json()
    assert body["flags"] == []
    assert body["status"] == "insufficient_data"
    assert any("sample" in w.lower() for w in body["warnings"])


# --- Finding 2: stale evidence is out of window ----------------------------

def test_stale_live_form4_does_not_pair_with_current_price():
    r = dv.analyze("AAPL", [form4(sell=500_000, when=STALE)], [price(9.0)])
    assert r["flags"] == []
    assert r["legs"]["insider"]["direction"] is None
    assert r["excluded"]["out_of_window"] == 1
    assert any("window" in w for w in r["warnings"])


def test_stale_senate_trades_do_not_count():
    ev = [senate("Purchase", when=STALE), senate("Purchase", when=STALE), form4(sell=300_000)]
    r = dv.analyze("AAPL", ev, [price(0.0)])
    assert r["legs"]["congress"]["direction"] is None
    assert "congress_buying_insiders_selling" not in flag_ids(r)


def test_stale_news_does_not_count():
    r = dv.analyze("AAPL", [news("Bullish", when=STALE) for _ in range(3)], [price(-9.0)])
    assert r["legs"]["news"]["direction"] is None
    assert r["flags"] == []


def test_evidence_far_after_the_price_signal_does_not_count():
    later = NOW + timedelta(days=dv.RECENCY_LOOKBACK_DAYS)
    r = dv.analyze("AAPL", [form4(sell=500_000, when=later)], [price(9.0)])
    assert r["flags"] == []


def test_undated_evidence_does_not_count():
    undated = Evidence(symbol="AAPL", title="f4", source_name="SEC EDGAR", source_type="sec_filing",
                       retrieved_at=NOW, data_mode="live",
                       details={"buy_shares": 0, "sell_shares": 1, "buy_value_usd": 0.0,
                                "sell_value_usd": 500_000.0, "is_10b5_1": False})
    r = dv.analyze("AAPL", [undated], [price(9.0)])
    assert r["flags"] == [] and r["excluded"]["undated"] == 1


def test_in_window_evidence_still_flags_and_window_is_reported():
    edge = NOW - timedelta(days=dv.RECENCY_LOOKBACK_DAYS - 1)
    r = dv.analyze("AAPL", [form4(sell=500_000, when=edge)], [price(9.0)])
    assert flag_ids(r) == {"insiders_selling_into_rally"}
    assert r["window"]["anchor"] == NOW.isoformat()
    assert r["window"]["lookback_days"] == dv.RECENCY_LOOKBACK_DAYS


def test_without_price_signal_the_window_anchors_on_as_of():
    ev = [senate("Purchase", when=STALE), form4(sell=300_000, when=STALE)]
    assert dv.analyze("AAPL", ev, [], as_of=NOW)["flags"] == []
    fresh = [senate("Purchase"), form4(sell=300_000)]
    assert flag_ids(dv.analyze("AAPL", fresh, [], as_of=NOW)) == {"congress_buying_insiders_selling"}


# --- Finding 3: excluded insider activity is not a usable leg --------------

def test_10b5_1_only_filings_leave_insider_leg_unusable():
    r = dv.analyze("AAPL", [form4(sell=60_000_000, plan=True)], [price(9.0)])
    assert r["legs"]["insider"]["direction"] is None
    assert r["status"] == "insufficient_data" and r["flags"] == []
    assert any("10b5-1" in n for n in r["notes"])


def test_tax_withholding_only_filings_leave_insider_leg_unusable():
    r = dv.analyze("AAPL", [form4(other={"F": 40.0})], [price(9.0)])
    assert r["legs"]["insider"]["direction"] is None
    assert r["status"] == "insufficient_data"


# === Second review (hbot on b8a13ce) ======================================
#
# A. a stale price signal (e.g. 2010) must not anchor the analysis and be
#    presented as a current flag;
# B. evidence outside the price signal's own change window (30d) must not be
#    paired with that price move;
# C. "live only" means data_mode == "live": cached records are excluded too;
# D. excluded counts cover every dropped record, including fixtures the
#    endpoint used to drop before analyze() could count them;
# E. a congressional row with an invalid trade date (observed_at None,
#    details.date_issue set) never falls back to published_at.

def test_stale_2010_price_is_not_a_current_flag():
    r = dv.analyze("AAPL", [form4(sell=500_000, when=STALE)], [price(9.0, as_of=STALE)], as_of=NOW)
    assert r["flags"] == []
    assert r["legs"]["price"]["direction"] is None
    assert r["window"]["anchor"] == NOW.isoformat()  # anchored on request time, not 2010
    assert r["window"]["price_as_of"] == STALE.isoformat()
    assert any("stale" in w.lower() for w in r["warnings"])
    assert r["excluded"]["stale_price"] == 1


def test_price_older_than_freshness_limit_is_unusable():
    old = NOW - timedelta(days=dv.MAX_PRICE_SIGNAL_AGE_DAYS + 1)
    r = dv.analyze("AAPL", [form4(sell=500_000, when=old - timedelta(days=2))], [price(9.0, as_of=old)], as_of=NOW)
    assert r["legs"]["price"]["direction"] is None and r["flags"] == []


def test_fresh_price_reports_its_age():
    r = dv.analyze("AAPL", [form4(sell=500_000)], [price(9.0, as_of=NOW - timedelta(days=3))], as_of=NOW)
    assert flag_ids(r) == {"insiders_selling_into_rally"}
    assert r["window"]["request_time"] == NOW.isoformat()
    assert r["window"]["price_age_days"] == 3.0


def test_endpoint_with_only_2010_data_has_no_flags(store):
    store.save_evidence([form4(sell=500_000, when=STALE)])
    store.save_signals([price(9.0, as_of=STALE)])
    body = client.get("/divergence", params={"symbol": "AAPL"}).json()
    assert body["flags"] == [] and body["status"] == "insufficient_data"


def test_filing_outside_30d_price_window_is_not_compared():
    r = dv.analyze("AAPL", [form4(sell=500_000, when=NOW - timedelta(days=40))], [price(9.0)], as_of=NOW)
    assert r["flags"] == [] and r["legs"]["insider"]["direction"] is None
    assert r["window"]["lookback_days"] == 30


def test_lookback_follows_the_price_signal_window():
    short = Signal(symbol="AAPL", name="30-day price change", value=9.0, unit="percent", window="14d",
                   as_of=NOW, source="yf", data_mode="live")
    r = dv.analyze("AAPL", [form4(sell=500_000, when=NOW - timedelta(days=20))], [short], as_of=NOW)
    assert r["flags"] == [] and r["window"]["lookback_days"] == 14


def test_filing_after_the_price_close_is_not_compared():
    r = dv.analyze("AAPL", [form4(sell=500_000, when=NOW + timedelta(days=2))], [price(9.0)], as_of=NOW)
    assert r["flags"] == []


def test_cached_evidence_does_not_count():
    r = dv.analyze("AAPL", [form4(sell=500_000, mode="cached")], [price(9.0)], as_of=NOW)
    assert r["legs"]["insider"]["direction"] is None and r["flags"] == []
    assert r["excluded"]["cached"] == 1
    assert any("cached" in w.lower() for w in r["warnings"])


def test_cached_price_does_not_count():
    r = dv.analyze("AAPL", [form4(sell=500_000)], [price(9.0, mode="cached")], as_of=NOW)
    assert r["legs"]["price"]["direction"] is None and r["flags"] == []
    assert r["excluded"]["cached"] == 1


def test_endpoint_counts_fixtures_dropped_next_to_live_data(store):
    store.save_evidence([form4(sell=500_000), form4(buy=9_000_000, mode="sample"), news("Bullish", mode="sample")])
    store.save_signals([price(9.0), price(-50.0, mode="sample"), price(1.0, mode="cached")])
    body = client.get("/divergence", params={"symbol": "AAPL"}).json()
    assert flag_ids(body) == {"insiders_selling_into_rally"}
    assert body["excluded"]["sample"] == 3
    assert body["excluded"]["cached"] == 1
    assert body["data_modes"] == ["live"]


def house_bad_date(kind="Purchase"):
    return Evidence(symbol="AAPL", title="h", source_name="House Clerk", source_type="congressional_disclosure",
                    retrieved_at=NOW, observed_at=None, published_at=RECENT, data_mode="live",
                    details={"chamber": "House", "transaction_type": kind,
                             "date_issue": "trade date after filing date"})


def test_invalid_house_trade_date_is_not_a_buying_flag():
    ev = [house_bad_date(), house_bad_date(), form4(sell=300_000)]
    r = dv.analyze("AAPL", ev, [], as_of=NOW)
    assert r["legs"]["congress"]["direction"] is None
    assert "congress_buying_insiders_selling" not in flag_ids(r)
    assert r["excluded"]["invalid_date"] == 2


def test_congress_never_falls_back_to_published_at():
    undated = Evidence(symbol="AAPL", title="h", source_name="House Clerk", source_type="congressional_disclosure",
                       retrieved_at=NOW, observed_at=None, published_at=RECENT, data_mode="live",
                       details={"chamber": "House", "transaction_type": "Purchase"})
    r = dv.analyze("AAPL", [undated, form4(sell=300_000)], [], as_of=NOW)
    assert r["legs"]["congress"]["direction"] is None
    assert r["excluded"]["undated"] == 1


def test_date_issue_excludes_even_with_observed_at():
    e = senate("Purchase")
    e.details["date_issue"] = "trade date after filing date"
    r = dv.analyze("AAPL", [e, form4(sell=300_000)], [], as_of=NOW)
    assert r["legs"]["congress"]["direction"] is None and r["excluded"]["invalid_date"] == 1
