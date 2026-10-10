# Research API

A fixture-first FastAPI skeleton for the Hack Midwest demo. It returns a **current research snapshot**, not a 14-day or price prediction. The endpoint contains no provider credentials and never converts a failed live request into fixture output.

## Routes

- `GET /health` — local readiness response.
- `POST /v0/research-assessments` — accepts `{ "symbol": "ACME", "mode": "sample" | "live" | "failure" }`.

### Mode behavior

- `sample`: returns deterministic, visibly labeled fixture evidence/signals and a research-snapshot assessment.
- `live`: returns `503 provider_unavailable` until a permitted live adapter has been configured. It does **not** fall back to fixtures.
- `failure`: deterministic `503 simulated_provider_failure` for frontend/demo failure-state testing.

## Akamai inference readiness (server-side plan)

Akamai preflight has verified three server-side operations: model discovery, one bounded chat completion, and one one-sentence embedding request. The configured chat and embedding aliases are available; the embedding result is **1024 dimensions**, matching the pgvector plan. This is preflight evidence, not a claim that the API currently calls Akamai.

When the reviewed live adapter is added, it will read the configured `AKAMAI_INFERENCE_*` environment names only in the backend process (`AKAMAI_INFERENCE_ENABLED`, `AKAMAI_INFERENCE_BASE_URL`, `AKAMAI_INFERENCE_API_KEY`, `AKAMAI_INFERENCE_MODEL`, and `AKAMAI_INFERENCE_TIMEOUT_SECONDS`). No alias, base URL, API key, raw prompt, or provider response is sent to the browser or committed to the repository.

The adapter must retain the existing safety boundary:

- `live` failures remain explicit `503 provider_unavailable` responses; they never switch to fixture output.
- Retry only transient connection, timeout, `429`, and `5xx` failures, with **at most one retry** and the configured request timeout. Fail fast for missing configuration and other `4xx` responses.
- Keep `sample` and `failure` modes deterministic for demo and frontend testing.
- Record only safe operational metadata (request ID when supplied, selected alias, latency, and failure class). Do not log secrets, raw prompts, or raw provider responses.

Implementing this adapter still requires the shared source/schema review; this skeleton intentionally remains fixture-first until that decision is recorded.

## Local checks

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m uvicorn research_api.app:app --app-dir src --port 8000
```

## Scheduler hook

`research_api.scheduler.run_scheduler` runs an injected refresh callback at a validated cadence. Set `RESEARCH_REFRESH_INTERVAL_SECONDS` to an integer from `900` (15 minutes) through `3600` (60 minutes); it defaults to 900. A managed worker can call it with no `max_cycles`; tests/smoke checks may pass a finite `max_cycles`.

The scheduler hook has no live provider implementation yet. Adding one requires Cai's source/rights confirmation and a reviewed contract decision.
