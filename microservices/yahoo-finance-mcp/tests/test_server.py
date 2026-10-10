from yahoo_finance_mcp.server import yahoo_finance_market_signal


def test_mcp_tool_returns_the_fixture_contract_by_default() -> None:
    result = yahoo_finance_market_signal("aapl")

    assert result["symbol"] == "AAPL"
    assert result["data_mode"] == "sample"
    assert result["source_name"] == "Yahoo Finance via yfinance"
