# Hack Midwest 2026

Evidence-backed stock research demo in progress. The repository now contains a fixture-first Research API, a multi-source ingestion service, a shared Jev judgment tool, and an imported option-volatility surface service. The Next.js frontend and end-to-end assessment flow are still pending.

Start with [the project brief](docs/PROJECT_BRIEF.md), [current architecture](docs/ARCHITECTURE.md), [task board](docs/TASKS.md), and [working agreement](docs/AGENTS.md). The original challenge notes remain in [DUMP.md](docs/DUMP.md).

| Component | Current capability |
|---|---|
| [Research API](microservices/research-api/README.md) | Local sample research snapshot; standalone Akamai inference and Jev adapter seams |
| [Scraper analysis](microservices/scraper-analysis/README.md) | Source adapters, fixtures, normalized evidence and market signals |
| [Jev tool](microservices/jev-tool/README.md) | Shared Python/MCP judgments and offline tests |
| [Volatility surface builder](microservices/volatility-surface-builder/README.md) | Imported Black–Scholes/SVI option diagnostics, charts, tests, and a standalone sample/live HTTP endpoint |
| [Yahoo Finance MCP](microservices/yahoo-finance-mcp/README.md) | Project-owned MCP server exposing realized price-change and market-data signals with sample fixtures |
| [Agentic search](microservices/agentic-search/README.md) | Project-owned, fixture-first Exa Search API boundary with bounded queries and domain filters |

The volatility service shows how options price risk. Its grid and skew measurements are not stock-price forecasts or buy/hold/sell recommendations. No frontend or deployed application is claimed here. See each service README for verified local commands.
