"""MCP server for a single Yahoo Finance historical market signal."""

from __future__ import annotations

import logging
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from .market_data import get_market_signal

mcp = MCPServer(
    "yahoo-finance-mcp",
    instructions=(
        "Provides one labeled historical market signal from Yahoo Finance via yfinance. "
        "Use sample mode by default. Live mode is opt-in and may return provider_unavailable; "
        "do not treat it as a forecast, investment advice, or an official Yahoo service."
    ),
)


@mcp.tool()
def yahoo_finance_market_signal(symbol: str, mode: str = "sample") -> dict[str, Any]:
    """Return a labeled 30-day realized price-change signal for one stock symbol.

    ``sample`` is deterministic fixture data. ``live`` is an opt-in yfinance
    request and returns an explicit error when unavailable; it never falls back
    to fixture data.
    """
    return get_market_signal(symbol, mode)


def main() -> None:
    """Run the MCP protocol over stdio; keep logs off stdout."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
