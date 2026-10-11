# Microservices

| Service | State |
|---|---|
| [Research API](research-api/README.md) | Serves `POST /v0/research-assessments`; `live` mode calls the decision maker when `DATABASE_URL` is set |
| [Decision maker](decision-maker/README.md) | Implemented (Jet, A3): `combiner-v1` rule, Strands explanation, Jev review. Run live for AAPL; not yet reviewed by the other lanes |
| [Scraper analysis](scraper-analysis/README.md) | Evidence collection, signals, divergence, briefing, optional scheduler and Jev judgment. See its [integration guide](scraper-analysis/INTEGRATION.md) |
| [Jev tool](jev-tool/README.md) | Shared Jev/MCP package; all Jev calls go through it |
| [Volatility surface builder](volatility-surface-builder/README.md) | Option-IV diagnostics; reachable from the decision maker through `VOL_SURFACE_URL`, no live option chain run through it yet |
| [Yahoo Finance MCP](yahoo-finance-mcp/README.md) | Fixture-first market-data MCP server; not wired into the pipeline |
| [Agentic search](agentic-search/README.md) | Fixture-first Exa search boundary; not wired into the pipeline |

No frontend exists yet, so no service is wired into an end-to-end user flow.
