from datetime import datetime, timezone

from yahoo_finance_mcp.market_data import get_market_signal


def test_sample_signal_is_explicitly_labeled_and_has_provenance() -> None:
    result = get_market_signal("aapl", mode="sample")

    assert result["symbol"] == "AAPL"
    assert result["data_mode"] == "sample"
    assert result["source_name"] == "Yahoo Finance via yfinance"
    assert result["name"] == "30-day price change"
    assert result["unit"] == "percent"
    assert result["as_of"].endswith("Z")
    assert result["retrieved_at"].endswith("Z")


def test_invalid_symbol_returns_a_stable_error_envelope() -> None:
    result = get_market_signal("AAPL!", mode="sample")

    assert result == {
        "error": {
            "code": "invalid_symbol",
            "message": "symbol must contain 1 to 5 uppercase letters",
            "retryable": False,
        }
    }


def test_live_failure_is_explicit_and_never_falls_back_to_sample(monkeypatch) -> None:
    def unavailable(_: str, start_date: str | None, end_date: str | None) -> tuple[float, float, datetime]:
        raise RuntimeError("upstream unavailable")

    monkeypatch.setattr("yahoo_finance_mcp.market_data._fetch_live_prices", unavailable)

    result = get_market_signal("AAPL", mode="live")

    assert result == {
        "error": {
            "code": "provider_unavailable",
            "message": "Yahoo Finance data is unavailable; no market signal was generated.",
            "retryable": True,
        }
    }


def test_live_time_range_is_reported_and_passed_to_the_data_provider(monkeypatch) -> None:
    observed: dict[str, str | None] = {}

    def prices(symbol: str, start_date: str | None, end_date: str | None) -> tuple[float, float, datetime]:
        observed.update({"symbol": symbol, "start_date": start_date, "end_date": end_date})
        return 100.0, 110.0, datetime(2025, 2, 1, tzinfo=timezone.utc)

    monkeypatch.setattr("yahoo_finance_mcp.market_data._fetch_live_prices", prices)

    result = get_market_signal(
        "AAPL",
        mode="live",
        start_date="2025-01-01",
        end_date="2025-02-01",
    )

    assert observed == {"symbol": "AAPL", "start_date": "2025-01-01", "end_date": "2025-02-01"}
    assert result["value"] == 10.0
    assert result["window"] == "2025-01-01..2025-02-01"
    assert result["as_of"] == "2025-02-01T00:00:00Z"


def test_reversed_time_range_is_rejected_before_fetching() -> None:
    result = get_market_signal("AAPL", mode="live", start_date="2025-02-01", end_date="2025-01-01")

    assert result == {
        "error": {
            "code": "invalid_date_range",
            "message": "start_date must be earlier than end_date",
            "retryable": False,
        }
    }
