# Folio

Folio is an evidence-backed stock research application. It brings attributed
news, dated market indicators, and a transparent current-evidence assessment
into one interface. It is a research aid: assessments are heuristics, not
validated forecasts or personalized investment advice. Folio does not execute
trades. The local, opt-in Robinhood connection uses Robinhood's official MCP
OAuth flow and exposes read-only portfolio data inside Folio. Hosted use stays
disabled unless separately configured and approved.

## Run the local full-stack app

The browser app is in `frontend/`; the authenticated research API is in
`microservices/research-api/`; source collection is in
`microservices/scraper-analysis/`. The easiest isolated full-stack start uses
Docker Compose and a local PostgreSQL database:

```sh
./scripts/setup-local-beta.sh
docker compose -f compose.frontend.yml up --build -d
```

The setup script creates an ignored, mode-600 root `.env` with fresh local-only
secrets and refuses to overwrite an existing file. Open `http://localhost:3100`.
The Compose stack runs PostgreSQL with pgvector, applies the frontend and source
schemas, starts the internal scraper and Research API, then starts the
frontend. Set `SEC_EDGAR_USER_AGENT` in the ignored
`microservices/scraper-analysis/.env` to identify the SEC requests. Ingest one
symbol manually with `./scripts/ingest-local-live.sh AAPL`; the script refuses
fixture fallback. The public stock page then reads stored records without
triggering upstream requests. The scheduler stays off. Host ports bind to
loopback, so this is a local testing stack, not a public deployment. The local
setup permits account creation without email verification only when the app's
`AUTH_URL` is loopback; hosted registrations still require real email
verification or configured OAuth providers.

The setup script creates a private broker-token encryption key and enables the
Robinhood connector for localhost. After signing in, open Settings → Connected
accounts → Robinhood and complete consent on Robinhood. To create your local
Folio login, open `http://localhost:3100/login?flow=register` and choose an
email and password; that credential stays in the local Folio database. Its
consent covers
account information broadly, but Folio calls only account, portfolio, and
equity-position read tools; order and mutation tools are blocked. Robinhood
requires a dedicated MCP account for external agents. Keep this connector
disabled on hosted deployments until Robinhood approves that platform.

Stop the services with:

```sh
docker compose -f compose.frontend.yml down
```

Add `-v` only when you intentionally want to delete the local PostgreSQL data.
The default host ports are 3100 (frontend), 8100 (Research API), and 5433
(PostgreSQL), so they can run alongside the separate local dev processes. Set
`HOST_PORT`, `RESEARCH_API_PORT`, or `DATABASE_PORT` in the ignored root `.env`
to change them.

## Live-source local preview

See [frontend/README.md](frontend/README.md#enable-live-sources-for-local-stock-research)
for the optional strict live-source path. It uses live SEC filings, public RSS,
and Yahoo Finance market data where reachable; unavailable sources remain
absent, and the request refuses fixture substitution. This path is local-only
and does not provide complete news coverage or a validated assessment.

## Project map

- [Frontend and account setup](frontend/README.md)
- [Research API](microservices/research-api/README.md)
- [Scraper and source boundaries](microservices/scraper-analysis/README.md)
- [Architecture](docs/ARCHITECTURE.md)
- [API documentation](docs/API.md)
- [Beta readiness and release blockers](docs/PUBLIC_BETA_READINESS.md)
- [Project decisions](docs/DECISIONS.md)

## Checks

Frontend: `cd frontend && npm run typecheck && npm test && npm run build`.
Research API: install its `dev` extra and run `python -m pytest` from its
directory. The local Compose setup additionally has frontend and API health
checks; remote deployment and external-provider behavior require separate
verification.
