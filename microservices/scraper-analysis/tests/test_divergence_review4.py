"""Regression tests for the fourth PR #15 review (hbot on 69641a3):

1. an invalid Senate trade date (unparseable, impossible, in the future or
   after the filing date) is never replaced by the filing date: the record
   keeps observed_at=None, reports details.date_issue and the raw
   details.transaction_date_reported, gets no reporting lag / timing, and
   divergence never treats it as a dated trade;
2. the synthesis get_divergences tool analyzes the raw stored records (as
   the /divergence endpoint does), so excluded.sample is complete.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from scraper_analysis.agents import synthesis_agent as sa
from scraper_analysis.api import app
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.models.signal import Signal
from scraper_analysis.pipeline import divergence as dv
from scraper_analysis.pipeline.normalize import normalize
from scraper_analysis.sources.congressional import SenateEfdAdapter
from scraper_analysis.storage import store as store_module

REAL_NOW = datetime.now(timezone.utc)
TODAY = REAL_NOW.replace(hour=0, minute=0, second=0, microsecond=0)
FILED = TODAY - timedelta(days=5)


def mdy(t: datetime) -> str:
    return t.strftime("%m/%d/%Y")


def detail_html(tx_date: str, tx_type: str = "Purchase") -> str:
    return (
        "<table><tbody><tr><td>1</td>"
        f"<td>{tx_date}</td><td>Self</td><td>AAPL</td><td>Apple Inc.</td><td>Stock</td>"
        f"<td>{tx_type}</td><td>$15,001 - $50,000</td><td>--</td></tr></tbody></table>"
    )


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, text):
        self._text = text

    def get(self, _url):
        return _Resp(self._text)


def scan(tx_date: str, filed: datetime = FILED, tx_type: str = "Purchase"):
    row = ["Jane", "Doe", "Doe, Jane", '<a href="/search/view/ptr/abc-123/">PTR</a>', mdy(filed)]
    return SenateEfdAdapter()._scan_filing(_Client(detail_html(tx_date, tx_type)), row, "AAPL", REAL_NOW)


def price(value=9.0):
    return Signal(symbol="AAPL", name="30-day price change", value=value, unit="percent", window="30d",
                  as_of=TODAY, source="yf", data_mode="live")


def form4(sell=0.0, buy=0.0, mode="live"):
    when = TODAY - timedelta(days=10)
    return Evidence(symbol="AAPL", title=f"f4 {mode} {sell} {buy}", source_name="SEC EDGAR", source_type="sec_filing",
                    retrieved_at=REAL_NOW, observed_at=when, published_at=when, data_mode=mode,
                    details={"buy_shares": 1 if buy else 0, "sell_shares": 1 if sell else 0,
                             "buy_value_usd": buy, "sell_value_usd": sell, "is_10b5_1": False, "other_codes": {}})


@pytest.fixture
def store(monkeypatch):
    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    yield s
    monkeypatch.setattr(store_module, "_store", None)


client = TestClient(app)


# --- Finding 1: invalid Senate trade dates ---------------------------------

INVALID = {
    "unparseable": "13/45/2026",
    "impossible": "02/30/2026",
    "garbage": "--",
    "after_filing": mdy(FILED + timedelta(days=2)),
    "future": mdy(TODAY + timedelta(days=30)),
}


@pytest.mark.parametrize("label", sorted(INVALID))
def test_invalid_senate_trade_date_is_not_replaced_by_filing_date(label):
    raw = INVALID[label]
    (rec,) = scan(raw)
    assert rec.observed_at is None
    assert rec.published_at == FILED
    assert rec.payload["date_issue"]
    assert rec.payload["transaction_date"] == raw


@pytest.mark.parametrize("label", sorted(INVALID))
def test_invalid_senate_trade_date_normalizes_without_lag_or_timing(label):
    raw = INVALID[label]
    (rec,) = scan(raw)
    ev = normalize(rec, "live")
    assert ev.observed_at is None
    assert ev.reporting_lag_days is None
    assert ev.details["timing"] is None
    assert ev.details["date_issue"]
    assert ev.details["transaction_date_reported"] == raw
    assert "invalid trade date" in ev.title


def test_valid_senate_trade_date_is_kept():
    traded = FILED - timedelta(days=20)
    (rec,) = scan(mdy(traded))
    assert rec.observed_at == traded and rec.payload["date_issue"] is None
    ev = normalize(rec, "live")
    assert ev.reporting_lag_days == pytest.approx(20)
    assert ev.details["timing"] is not None and not ev.details.get("date_issue")


def test_invalid_senate_trade_date_never_counts_in_divergence():
    # Pre-fix the filing date stood in for the trade date, so this Senate
    # purchase was "dated" and flagged against the insider sale.
    (rec,) = scan(INVALID["after_filing"])
    senate = normalize(rec, "live")
    r = dv.analyze("AAPL", [senate, form4(sell=300_000)], [], as_of=REAL_NOW)
    assert "congress_buying_insiders_selling" not in {f["id"] for f in r["flags"]}
    assert r["excluded"]["invalid_date"] == 1
    assert all(senate.id not in f["evidence_ids"] for f in r["flags"])


# --- Finding 2: synthesis tool sees raw records for excluded counts --------

def test_synthesis_tool_excluded_sample_matches_endpoint(store):
    store.save_evidence([form4(sell=500_000), form4(buy=1_000, mode="sample"), form4(sell=7_000, mode="sample")])
    store.save_signals([price(9.0)])
    endpoint = client.get("/divergence", params={"symbol": "AAPL"}).json()
    assert endpoint["excluded"]["sample"] == 2
    tool = sa.build_tools(store, "AAPL", set())[3]
    out = json.loads(tool())
    assert out["excluded"] == endpoint["excluded"]
    assert {f["id"] for f in out["flags"]} == {f["id"] for f in endpoint["flags"]}


def test_synthesis_tool_record_selection_for_other_tools_is_unchanged(store):
    live = form4(sell=500_000)
    store.save_evidence([live, form4(buy=1_000, mode="sample")])
    store.save_signals([price(9.0)])
    rows = json.loads(sa.build_tools(store, "AAPL", set())[0]())
    assert [r["id"] for r in rows] == [live.id]
