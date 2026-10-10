"""Starts the real MCP server over stdio and talks to it through Strands' MCPClient."""

import pytest

pytest.importorskip("strands")

from jev_tool.strands_mcp import mcp_client  # noqa: E402

EXPECTED_TOOLS = {"jev_check", "jev_classify", "jev_score", "jev_evaluate", "judge_article"}


make_client = mcp_client


def test_tools_are_listed_and_callable_when_jev_is_off():
    with make_client({"JEV_ENABLED": "false"}) as client:
        names = {tool.tool_name for tool in client.list_tools_sync()}
        assert names == EXPECTED_TOOLS

        result = client.call_tool_sync(
            "t1",
            "judge_article",
            {"symbol": "ACME", "company": "Acme Corp", "title": "Acme recalls product", "summary": "..."},
        )
        assert result["status"] == "success"
        judgment = result["structuredContent"]
        assert judgment["engine"] == "unavailable"
        assert judgment["direction"] is None
        assert "disabled" in judgment["error"]


@pytest.mark.live
def test_live_call_through_mcp():
    """Run with `pytest -m live`. Needs TYPESAFE_API_KEY and JEV_ENABLED=true (shell or .env)."""
    with make_client() as client:
        result = client.call_tool_sync(
            "t1",
            "jev_check",
            {"text": "I was charged twice. Please fix this ASAP.", "statement": "Is this about billing?"},
        )
        answer = result["structuredContent"]
        assert answer["engine"] == "jev", answer
        assert 0 <= answer["probability"] <= 1
