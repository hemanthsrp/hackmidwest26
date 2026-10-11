# Folio frontend

Next.js App Router application for Home, Trending, Industries, stock research,
settings, and a persistent research assistant. Light is the default; dark mode
is available from the sidebar and settings.

## Run the demo

```sh
cd frontend
npm ci
npm run dev
```

Open the URL printed by Next.js. No credentials or database are required for the
public demo. Every price, holding, article, chart, assessment, and assistant
response in the demo is explicitly illustrative. Demo preferences last for the
current visit; only the theme persists locally.

For a full-stack local run with PostgreSQL and account/research schemas, use
the root [Compose setup](../README.md#run-the-local-full-stack-app). Its
`/api/health` check verifies required service configuration and database access.

## Run the demo with the Research API

The stock detail page's sample research request goes through the Next.js BFF to
the Python Research API. Start the API in one terminal:

```sh
cd microservices/research-api
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m uvicorn research_api.app:app --app-dir src --host 127.0.0.1 --port 8000
```

In `frontend/.env.local`, set `RESEARCH_API_URL=http://127.0.0.1:8000`, then
start the frontend in another terminal with `npm run dev`. Open a stock detail
page such as `/stocks/AAPL`; its sample assessment, evidence and signal come
from `POST /v0/research-assessments` through the same-origin BFF. If the API is
down, the page shows an explicit service-unavailable state instead of replacing
it with another local fixture. The wider account-backed `/v1` features still
need PostgreSQL and server configuration described below.

## Enable live sources for local stock research

The local development path can fetch live EDGAR filings, official RSS news and
market signals when you open or refresh a stock detail page. Start the
`scraper-analysis` service on port 8002 with its `.env` configured, including a
valid contact in `SEC_EDGAR_USER_AGENT`. Leave `ENABLE_SCHEDULER=false`; the
frontend requests a strict one-shot ingest with fixtures disabled. The Yahoo
Finance adapter and official RSS feeds need no API key. `NEWS_API_KEY` and
AWS/Bedrock settings are optional; without them those enrichment sources are
reported unavailable or tagging is skipped.

Set the same random `SERVICE_ASSERTION_SECRET` (at least 32 characters) and
`SCRAPER_API_URL=http://127.0.0.1:8002` in `frontend/.env.local` and
`microservices/research-api/.env`. Set `DEMO_LIVE_RESEARCH=true` in the frontend
environment and restart both the Research API and Next.js. This local-only
switch is ignored when Next.js runs in production. Stock detail pages show live
records from reachable sources; unavailable sources stay absent and fixtures
are not substituted. The account dashboard and portfolio remain illustrative
until account storage and sign-in providers are configured.

## Configure accounts and research

Copy `.env.example` to `.env.local` and populate server-only configuration.
Generate `AUTH_SECRET` and `SERVICE_ASSERTION_SECRET` independently with
`openssl rand -base64 32`; use the same service assertion secret in FastAPI.
Set `AUTH_URL` to the exact externally visible origin.

Create a PostgreSQL database and apply the generated migrations:

```sh
# Export DATABASE_URL in your shell first. Drizzle does not load .env.local.
npm run db:migrate
```

In the research API environment, set `RESEARCH_DATABASE_URL` and run:

```sh
python -m research_api.storage
python -m uvicorn research_api.app:app --port 8000
```

Configure `SCRAPER_API_URL` for the existing scraper service. The research API
only uses fresh live/cached records; it excludes sample records even if the
scraper falls back internally. `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `CHAT_MODEL`,
and `EMBEDDING_MODEL` configure the existing Akamai inference client.

Set Resend credentials and `EMAIL_FROM` to a verified sender. Hosted registration
is disabled until `ALLOW_REGISTRATION=true`. Email/password accounts require
email verification. The root Compose setup has a separate loopback-only local
account option so you can create a Folio account without email delivery.
Configure the three OAuth applications and their secrets to enable
Google, Apple, and Microsoft buttons. Callback paths are
`/api/auth/callback/google`, `/api/auth/callback/apple`, and
`/api/auth/callback/microsoft-entra-id`.

Auth.js Credentials uses encrypted JWT cookies. A database session registry is
checked on each session read and supports immediate revocation. Credentials use
scrypt N=131072, r=8, p=1 with random salts. OAuth account linking is not enabled
by matching email addresses; Auth.js's default account-linking protection stays on.

## Service and privacy boundaries

- Browser requests use the same-origin Next.js BFF. FastAPI accepts a signed,
  audience-bound service assertion with a 60-second lifetime.
- Chat messages exist in browser memory and the current inference request only.
  The database stores only allowlisted, consented research preferences, which
  users can delete. Disabling memory clears stored memories.
- No raw chats, portfolio account numbers, or broker grants are sent to Jev.
- The local Compose profile supports Robinhood's official Trading MCP OAuth
  flow. It stores a user-bound encrypted grant server-side and restricts Folio
  to account, portfolio, and equity-position read tools. Folio does not expose
  MCP tools to the model or call order/mutation tools. Robinhood consent covers
  account details, balances, positions, and transaction history; Folio does
  not persist account numbers or transaction history. OAuth remains unverified
  until the user completes Robinhood's consent flow. Keep the integration off
  on hosted deployments until Robinhood approves that platform.
- Live research currently uses a versioned evidence-direction heuristic. It does
  not claim predictive performance. Feed coverage is the bounded universe in
  `research_api.v1.UNIVERSE`.
- Notifications are generated when the home feed observes an assessment change.
  A trusted scheduler can POST `/api/jobs/digest` with `DIGEST_JOB_SECRET` to
  refresh opted-in users and deliver pending email. Configure it at a daily cadence.
  The endpoint uses Resend idempotency keys; no schedule is provisioned automatically.
- Research data and credentials must not be exposed via shared/public caches.

## Checks

```sh
npm run typecheck
npm test
npm run build
npm audit --omit=dev
```

Backend checks: `python -m pytest microservices/research-api/tests -q` from the
repository root with the research API's dev dependencies installed.

## Delivery limitations

The desktop UI and local fixture flow are runnable. Public-beta readiness still
requires hosted-platform Robinhood approval, a real OAuth/MCP consent and
portfolio-refresh check, email/PostgreSQL checks, reliable jobs and operational monitoring,
source-rights review, backup restoration, and owner-approved privacy/terms text.
No cloud resources are provisioned by this change. `compose.frontend.yml` is a
loopback-only local topology, not a public deployment with TLS or backups. See
the [public beta readiness record](../docs/PUBLIC_BETA_READINESS.md) for the
release gate and current verification limits.
