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
    def unavailable(_: str) -> tuple[float, float, datetime]:
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
