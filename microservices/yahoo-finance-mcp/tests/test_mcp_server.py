from yahoo_finance_mcp.strands_mcp import mcp_client, server_parameters


def test_server_parameters_preserve_explicit_fundamentals_disable(monkeypatch) -> None:
    monkeypatch.setenv("YAHOO_FINANCE_FUNDAMENTALS_ENABLED", "false")

    params = server_parameters()

    assert params.env["YAHOO_FINANCE_FUNDAMENTALS_ENABLED"] == "false"


def test_mcp_server_lists_and_runs_the_sample_market_signal_tool() -> None:
    with mcp_client() as client:
        names = {tool.tool_name for tool in client.list_tools_sync()}
        assert names == {"yahoo_finance_market_signal", "yahoo_finance_company_fundamentals"}

        result = client.call_tool_sync(
            "sample-signal",
            "yahoo_finance_market_signal",
            {"symbol": "AAPL"},
        )

    assert result["status"] == "success"
    signal = result["structuredContent"]
    assert signal["symbol"] == "AAPL"
    assert signal["data_mode"] == "sample"
