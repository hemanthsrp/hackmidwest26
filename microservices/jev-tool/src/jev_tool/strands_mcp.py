"""One-line hookup of the Jev MCP server for Strands agents.

    from jev_tool.strands_mcp import mcp_client

    with mcp_client() as jev:
        agent = Agent(tools=jev.list_tools_sync())

Needs `strands-agents` (install jev-tool with the `strands` extra).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import Any

from mcp.client.stdio import StdioServerParameters, stdio_client

# The stdio client starts the server with a near-empty environment, so name what it needs.
PASS_THROUGH = (
    "TYPESAFE_API_KEY",
    "TYPESAFE_BASE_URL",
    "JEV_ENABLED",
    "JEV_MODEL",
    "JEV_TIMEOUT_SECONDS",
    "JEV_MAX_RETRIES",
    "JEV_MAX_CONCURRENCY",
    "JEV_ENV_FILE",
    "PATH",
    "SYSTEMROOT",
)


def server_parameters(env: Mapping[str, str] | None = None) -> StdioServerParameters:
    """Parameters that start `python -m jev_tool.server`. `env` overrides passed-through values."""
    passed = {name: os.environ[name] for name in PASS_THROUGH if name in os.environ}
    return StdioServerParameters(
        command=sys.executable, args=["-m", "jev_tool.server"], env={**passed, **(env or {})}
    )


def mcp_client(env: Mapping[str, str] | None = None, **kwargs: Any):
    """A Strands MCPClient for the Jev tools. Use it as a context manager."""
    from strands.tools.mcp import MCPClient

    params = server_parameters(env)
    return MCPClient(lambda: stdio_client(params), **kwargs)
