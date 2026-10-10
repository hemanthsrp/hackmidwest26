# Research API

A fixture-first FastAPI skeleton for the Hack Midwest demo. It returns a **current research snapshot**, not a 14-day or price prediction. The endpoint contains no provider credentials and never converts a failed live request into fixture output.

## Routes

- `GET /health` — local readiness response.
- `POST /v0/research-assessments` — accepts `{ "symbol": "ACME", "mode": "sample" | "live" | "failure" }`.

### Mode behavior

- `sample`: returns deterministic, visibly labeled fixture evidence/signals and a research-snapshot assessment.
- `live`: returns `503 provider_unavailable` until a permitted live adapter has been configured. It does **not** fall back to fixtures.
- `failure`: deterministic `503 simulated_provider_failure` for frontend/demo failure-state testing.

## Local checks

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m uvicorn research_api.app:app --app-dir src --port 8000
```

## Scheduler hook

`research_api.scheduler.run_scheduler` runs an injected refresh callback at a validated cadence. Set `RESEARCH_REFRESH_INTERVAL_SECONDS` to an integer from `900` (15 minutes) through `3600` (60 minutes); it defaults to 900. A managed worker can call it with no `max_cycles`; tests/smoke checks may pass a finite `max_cycles`.

The scheduler hook has no live provider implementation yet. Adding one requires Cai's source/rights confirmation and a reviewed contract decision.
