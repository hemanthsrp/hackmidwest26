# Research API

A fixture-first FastAPI skeleton for the Hack Midwest demo. It returns a **current research snapshot**, not a 14-day or price prediction. The endpoint contains no provider credentials and never converts a failed live request into fixture output.

## Routes

- `GET /health` — local readiness response.
- `POST /v0/research-assessments` — accepts `{ "symbol": "ACME", "mode": "sample" | "live" | "failure" }`.

### Mode behavior

- `sample`: returns deterministic, visibly labeled fixture evidence/signals and a research-snapshot assessment.
- `live`: returns `503 provider_unavailable` until a permitted live adapter has been configured. It does **not** fall back to fixtures.
- `failure`: deterministic `503 simulated_provider_failure` for frontend/demo failure-state testing.

## Akamai inference seam (server-side only)

Akamai preflight has verified model discovery, one bounded chat completion, and one one-sentence embedding request. The configured aliases are available; embeddings are **1024 dimensions**, matching the pgvector plan. `research_api.inference` now supplies an injected-transport client seam for those OpenAI-compatible endpoints, but the assessment route does **not** call it yet.

The seam reads only the root `.env.example` contract from the backend process:

```text
OPENAI_BASE_URL
OPENAI_API_KEY
CHAT_MODEL
EMBEDDING_MODEL
```

The browser never receives these values. Configuration errors name only missing variables, not values; the API key is omitted from settings representations and provider errors never include raw response bodies.

The client has a fixed 10-second request bound and at most one retry for connection, timeout, `408`, `429`, and `5xx` failures. It fails fast for missing configuration and other `4xx` responses. Tests inject an in-memory transport, so they make no live network calls.

The safety boundary remains unchanged:

- `live` route failures remain explicit `503 provider_unavailable` responses; they never switch to fixtures.
- `sample` and `failure` remain deterministic demo/test modes.
- Live inference is not wired to sources, embeddings storage, database tables, or the assessment route until Cai/Gate 0 defines the permitted source and evidence contract.

## Jev adapter seams (not wired to the route yet)

`research_api.decision` wraps the shared `microservices/jev-tool` package without importing it; inject a `JevTool` (see `microservices/jev-tool/AGENT_GUIDE.md`).

- `JevDecisionAdapter.judge_article(...)` returns `direction` and `materiality` as before, plus the rest of Jev's judgment (`relevant`, `content_type`, `event_type`, `upcoming_event`, confidences, `model`, `request_id`) when the tool supplies it.
- `JevDecisionAdapter.judge_evidence(evidence, company=...)` uses the judgment `scraper-analysis` stores on a record (`details.jev`) when there is one, and only calls Jev otherwise. `from_stored(...)` reads one without any call.
- `JevExplanationAdapter.review(explanation=..., evidence=...)` reports sentences the evidence does not back and whether the text reads as advice or a promised outcome. Advisory only.
- In every case a disabled or failed Jev comes back as `status: "unavailable"`; nothing is substituted.

## Local checks

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m uvicorn research_api.app:app --app-dir src --port 8000
```

## Scheduler hook

`research_api.scheduler.run_scheduler` runs an injected refresh callback at a validated cadence. Set `RESEARCH_REFRESH_INTERVAL_SECONDS` to an integer from `900` (15 minutes) through `3600` (60 minutes); it defaults to 900. A managed worker can call it with no `max_cycles`; tests/smoke checks may pass a finite `max_cycles`.

The scheduler hook has no live provider implementation yet. Adding one requires Cai's source/rights confirmation and a reviewed contract decision.
