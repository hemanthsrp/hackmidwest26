"""Starts the real MCP server over stdio and talks to it through Strands' MCPClient."""

import os
import sys

import pytest

pytest.importorskip("strands")

from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402
from strands.tools.mcp import MCPClient  # noqa: E402

EXPECTED_TOOLS = {"jev_check", "jev_classify", "jev_score", "jev_evaluate", "judge_article"}


def make_client(env: dict[str, str]) -> MCPClient:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "jev_tool.server"],
        # The stdio client does not pass the parent environment through, so name what the server needs.
        env={**{k: v for k, v in os.environ.items() if k in {"PATH", "SYSTEMROOT"}}, **env},
    )
    return MCPClient(lambda: stdio_client(params))


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
@pytest.mark.skipif(
    not (os.environ.get("TYPESAFE_API_KEY") and os.environ.get("JEV_ENABLED", "").lower() == "true"),
    reason="needs TYPESAFE_API_KEY and JEV_ENABLED=true",
)
def test_live_call_through_mcp():
    env = {"JEV_ENABLED": "true", "TYPESAFE_API_KEY": os.environ["TYPESAFE_API_KEY"]}
    with make_client(env) as client:
        result = client.call_tool_sync(
            "t1",
            "jev_check",
            {"text": "I was charged twice. Please fix this ASAP.", "statement": "Is this about billing?"},
        )
        answer = result["structuredContent"]
        assert answer["engine"] == "jev", answer
        assert 0 <= answer["probability"] <= 1
