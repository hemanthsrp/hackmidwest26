from yahoo_finance_mcp.server import yahoo_finance_market_signal


def test_mcp_tool_returns_the_fixture_contract_by_default() -> None:
    result = yahoo_finance_market_signal("aapl")

    assert result["symbol"] == "AAPL"
    assert result["data_mode"] == "sample"
    assert result["source_name"] == "Yahoo Finance via yfinance"


def test_mcp_tool_exposes_time_range_filters() -> None:
    result = yahoo_finance_market_signal(
        "AAPL",
        mode="sample",
        start_date="2025-01-01",
        end_date="2025-02-01",
    )

    assert result["error"]["code"] == "unsupported_sample_time_range"
