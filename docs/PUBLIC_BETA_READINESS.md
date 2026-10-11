# Public beta readiness

Status checked 2026-10-11. The integrated frontend and research services run
locally in Docker Compose. A strict live AAPL ingest stored SEC EDGAR, Yahoo
Finance, House Clerk, and market-signal records, and the public read-only stock
route returned stored live data. This is not evidence of complete coverage,
predictive performance, production reliability, or a deployed public beta.

## Ready in the repository

- The frontend, same-origin BFF, signed service assertions, and authenticated
  Research API are implemented. Brokerage actions are disabled.
- The default account-free interface labels its portfolio and research examples
  as illustrative. Live records are labeled separately and are not silently
  replaced with fixtures.
- `scripts/setup-local-beta.sh` creates private local-only secrets and refuses
  to overwrite `.env`. `compose.frontend.yml` starts PostgreSQL with pgvector,
  applies frontend and scraper schemas, initializes research storage, and waits
  on health checks. The scraper API is internal to Compose and its scheduler is
  disabled. `scripts/ingest-local-live.sh SYMBOL` performs an explicit strict
  live ingest; it refuses fixture fallback. The local UI can then show stored
  live research through a read-only BFF route with a global request cap.
  Host-published ports bind to loopback.
- `/api/health` provides a non-sensitive readiness check for the frontend and
  verifies database access. The Research API exposes `/health`.
- Public stock pages can be configured to read stored research while
  unauthenticated. The BFF uses a service assertion and a global database-backed
  limit of 600 requests/minute. It does not initiate source ingestion per page
  view. This is a low-volume beta guard, not a capacity guarantee.
- `/privacy` and `/terms` give users a factual beta data notice and research
  use limits. The operator must still review the final copy, publish a
  support/privacy contact, and set the actual host's log-retention period.
- The local Compose profile has an opt-in Robinhood Trading MCP OAuth flow
  using PKCE, encrypted user-bound token storage/refresh, and a server-side
  read-tool allowlist. Portfolio snapshots omit account numbers and transaction
  history. The connector is off by default outside the private local `.env`;
  users must also revoke access in Robinhood settings when disconnecting.

## Required before inviting public users

These items require owner decisions, provider accounts, or infrastructure that
is not available in this workspace:

1. Choose and approve a public host, domain, spend limit, region, and production
   database plan. The repository's working agreement requires Jet's approval
   before a remote deployment, paid provisioning, or publishing.
2. Configure HTTPS and production secrets; test database migrations against a
   disposable production-like database and prove backup restoration.
3. Decide whether signups will be open. If yes, configure a verified email
   sender and test verification, password recovery, OAuth callback/claims,
   session revocation, export, deletion, and unsubscribe end to end. The code
   defaults registration to closed. OAuth identity providers remain optional.
4. Have the operator approve the beta notice and use terms against the final
   jurisdiction and provider setup. Publish a support/privacy contact and the
   actual log-retention period before enabling account creation.
5. Review source terms, attribution, and rate limits for every enabled live
   provider. Establish operational monitoring, alert ownership, retention,
   incident response, and a trusted scheduled job only after those policies
   are accepted.
6. Decide whether the beta is a public read-only demo or an account-backed
   product. The local-only Robinhood MCP authorization/refresh path is
   implemented with a read-tool allowlist, but user consent, token refresh, and
   portfolio responses have not been verified. Keep the connector disabled
   on hosted deployments until Robinhood approves the public platform, and
   complete security/privacy review before account data is accepted. Folio has
   no order execution path.
7. Verify the chosen production data and inference paths. No live inference
   credentials are configured in this workspace. Research assessments remain
   current-evidence heuristics without demonstrated predictive validity.

## Local release-candidate verification

```sh
./scripts/setup-local-beta.sh
docker compose -f compose.frontend.yml up --build -d
./scripts/ingest-local-live.sh AAPL
curl --fail http://localhost:3100/api/health
curl --fail http://localhost:8100/health
```

Then walk through the app in a browser, check a stock detail page, inspect the
visible sample/live label and source timestamps, and verify that unavailable
providers produce an explicit state. Before a public launch, repeat the smoke
check against the actual HTTPS deployment and retain the URL and results.

## Current verification limits

On 2026-10-11, frontend typecheck, 3 frontend tests, production build, and
`npm audit --omit=dev` passed (zero reported vulnerabilities). Python suites
passed: research API 76, scraper-analysis 1,320 (1 skipped), decision-maker
140, Jev tool 41 (1 live test deselected), agentic-search 5, Yahoo Finance MCP
14, and volatility-surface-builder 67. Total: 1,666 passed, with one skipped
and one live test deselected. The Compose images built and the stack started;
the frontend, Research API, and scraper health checks passed. Compose
configuration validation and `git diff --check` passed.

The local frontend and `/api/health` return 200; the Research API and scraper
health endpoints return 200. The AAPL stock page returns 200 and its BFF
response identifies `data_mode=live`, with 12 fresh evidence items and one
signal. The assessment is `insufficient_data`, since sentiment tagging is not
configured. MarketAux is unavailable without `NEWS_API_KEY`; some enabled
sources returned zero records, and a portion of House Clerk PDFs had no text
layer. The app remains a local read-only beta candidate. No public URL, remote
database, production mail delivery, paid resource, production monitoring, or
production provider integration has been verified.
