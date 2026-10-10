"""Strands MCP client helper for the project-owned Yahoo Finance server."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import Any

from mcp.client.stdio import StdioServerParameters, stdio_client


def server_parameters(env: Mapping[str, str] | None = None) -> StdioServerParameters:
    """Start the local Yahoo Finance MCP server over stdio."""
    passed = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT") if name in os.environ}
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "yahoo_finance_mcp.server"],
        env={**passed, **(env or {})},
    )


def mcp_client(**kwargs: Any):
    """Return a Strands MCPClient context manager for the Yahoo Finance tool."""
    from strands.tools.mcp import MCPClient

    params = server_parameters()
    return MCPClient(lambda: stdio_client(params), **kwargs)
