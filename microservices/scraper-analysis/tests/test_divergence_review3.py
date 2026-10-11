"""Regression tests for the third PR #15 review (hbot on c0161f6):

1. a future-dated price (or evidence) can never produce a current flag, and a
   caller-supplied `as_of` is never in the future; a past `as_of` is labelled
   as historical analysis, never presented as current;
2. a multi-day Form 4 is valued only for the trades inside the window
   (per-transaction breakdown); a legacy record without a breakdown whose
   trade dates leave the window is excluded, never valued in full;
3. congressional wording is chamber-neutral (no "Senate" for House trades).
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from scraper_analysis.api import app
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.models.signal import Signal
from scraper_analysis.pipeline import divergence as dv
from scraper_analysis.pipeline.normalize import normalize
from scraper_analysis.sources.base import RawRecord
from scraper_analysis.sources.form4 import parse_form4
from scraper_analysis.storage import store as store_module

REAL_NOW = datetime.now(timezone.utc)
TODAY = REAL_NOW.replace(hour=0, minute=0, second=0, microsecond=0)
RECENT = TODAY - timedelta(days=10)
Y2010 = datetime(2010, 1, 15, tzinfo=timezone.utc)


def price(value=9.0, as_of=TODAY, window="30d"):
    return Signal(symbol="AAPL", name="30-day price change", value=value, unit="percent", window=window,
                  as_of=as_of, source="yf", data_mode="live")


def form4(buy=0.0, sell=0.0, when=RECENT, dates=None, transactions=None):
    details = {"buy_shares": 1 if buy else 0, "sell_shares": 1 if sell else 0,
               "buy_value_usd": buy, "sell_value_usd": sell, "is_10b5_1": False, "other_codes": {}}
    if dates is not None:
        details["transaction_dates"] = dates
    if transactions is not None:
        details["transactions"] = transactions
    return Evidence(symbol="AAPL", title="f4", source_name="SEC EDGAR", source_type="sec_filing",
                    retrieved_at=REAL_NOW, observed_at=when, published_at=when, data_mode="live", details=details)


def congress(kind, chamber, when=RECENT):
    return Evidence(symbol="AAPL", title="c", source_name=f"{chamber} disclosure",
                    source_type="congressional_disclosure", retrieved_at=REAL_NOW, observed_at=when,
                    published_at=when, data_mode="live", details={"transaction_type": kind, "chamber": chamber})


def flag_ids(result):
    return {f["id"] for f in result["flags"]}


def d(t: datetime) -> str:
    return t.date().isoformat()


@pytest.fixture
def store(monkeypatch):
    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    yield s
    monkeypatch.setattr(store_module, "_store", None)


client = TestClient(app)


# --- Finding 1: future-dated data / as_of ----------------------------------

@pytest.mark.parametrize("ahead", [timedelta(hours=12), timedelta(days=20)])
def test_future_dated_price_never_flags(ahead):
    r = dv.analyze("AAPL", [form4(sell=500_000)], [price(as_of=REAL_NOW + ahead)])
    assert r["legs"]["price"]["direction"] is None
    assert r["flags"] == [] and r["status"] == "insufficient_data"
    assert r["excluded"]["future_dated"] == 1
    assert any("future" in w.lower() for w in r["warnings"])


def test_price_within_clock_skew_is_still_usable():
    skew = timedelta(hours=dv.CLOCK_SKEW_TOLERANCE_HOURS) / 2
    r = dv.analyze("AAPL", [form4(sell=500_000)], [price(as_of=REAL_NOW + skew)])
    assert flag_ids(r) == {"insiders_selling_into_rally"}
    assert r["excluded"]["future_dated"] == 0


def test_future_dated_evidence_is_counted_and_never_compared():
    future = REAL_NOW + timedelta(hours=6)
    r = dv.analyze("AAPL", [form4(sell=500_000, when=future)], [price()])
    assert r["legs"]["insider"]["direction"] is None and r["flags"] == []
    assert r["excluded"]["future_dated"] == 1


def test_future_dated_price_and_filing_do_not_return_ok_without_warning(store):
    future = REAL_NOW + timedelta(days=3)
    store.save_evidence([form4(sell=500_000, when=future)])
    store.save_signals([price(as_of=future)])
    body = client.get("/divergence", params={"symbol": "AAPL"}).json()
    assert body["status"] == "insufficient_data" and body["flags"] == []
    assert body["excluded"]["future_dated"] == 2
    assert any("future" in w.lower() for w in body["warnings"])


def test_future_as_of_is_rejected_by_analyze():
    future = REAL_NOW + timedelta(days=30)
    with pytest.raises(ValueError):
        dv.analyze("AAPL", [form4(sell=500_000, when=future - timedelta(days=5))], [price(as_of=future)],
                   as_of=future)


def test_future_as_of_is_rejected_by_endpoint(store):
    future = REAL_NOW + timedelta(days=30)
    store.save_evidence([form4(sell=500_000, when=future - timedelta(days=5))])
    store.save_signals([price(as_of=future)])
    resp = client.get("/divergence", params={"symbol": "AAPL", "as_of": future.isoformat()})
    assert resp.status_code == 400
    assert "future" in resp.text.lower()


def test_2010_as_of_is_labelled_historical_not_current():
    r = dv.analyze("AAPL", [form4(sell=500_000, when=Y2010 - timedelta(days=5))], [price(as_of=Y2010)], as_of=Y2010)
    assert r["window"]["historical"] is True
    assert any("historical" in w.lower() for w in r["warnings"])
    # The flag describes 2010, and is labelled as such.
    assert flag_ids(r) == {"insiders_selling_into_rally"}


def test_2010_as_of_via_endpoint_is_historical(store):
    store.save_evidence([form4(sell=500_000, when=Y2010 - timedelta(days=5))])
    store.save_signals([price(as_of=Y2010)])
    body = client.get("/divergence", params={"symbol": "AAPL", "as_of": Y2010.isoformat()}).json()
    assert body["window"]["historical"] is True
    assert any("historical" in w.lower() for w in body["warnings"])


def test_default_request_is_current_not_historical(store):
    store.save_evidence([form4(sell=500_000)])
    store.save_signals([price()])
    body = client.get("/divergence", params={"symbol": "AAPL"}).json()
    assert body["window"]["historical"] is False
    assert flag_ids(body) == {"insiders_selling_into_rally"}


def test_historical_as_of_ignores_evidence_from_after_it():
    later = Y2010 + timedelta(days=200)
    r = dv.analyze("AAPL", [form4(sell=500_000, when=later)], [price(as_of=Y2010)], as_of=Y2010)
    assert r["legs"]["insider"]["direction"] is None and r["flags"] == []


# --- Finding 2: multi-day Form 4 ----------------------------------------------

def tx(day: datetime, code: str, value: float):
    return {"date": d(day), "code": code, "shares": 1.0, "price": value, "value_usd": value}


def test_multi_day_form4_counts_only_in_window_trades():
    inside, outside = TODAY - timedelta(days=5), TODAY - timedelta(days=45)
    # 50k sold in window, 5M sold 45 days ago; totals say 5.05M.
    f = form4(sell=5_050_000, when=outside, dates=[d(outside), d(inside)],
              transactions=[tx(outside, "S", 5_000_000), tx(inside, "S", 50_000)])
    r = dv.analyze("AAPL", [f], [price()])
    assert r["legs"]["insider"]["inputs"]["discretionary_net_usd"] == -50_000
    assert r["legs"]["insider"]["direction"] == "neutral"
    assert "insiders_selling_into_rally" not in flag_ids(r)


def test_multi_day_form4_observed_inside_values_only_inside():
    inside = TODAY - timedelta(days=20)
    price_asof = TODAY - timedelta(days=3)
    # Earliest trade in the window, a later 900k buy after the price close + grace.
    after = price_asof + timedelta(days=2)
    f = form4(buy=900_000, sell=200_000, when=inside, dates=[d(inside), d(after)],
              transactions=[tx(inside, "S", 200_000), tx(after, "P", 900_000)])
    r = dv.analyze("AAPL", [f], [price(as_of=price_asof)])
    assert r["legs"]["insider"]["inputs"]["discretionary_net_usd"] == -200_000
    assert r["legs"]["insider"]["direction"] == "selling"


def test_legacy_multi_day_form4_partially_out_of_window_is_excluded():
    inside, outside = TODAY - timedelta(days=5), TODAY - timedelta(days=45)
    # No breakdown: observed_at inside, but one trade date is out of window.
    f = form4(sell=5_050_000, when=inside, dates=[d(outside), d(inside)])
    f.observed_at = inside  # deliberately inconsistent legacy record
    r = dv.analyze("AAPL", [f], [price()])
    assert r["legs"]["insider"]["direction"] is None
    assert r["flags"] == []
    assert r["excluded"]["partially_out_of_window"] == 1
    assert any("partially" in w.lower() for w in r["warnings"])


def test_legacy_form4_with_all_dates_in_window_uses_totals():
    a, b = TODAY - timedelta(days=6), TODAY - timedelta(days=4)
    r = dv.analyze("AAPL", [form4(sell=500_000, when=a, dates=[d(a), d(b)])], [price()])
    assert flag_ids(r) == {"insiders_selling_into_rally"}
    assert r["excluded"]["partially_out_of_window"] == 0


MULTI_DAY_XML = """<ownershipDocument>
  <periodOfReport>2026-09-03</periodOfReport>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-09-01</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>100</value></transactionShares>
        <transactionPricePerShare><value>10</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-09-03-05:00</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>50</value></transactionShares>
        <transactionPricePerShare><value>12</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-09-02</value></transactionDate>
      <transactionCoding><transactionCode>F</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>7</value></transactionShares>
        <transactionPricePerShare><value>11</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


