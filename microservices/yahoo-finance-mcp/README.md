# Yahoo Finance MCP

A project-owned MCP server that exposes one historical market-data tool for the
Hack Midwest research demo.

## Tool

`yahoo_finance_market_signal(...)` returns a labeled realized price-change
signal and optional historical metrics:

- `sample` is deterministic and is the default.
- `live` is opt-in and retrieves a 30-day historical signal through `yfinance`.
  An upstream failure returns `provider_unavailable`; it never becomes sample
  output silently.

Every successful response includes `source_name`, `as_of`, `retrieved_at`, and
`data_mode`. It does not make forecasts, produce investment advice, or make the
service an official Yahoo product.

### Query parameters

- `symbol` — required 1–5 letter ticker.
- `mode` — `sample` (default) or opt-in `live`.
- `start_date` and `end_date` — optional ISO `YYYY-MM-DD` range for `live`
  requests; provide both. The start is inclusive and the end is exclusive.
  Omitting both uses the latest 30-day window.
- `interval` — `daily` (default), `weekly`, or `monthly` (`1d`, `1wk`, and
  `1mo` aliases are also accepted).
- `price_field` — `close` (default) or `adjusted_close`.
- `include_volume` — adds average observed volume.
- `include_realized_volatility` — adds annualized historical volatility from
  returns, using the selected interval's standard annualization factor.
- `include_corporate_actions` — adds dividend total and number of split events.

Explicit ranges are limited to 3,650 days. Requests outside that cap return
`range_too_large` before any provider call. The deterministic sample fixture
supports only its daily 30-day close value; it rejects filters rather than
inventing unsupported fixture values.

`yahoo_finance_company_fundamentals(symbol, mode="live")` exposes a narrow
fundamentals record (market cap, valuation multiples, dividend yield, sector,
and industry) only after the project has approved that source use. It is off by
default. A deployed service must set `YAHOO_FINANCE_FUNDAMENTALS_ENABLED=true`
only after that decision; otherwise it returns `source_policy_not_approved`.

Invalid symbols, invalid ranges, unavailable providers, and unsupported sample
filters return explicit error envelopes.

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
