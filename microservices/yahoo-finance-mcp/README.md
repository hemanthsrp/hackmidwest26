# Yahoo Finance MCP

A project-owned MCP server that exposes one historical market-data tool for the
Hack Midwest research demo.

## Tool

`yahoo_finance_market_signal(symbol, mode="sample")` returns a labeled
30-day realized price-change signal:

- `sample` is deterministic and is the default.
- `live` is opt-in and retrieves a 30-day historical signal through `yfinance`.
  An upstream failure returns `provider_unavailable`; it never becomes sample
  output silently.

Every successful response includes `source_name`, `as_of`, `retrieved_at`, and
`data_mode`. It does not make forecasts, produce investment advice, or make the
service an official Yahoo product.

## Run locally

```sh
python -m pip install -e '.[dev]'
python -m pytest
python -m yahoo_finance_mcp.server
```

For a Strands caller:

```python
from yahoo_finance_mcp.strands_mcp import mcp_client

with mcp_client() as yahoo:
    tools = yahoo.list_tools_sync()
```

## Source policy

`yfinance` is an independent open-source library, not a Yahoo-affiliated API.
It describes itself as intended for research and educational use. Review the
applicable Yahoo terms and the project’s source-policy decision before enabling
live mode in a deployed service:

- https://ranaroussi.github.io/yfinance/index.html
- https://guce.yahoo.com/terms?locale=en-US

Do not bypass source terms, access controls, paywalls, or robots restrictions.
Do not add other web sources without a separately reviewed source policy.

## Integration boundary

This server is a standalone data tool. It does not replace the Research API or
Jev decision boundary. Any composition or replacement must have an explicit
contract and tests after source, record, and retention decisions are accepted.
