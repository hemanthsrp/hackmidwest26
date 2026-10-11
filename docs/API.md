# API reference

Every HTTP route and MCP tool in the repo, as of `endpoint-cleanup`. This is a **reference for what exists**, not a frozen contract: the v0 contract is still a proposal in [api-contract-v0.md](api-contract-v0.md) (Gate 0). Service READMEs hold the detail; this page is the index.

Add new endpoints to this page in the same PR that adds them (see "Adding an endpoint").

## Services and ports

| Service | Protocol | Default port | Start |
|---|---|---|---|
| [research-api](../microservices/research-api/README.md) | HTTP | 8000 | `python -m uvicorn research_api.app:app --app-dir src --port 8000` |
| [scraper-analysis](../microservices/scraper-analysis/INTEGRATION.md) | HTTP | 8001 | `uvicorn scraper_analysis.api:app --port 8001 --app-dir src` |
| [volatility-surface-builder](../microservices/volatility-surface-builder/README.md) | HTTP | 8002 | `uvicorn vol_surface_builder.api:app --port 8002` |
| [yahoo-finance-mcp](../microservices/yahoo-finance-mcp/README.md) | MCP over stdio | n/a | see its README |
| [jev-tool](../microservices/jev-tool/README.md) | MCP over stdio, Python import | n/a | see its README |
| [agentic-search](../microservices/agentic-search/README.md) | Python library (Exa) | n/a | not an HTTP service |

The frontend talks to **research-api only**. The other services are backend dependencies.

## Conventions

- **Errors** use one envelope: `{"error": {"code", "message", "retryable"}, "request_id"}`. Codes seen: `invalid_symbol` (400), `provider_unavailable` (503), `stale_data` (409), `internal_error` (500), `simulated_provider_failure` (503). scraper-analysis uses `briefing_unavailable` (503) for `/briefing`, and plain FastAPI `{"detail"}` for its 400s.
- **Symbols** are 1 to 5 letters, uppercased by the server. Anything else is `400 invalid_symbol`.
- **Data modes**: every record and response carries `data_mode` of `live`, `cached` or `sample`. Sample data is never presented as live, and a failed live request never falls back to fixtures (except where scraper-analysis documents `fallback=true`).
- **Timestamps** are ISO 8601 UTC.
- **CORS**: research-api allows `http://localhost:3000` and `http://127.0.0.1:3000` by default (GET, POST, OPTIONS; no credentials). Set `CORS_ALLOW_ORIGINS` (comma-separated) for a deployed frontend. `*` is ignored. The other services have no CORS and are not meant to be called from a browser.
- **No credentials** reach a response or the browser. Provider keys live in the backend process environment only.

---

## research-api

### `GET /health`
`{"status": "ok", "service": "research-api"}`. Dependency-free readiness only.

### `POST /v0/research-assessments`
The stock-analysis endpoint. Given a symbol, returns the evidence behind it, the quant signals, and a research assessment with a label and a 0 to 100 score.

**Request**

| Field | Type | Notes |
|---|---|---|
| `symbol` | string | required |
| `mode` | `sample` \| `live` \| `sample_decision` \| `failure` | default `sample` |
| `query` | string, max 2000 | optional user question; used by `live` and `sample_decision`. It can change the explanation and `answer`, never the label or score |
| `preferences.horizon` | `7d` \| `30d` \| `90d` | default `30d` |
| `preferences.risk_profile` | `conservative` \| `balanced` \| `growth` | default `balanced` |

Unknown fields are rejected (422).

**Modes**

| Mode | What it does |
|---|---|
| `sample` | Fixed labeled snapshot. No score, ignores `query` and `preferences`. |
| `sample_decision` | Runs the decision maker over its packaged fixture. Offline; use it to build the frontend against the real response shape. |
| `live` | Runs the decision maker over the evidence **already stored** by scraper-analysis. Needs `DATABASE_URL`; otherwise `503 provider_unavailable`. It does not trigger ingestion, so a symbol with no stored evidence returns `insufficient_data` or an error. Takes roughly 20 to 30 seconds. |
| `failure` | Deterministic `503` for building the frontend error state. |

**Response (200, decision-maker modes)**

| Field | Meaning |
|---|---|
| `request_id`, `symbol`, `query`, `data_mode` | identity and overall data mode |
| `freshness` | `as_of`, `retrieved_at`, `status` (`fresh` \| `stale` \| `unknown`), `stale_after_seconds` |
| `evidence[]` | **the sources list**: `id`, `title`, `summary`, `source_name`, `source_type`, `source_url`, `published_at`, `observed_at`, `retrieved_at`, `sentiment`, `credibility`, `entities`, `details` (Jev judgment and grade when enabled), `data_mode` |
| `signals[]` | quant signals: `id`, `name`, `value`, `unit`, `window`, `as_of`, `source`, `data_mode` |
| `assessment.label` | `buy` \| `hold` \| `sell` \| `insufficient_data` |
| `assessment.score` | integer 0 to 100, or `null` for `insufficient_data` (see below) |
| `assessment.score_sell_at_or_below`, `assessment.score_buy_at_or_above` | scores at which the label flips; they move when the combiner raises its threshold |
| `assessment.horizon`, `assessment.uncertainty` | stated horizon and plain-language limits |
| `assessment.explanation`, `explanation_points[]` | explanation; each point lists the `evidence_ids` it cites |
| `assessment.answer` | reply to `query`, or `null` |
| `assessment.reason_codes` | evidence or signal ids, or system codes such as `insufficient_direction_signals` |
| `assessment.decision_engine` | which engine ran and its status |
| `warnings[]` | `code`, `message`, `retryable` (for example `quant_unavailable`) |
| `meta.decision_trace` | how the label was reached: legs, weights, thresholds, `net_direction`, what was excluded and why |
| `meta.explanation_engine`, `meta.jev_review`, `meta.retrieval` | engine status, Jev review of the explanation, semantic-search status |

