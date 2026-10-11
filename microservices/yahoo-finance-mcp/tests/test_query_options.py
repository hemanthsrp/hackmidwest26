from datetime import datetime, timezone

import pandas as pd

from yahoo_finance_mcp.market_data import get_company_fundamentals, get_market_signal


def test_live_query_supports_price_volume_volatility_and_corporate_actions(monkeypatch) -> None:
    history = pd.DataFrame(
        {
            "Close": [100.0, 110.0, 120.0],
            "Adj Close": [90.0, 110.0, 120.0],
            "Volume": [1_000_000, 2_000_000, 3_000_000],
            "Dividends": [0.0, 0.25, 0.0],
            "Stock Splits": [0.0, 2.0, 0.0],
        },
        index=pd.to_datetime(["2025-01-02", "2025-01-16", "2025-01-31"], utc=True),
    )
    observed: dict[str, object] = {}

    def fetch(symbol: str, start_date: str | None, end_date: str | None, interval: str) -> pd.DataFrame:
        observed.update({"symbol": symbol, "start_date": start_date, "end_date": end_date, "interval": interval})
        return history

    monkeypatch.setattr("yahoo_finance_mcp.market_data._fetch_live_history", fetch)

    result = get_market_signal(
        "aapl",
        mode="live",
        start_date="2025-01-02",
        end_date="2025-02-01",
        interval="daily",
        price_field="adjusted_close",
        include_volume=True,
        include_realized_volatility=True,
        include_corporate_actions=True,
    )

    assert observed == {"symbol": "AAPL", "start_date": "2025-01-02", "end_date": "2025-02-01", "interval": "1d"}
    assert result["price_field"] == "adjusted_close"
    assert result["interval"] == "1d"
    assert result["value"] == 33.3333
    assert result["average_volume"] == 2_000_000
    assert result["realized_volatility_annualized"] is not None
    assert result["dividends_total"] == 0.25
    assert result["stock_split_events"] == 1


def test_default_live_signal_uses_only_the_labeled_30_day_window(monkeypatch) -> None:
    history = pd.DataFrame(
        {"Close": [float(value) for value in range(100, 135)]},
        index=pd.date_range("2025-01-01", periods=35, freq="D", tz="UTC"),
    )
    monkeypatch.setattr("yahoo_finance_mcp.market_data._fetch_live_history", lambda *_: history)

    result = get_market_signal("AAPL", mode="live")

    assert result["window"] == "30d"
    assert result["value"] == 28.8462


def test_date_range_is_capped_before_live_fetch() -> None:
    result = get_market_signal(
        "AAPL",
        mode="live",
        start_date="2010-01-01",
        end_date="2025-01-01",
    )

    assert result == {
        "error": {
            "code": "range_too_large",
            "message": "requested date range exceeds the 3650-day limit",
            "retryable": False,
        }
    }


def test_fundamentals_can_be_explicitly_disabled(monkeypatch) -> None:
    monkeypatch.setenv("YAHOO_FINANCE_FUNDAMENTALS_ENABLED", "false")

    result = get_company_fundamentals("AAPL", mode="live")

    assert result == {
        "error": {
            "code": "source_policy_not_approved",
            "message": "company fundamentals are disabled pending source-policy approval",
            "retryable": False,
        }
    }


def test_fundamentals_are_disabled_by_default_pending_source_policy(monkeypatch) -> None:
    monkeypatch.delenv("YAHOO_FINANCE_FUNDAMENTALS_ENABLED", raising=False)
    monkeypatch.setattr(
        "yahoo_finance_mcp.market_data.yf.Ticker",
        lambda _: (_ for _ in ()).throw(AssertionError("provider must not be called")),
    )

    result = get_company_fundamentals("AAPL")

    assert result == {
        "error": {
            "code": "source_policy_not_approved",
            "message": "company fundamentals are disabled pending source-policy approval",
            "retryable": False,
        }
    }


def test_fundamentals_require_explicit_source_policy_enablement(monkeypatch) -> None:
    monkeypatch.setenv("YAHOO_FINANCE_FUNDAMENTALS_ENABLED", "true")

    class Ticker:
        info = {
            "marketCap": 3_000_000_000_000,
            "trailingPE": 31.2,
            "forwardPE": 28.4,
            "dividendYield": 0.004,
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "unrelated_field": "excluded",
        }

    monkeypatch.setattr("yahoo_finance_mcp.market_data.yf.Ticker", lambda _: Ticker())

    result = get_company_fundamentals("AAPL")

    assert result["data_mode"] == "live"
    assert result["fundamentals"] == {
        "marketCap": 3_000_000_000_000,
        "trailingPE": 31.2,
        "forwardPE": 28.4,
        "dividendYield": 0.004,
        "sector": "Technology",
        "industry": "Consumer Electronics",
    }
