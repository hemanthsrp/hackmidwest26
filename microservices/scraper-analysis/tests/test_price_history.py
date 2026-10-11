import pandas as pd
import pytest
from fastapi.testclient import TestClient

from scraper_analysis.api import app
from scraper_analysis.sources import price_history
from scraper_analysis.sources.base import SourceUnavailableError


def _frame(closes):
    index = pd.date_range("2026-10-05", periods=len(closes), freq="D", tz="America/New_York")
    return pd.DataFrame({"Close": closes}, index=index)


def _ticker(frame):
    class _Ticker:
        def __init__(self, symbol):
            pass

        def history(self, **kwargs):
            return frame

    return _Ticker


def test_fetch_live_returns_utc_closes(monkeypatch):
    monkeypatch.setattr(price_history.yf, "Ticker", _ticker(_frame([100.0, 101.5, 99.25])))
    points = price_history.fetch_live("AAPL", "1W")
    assert [p["close"] for p in points] == [100.0, 101.5, 99.25]
    assert all(p["t"].endswith("Z") for p in points)


def test_fetch_live_drops_missing_closes(monkeypatch):
    monkeypatch.setattr(price_history.yf, "Ticker", _ticker(_frame([100.0, float("nan"), 102.0])))
    assert [p["close"] for p in price_history.fetch_live("AAPL", "1M")] == [100.0, 102.0]


@pytest.mark.parametrize("frame", [_frame([]), _frame([100.0])])
def test_fetch_live_refuses_empty_or_single_point_history(monkeypatch, frame):
    monkeypatch.setattr(price_history.yf, "Ticker", _ticker(frame))
    with pytest.raises(SourceUnavailableError):
        price_history.fetch_live("AAPL", "1M")


def test_fetch_live_wraps_provider_errors(monkeypatch):
    class _Boom:
        def __init__(self, symbol):
            pass

        def history(self, **kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr(price_history.yf, "Ticker", _Boom)
    with pytest.raises(SourceUnavailableError):
        price_history.fetch_live("AAPL", "1M")


def test_endpoint_returns_labeled_live_history(monkeypatch):
    monkeypatch.setattr(price_history.yf, "Ticker", _ticker(_frame([100.0, 101.0])))
    body = TestClient(app).get("/price-history", params={"symbol": "aapl", "range": "1M"}).json()
    assert body["symbol"] == "AAPL"
    assert body["data_mode"] == "live"
    assert body["source"] == "Yahoo Finance (yfinance)"
    assert body["as_of"] == body["points"][-1]["t"]


def test_endpoint_never_substitutes_fixture_prices(monkeypatch):
    monkeypatch.setattr(price_history.yf, "Ticker", _ticker(_frame([])))
    resp = TestClient(app).get("/price-history", params={"symbol": "AAPL"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "provider_unavailable"


def test_endpoint_validates_symbol_and_range():
    client = TestClient(app)
    assert client.get("/price-history", params={"symbol": "NOT A SYMBOL!"}).status_code == 400
    assert client.get("/price-history", params={"symbol": "AAPL", "range": "5Y"}).status_code == 400
