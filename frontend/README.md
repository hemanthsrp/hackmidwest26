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

Set Resend credentials and `EMAIL_FROM` to a verified sender. Registration is
disabled until `ALLOW_REGISTRATION=true`. Email/password accounts require email
verification. Configure the three OAuth applications and their secrets to enable
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
- Robinhood linking currently returns `503` pending platform approval. The
  adapter's tested read-tool allowlist and user-bound encrypted grant helpers
  exist; a production OAuth/MCP connection has **not** been implemented or verified.
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
requires Robinhood approval and an implemented approved authorization/refresh
flow, live OAuth/email/PostgreSQL checks, reliable jobs and operational monitoring,
source-rights review, backup restoration, and owner-approved privacy/terms text.
No cloud resources are provisioned by this change. `compose.frontend.yml` is a
local development topology, not a public deployment with TLS or backups.
