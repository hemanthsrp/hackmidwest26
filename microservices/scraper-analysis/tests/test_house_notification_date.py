"""PR #17 review (hbot): "an impossible notification date is silently
accepted". The notification date is validated like the trade date. An invalid
one is reported in details.notification_date_issue and no notification-derived
value (notification_date, notification_lag_days) is kept, but a VALID trade
date stays the event date: observed_at, reporting lag and timing are kept and
details.date_issue stays unset (so divergence still counts the trade)."""

from datetime import timedelta

import pytest

from .test_house_clerk import NOW, _d, _ev, adapter, dated_row  # noqa: F401  (adapter is a fixture)


def test_valid_notification_date_is_kept_with_its_lag(adapter, monkeypatch):  # noqa: F811
    (ev,) = _ev(adapter, monkeypatch, [dated_row(_d(20), _d(17))])
    assert ev.details["notification_date_issue"] is None
    assert ev.details["notification_date"] == (NOW - timedelta(days=17)).date().isoformat()
    assert ev.details["notification_lag_days"] == 3
    assert ev.details["notification_date_reported"] == _d(17)


@pytest.mark.parametrize(
    "notified,issue",
    [
        ("02/30/2026", "unparseable"),  # impossible calendar date
        ("13/01/2026", "unparseable"),  # month 13
        ("not a date", "unparseable"),
        ("", "unparseable"),
        (_d(25), "before_trade"),  # notified of the trade before it happened
        (_d(-3), "future"),  # after we retrieved the report
        (_d(5), "after_filing"),  # filing (10 days ago) cannot report a later notification
    ],
)
def test_invalid_notification_date_is_flagged_but_valid_trade_date_is_kept(adapter, monkeypatch, notified, issue):  # noqa: F811
    tx = _d(20)
    (ev,) = _ev(adapter, monkeypatch, [dated_row(tx, notified)])
    d = ev.details
    assert d["notification_date_issue"] == issue
    assert d["notification_date"] is None and d["notification_lag_days"] is None  # never used for timing
    assert d["notification_date_reported"] == notified  # what the filer wrote is still visible
    # The trade date itself is valid, so the record stays dated and usable.
    assert not d.get("date_issue")
    assert ev.observed_at is not None and ev.observed_at.strftime("%m/%d/%Y") == tx
    assert ev.reporting_lag_days == pytest.approx(10, abs=1)
    assert d["timing"] == "Recent Disclosure"
    assert "invalid trade date" not in ev.title


def test_invalid_trade_and_notification_dates_are_both_reported(adapter, monkeypatch):  # noqa: F811
    (ev,) = _ev(adapter, monkeypatch, [dated_row("02/30/2026", "13/01/2026")])
    assert ev.details["date_issue"] == "unparseable" and ev.observed_at is None
    assert ev.details["notification_date_issue"] == "unparseable"
    assert ev.details["notification_lag_days"] is None


def test_end_to_end_invalid_notification_keeps_the_dated_purchase(monkeypatch):
    """Through /ingest/run, /evidence and /divergence (in-memory store): a
    purchase with a valid trade date but an impossible notification date is
    stored dated, marked, and still counts as congressional buying."""
    from fastapi.testclient import TestClient

    from scraper_analysis.api import app
    from scraper_analysis.pipeline import ingest
    from scraper_analysis.sources import house_clerk as h
    from scraper_analysis.sources import market_signals
    from scraper_analysis.sources.base import SourceUnavailableError
    from scraper_analysis.storage import store as store_module

    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    h._pdf_cache.clear()
    f = h.HouseFiling("901", NOW.year, NOW - timedelta(days=10), "Jane Example")
    monkeypatch.setattr(h, "_load_index", lambda client, year: [f])
    monkeypatch.setattr(h, "_load_transactions", lambda client, f_: [dated_row(_d(15), "02/30/2026")])
    monkeypatch.setattr(ingest, "build_adapters", lambda: [h.HouseClerkAdapter()])
    monkeypatch.setattr(market_signals, "fetch_live",
                        lambda sym: (_ for _ in ()).throw(SourceUnavailableError("offline in tests")))
    try:
        client = TestClient(app)
        assert client.post("/ingest/run?symbol=AAPL&fallback=false&tag=false").status_code == 200
        (e,) = [e for e in client.get("/evidence", params={"symbol": "AAPL"}).json()["evidence"]
                if e["source_name"] == "House Clerk"]
        assert e["observed_at"] is not None and e["details"]["date_issue"] is None
        assert e["details"]["notification_date_issue"] == "unparseable"
        assert e["details"]["notification_date"] is None and e["details"]["notification_lag_days"] is None
        body = client.get("/divergence", params={"symbol": "AAPL"}).json()
        assert body["legs"]["congress"]["direction"] == "buying"
        assert body["excluded"]["invalid_date"] == 0
    finally:
        monkeypatch.setattr(store_module, "_store", None)