def test_parse_form4_has_per_transaction_breakdown():
    f = parse_form4(MULTI_DAY_XML)
    assert f["transactions"] == [
        {"date": "2026-09-01", "code": "S", "shares": 100.0, "price": 10.0, "value_usd": 1000.0},
        {"date": "2026-09-03", "code": "P", "shares": 50.0, "price": 12.0, "value_usd": 600.0},
    ]
    assert f["sell_value_usd"] == 1000.0 and f["buy_value_usd"] == 600.0


def test_normalized_form4_details_carry_transactions():
    f = parse_form4(MULTI_DAY_XML)
    rec = RawRecord(source_name="sec_edgar", source_type="sec_filing", symbol="AAPL",
                    payload={"form_type": "4", "form4": f}, retrieved_at=REAL_NOW,
                    observed_at=datetime(2026, 9, 1, tzinfo=timezone.utc), url="https://www.sec.gov/x")
    e = normalize(rec, "live")
    assert e.details["transactions"] == f["transactions"]
    json.dumps(e.details)  # JSON-serialisable for the store


# --- Finding 3: chamber-neutral wording ---------------------------------------

def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


def test_house_buying_is_not_called_senate():
    ev = [congress("Purchase", "House"), congress("Purchase", "House"), form4(sell=300_000)]
    r = dv.analyze("AAPL", ev, [])
    assert flag_ids(r) == {"congress_buying_insiders_selling"}
    assert r["flags"][0]["title"] == "Members of Congress buying while insiders sell"
    assert not [s for s in _strings(r) if "senate" in s.lower()]


def test_house_selling_flag_title_is_chamber_neutral():
    r = dv.analyze("AAPL", [congress("Sale (Full)", "House"), form4(buy=300_000)], [])
    assert r["flags"][0]["title"] == "Members of Congress selling while insiders buy"
    assert not [s for s in _strings(r) if "senate" in s.lower()]


def test_empty_congress_leg_summary_is_chamber_neutral():
    r = dv.analyze("AAPL", [form4(sell=300_000)], [price()])
    assert r["legs"]["congress"]["summary"] == \
        "No dated congressional (Senate or House) trades in this symbol in the window."
