# scraper-analysis

FastAPI service that collects attributed evidence and market signals. It does
not calculate the final buy/hold/sell assessment; that belongs to the Research
API and decision-maker. Every source reports whether it returned live,
cached, sample, or unavailable data. Live requests can refuse fixture fallback.

## Run locally

```sh
cd microservices/scraper-analysis
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
# Set SEC_EDGAR_USER_AGENT to a descriptive app name and contact address.
.venv/bin/python -m uvicorn scraper_analysis.api:app --app-dir src --port 8001
```

Without `DATABASE_URL`, records are held in memory for the process. For
persistent PostgreSQL storage, initialize the idempotent schema with
`.venv/bin/python -m scraper_analysis.storage.bootstrap` before serving. The
schema enables pgvector. A non-local database must set
`sslmode=require`; the explicit `ALLOW_INSECURE_LOCAL_DATABASE=true` exception
is only for the root Compose topology's private `database` container. It does
not permit other remote hosts.

For the complete local app, use the root [Compose setup](../../README.md#run-the-local-full-stack-app).
The scraper is internal to the Compose network; its port is not published to
the host. Its scheduler and social-source adapters remain disabled there.

## Endpoints

| Endpoint | Behavior |
|---|---|
| `GET /health` | Liveness probe. |
| `POST /ingest/run?symbol=AAPL&live=true&fallback=false&tag=false&judge=false` | Fetches sources and persists newly collected evidence/signals. `fallback=false` refuses fixtures. `tag=false` skips Bedrock tagging; `judge=false` skips optional Jev judgments. |
| `GET /evidence?symbol=AAPL` | Stored attributed evidence. |
| `GET /signals?symbol=AAPL` | Stored market signals. |
| `GET /divergence?symbol=AAPL` | Rule-based source divergence with window and exclusions. Not a price forecast. |
| `POST /briefing?symbol=AAPL` | Optional source-cited briefing; requires configured inference. |
| `GET /scheduler/status` | Scheduler state. Background ingestion is off by default. |

Supported evidence adapters include SEC EDGAR, public RSS feeds, optional
MarketAux, Senate eFD and House Clerk PTR disclosures. Market signals include
the 30-day realized price change; selected commodity symbols have separate
indicators. House coverage is partial because some PTR PDFs are scanned images
without a text layer. Each run returns source status and warnings. Re-ingesting
may return zero *new* evidence even though prior records remain stored.

## Data and safety limits

- Public-source data is not guaranteed complete, current, or suitable for a
  financial decision. Timestamps and source links are part of the record.
- Reddit is disabled by default and may be blocked; X is disabled. Paywalled
  publishers are not scraped. Optional APIs and model tagging require separate
  credentials.
- Raw chat history is not stored. Optional tagging and Jev judgment send
  selected evidence to those configured providers; confirm source terms before
  enabling those features.
- The service's ingest route has no user auth by itself. Keep it on a trusted
  private network. The local Compose network does not publish it to the host;
  production deployment needs an authenticated ingestion boundary.
- Never describe credibility/direction scores or a downstream assessment as a
  validated prediction. No backtest or predictive performance is claimed.

## Checks

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
```

The project integration notes are in [`INTEGRATION.md`](INTEGRATION.md).