**The score.** `score = round(50 + 50 * net_direction)`, limited to 0 to 100, where `net_direction` is the combiner's weighted lean across the usable evidence legs (news 0.4, insider 0.3, price 0.2, congress 0.1). 50 is neutral. It is a position on a hand-set heuristic scale. It is **not** a probability, a forecast, or validated. Label it "heuristic score" in the UI and show it next to the label and `uncertainty`.

**Rendering the sources list.** Group `evidence[]` by `source_type`, link `source_url`, show `published_at`, and show `data_mode` on any item that is not `live`. Citations in `explanation_points[].evidence_ids` and `reason_codes` refer to `evidence[].id` and `signals[].id`.

**Environment** (`live`): `DATABASE_URL`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `CHAT_MODEL`, `EMBEDDING_MODEL`, `JEV_ENABLED`, `TYPESAFE_API_KEY`, `DECISION_STALE_AFTER_SECONDS`, `VOL_SURFACE_URL`. Meanings are in the [research-api README](../microservices/research-api/README.md).

---

## scraper-analysis

Evidence collection and quant signals. Does **not** produce a buy/hold/sell assessment. Full parameter detail and examples are in [INTEGRATION.md](../microservices/scraper-analysis/INTEGRATION.md).

| Route | Purpose |
|---|---|
| `GET /health` | `{"status": "ok"}` |
| `POST /ingest/run?symbol=&live=&fallback=&tag=&judge=` | Collect from all sources, score, dedupe and store. Returns only newly stored items, `signals`, a per-source `sources` report and `warnings`. `live=false` forces fixtures. `fallback=false` (strict) refuses fixtures; use it for anything that persists to the shared DB. `tag=false` skips the Bedrock tagging call. `judge=false` skips the optional Jev judgment. |
| `GET /evidence?symbol=&ranked=&relevant_only=` | Everything stored for the symbol. `status` is `ok` or `insufficient_data`. `ranked` sorts by graded strength and adds `news_tone`; `relevant_only` hides records graded off-topic. |
| `GET /signals?symbol=` | Stored quant signals for the symbol. |
| `GET /divergence?symbol=&as_of=` | Where independent source types disagree (price, insiders, congress, news). Rule-based; live records only. `as_of` must not be in the future (400); a past value is labeled historical. |
| `POST /briefing?symbol=` | Cited research briefing from stored evidence (Strands synthesis agent). Costs a Bedrock call. Never a buy/sell call. `503 briefing_unavailable` when it cannot run. |
| `GET /scheduler/status` | `{"enabled": false}` or the scheduler's per-run status. Keep the scheduler off on the shared DB until the SEC re-key migration is authorized. |

---

## volatility-surface-builder

Option-implied-volatility diagnostics. Not a price forecast.

### `GET /health`
`{"status": "ok", "service": "volatility-surface-builder"}`

### `POST /v0/volatility-surfaces`
Request: `{"symbol", "mode": "sample" | "live", "spot"}` (`spot` defaults to 602.0 and is used by sample mode). Sample mode supports `SPY` only (`400 unsupported_sample_symbol` otherwise). `live` fetches option chains and returns `503 options_provider_unavailable` (retryable) when the provider fails. Research-api calls this when `VOL_SURFACE_URL` is set.

---

## MCP tools

### yahoo-finance-mcp
- `yahoo_finance_market_signal(symbol, mode="sample", start_date, end_date, interval="daily", price_field="close", include_volume, include_realized_volatility, include_corporate_actions)`: labeled realized price-change signal. `live` is opt-in via yfinance and returns an explicit error when unavailable; it never falls back to fixtures.
- `yahoo_finance_company_fundamentals(symbol, mode="live")`: narrow fundamentals, only when source policy has enabled it.

### jev-tool
Read [AGENT_GUIDE.md](../microservices/jev-tool/AGENT_GUIDE.md) before calling. All Jev calls go through this package.
- `jev_check`, `jev_classify`, `jev_score`, `jev_evaluate`: thin wrappers over the Jev primitives.
- `judge_article(symbol, company, title, summary)`: structured judgment of a news item (content type, event type, sensational, usable content).
- `check_explanation(explanation, evidence)`: checks a written explanation sentence by sentence against its evidence and flags advice or promised outcomes.

---

## Python-only boundaries

- **decision-maker**: `DecisionMaker.decide(request, quant)` returns the response shape above. Reached over HTTP only through research-api.
- **agentic-search**: fixture-first Exa search adapter with bounded symbol, date and domain filters. Calls `POST https://api.exa.ai/search` with a server-only `EXA_API_KEY`. Not yet wired into ingestion.

## Known gaps

- No endpoint triggers ingestion on demand; `live` assessments read what scraper-analysis has already stored.
- No streaming or job/poll endpoint. A live assessment blocks for 20 to 30 seconds, so the frontend needs a loading state and a generous timeout.
- No auth and no rate limiting on any service.
- The score meaning and the whole v0 contract still need Gate 0 sign-off.

## Adding an endpoint

1. Add the route and a test (including its error path).
2. Add it to this page: method, path, request fields, response fields, errors, and which modes touch live data.
3. If it changes the frontend-facing contract, update [api-contract-v0.md](api-contract-v0.md) and post a `CONTRACT PROPOSAL` per [AGENTS.md](AGENTS.md).
