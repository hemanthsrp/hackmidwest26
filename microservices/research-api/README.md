# Research API

A fixture-first FastAPI skeleton for the Hack Midwest demo. It returns a **current research snapshot**, not a 14-day or price prediction. The endpoint contains no provider credentials and never converts a failed live request into fixture output.

## Routes

- `GET /health` — local readiness response.
- `POST /v0/research-assessments` — accepts `{ "symbol": "ACME", "mode": "sample" | "live" | "failure" | "sample_decision", "query": "optional question", "preferences": { "horizon": "7d" | "30d" | "90d", "risk_profile": "conservative" | "balanced" | "growth" } }`. Unknown fields are rejected.

### Mode behavior

- `sample`: returns deterministic, visibly labeled fixture evidence/signals and a research-snapshot assessment. Unchanged; it ignores `query` and `preferences`.
- `live`: runs the decision maker (below) over the evidence store when `DATABASE_URL` is set and `microservices/decision-maker` is installed. Otherwise `503 provider_unavailable`, as before. It does **not** fall back to fixtures.
- `sample_decision`: runs the decision maker over its packaged fixture. Offline, no credentials, every record labeled `sample`. Use it to build against the live response shape.
- `failure`: deterministic `503 simulated_provider_failure` for frontend/demo failure-state testing.

## Decision maker (`live` and `sample_decision`)

`research_api.assessment` builds [`microservices/decision-maker`](../decision-maker/README.md) from the process environment and calls it. The response shape, the rule that picks the label, and the warning codes are documented there.

```bash
python -m pip install -e "../decision-maker[pg,agent]"
python -m pip install -e ../jev-tool        # optional: Jev review and judging
```

| Variable | Effect when set |
|---|---|
| `DATABASE_URL` | Required for `live`. The evidence store `scraper-analysis` writes; read-only here. Non-local hosts need `sslmode=require`. |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `CHAT_MODEL`, `EMBEDDING_MODEL` | All four enable the Strands explanation agent and semantic search for the question. Without them the explanation is a labeled template and the question does not narrow the evidence. |
| `JEV_ENABLED`, `TYPESAFE_API_KEY` | Read by `jev-tool` (its own `.env` works). Enables review of the model's text and judging of news stored without a judgment. |
| `DECISION_AGENT_TOOLS` | `false` gives the model its data in the prompt instead of tools. Default `true`; a failed tools attempt falls back to this automatically. |
| `DECISION_STALE_AFTER_SECONDS` | Freshness window, default `86400`. Older evidence returns `409 stale_data`. |

This service does not load a `.env` file itself; export the variables or start uvicorn with `--env-file`.

Errors use the contract envelope: `400 invalid_symbol`, `503 provider_unavailable`, `409 stale_data`, and `500 internal_error` for anything unexpected (the cause is logged by type only).

### Plugging in the math

The quant math lives in this service and reaches the decision maker through one hook:

```python
from research_api import assessment

assessment.set_quant_provider(my_quant)   # (symbol, horizon) -> decision_maker.QuantInput | None
```

The expected fields, with an example built from `vol-surface-builder`'s own functions, are in the decision-maker README under "Handing over the math". Until a provider is registered, every assessment carries a `quant_unavailable` warning and is decided from evidence and the price signal alone. A provider that raises is reported as `quant_provider_failed` and does not block the response.

Not yet run against the real store, Akamai inference or TypeSafe from this service; only the offline tests have run.

## Akamai inference seam (server-side only)

Akamai preflight has verified model discovery, one bounded chat completion, and one one-sentence embedding request. The configured aliases are available; embeddings are **1024 dimensions**, matching the pgvector plan. `research_api.inference` supplies an injected-transport client seam for those OpenAI-compatible endpoints.

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

- `live` route failures remain explicit error responses; they never switch to fixtures.
- `sample`, `sample_decision` and `failure` remain deterministic demo/test modes.
- The `live` route now reaches inference through the decision maker, for the explanation and for embedding the user's question. `research_api.assessment.httpx_transport` is the real transport for the client above.

## Jev adapter seams

`research_api.decision` wraps the shared `microservices/jev-tool` package without importing it; inject a `JevTool` (see `microservices/jev-tool/AGENT_GUIDE.md`).

- `JevDecisionAdapter.judge_article(...)` returns `direction` and `materiality` as before, plus the rest of Jev's judgment (`relevant`, `content_type`, `event_type`, `upcoming_event`, confidences, `model`, `request_id`) when the tool supplies it.
- `JevDecisionAdapter.judge_evidence(evidence, company=...)` uses the judgment `scraper-analysis` stores on a record (`details.jev`) when there is one, and only calls Jev otherwise. `from_stored(...)` reads one without any call.
- `JevExplanationAdapter.review(explanation=..., evidence=...)` reports sentences the evidence does not back and whether the text reads as advice or a promised outcome. Advisory only.
- In every case a disabled or failed Jev comes back as `status: "unavailable"`; nothing is substituted.
- The `live` route injects both adapters into the decision maker when Jev is enabled.

## Local checks

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m uvicorn research_api.app:app --app-dir src --port 8000
```

## Scheduler hook

`research_api.scheduler.run_scheduler` runs an injected refresh callback at a validated cadence. Set `RESEARCH_REFRESH_INTERVAL_SECONDS` to an integer from `900` (15 minutes) through `3600` (60 minutes); it defaults to 900. A managed worker can call it with no `max_cycles`; tests/smoke checks may pass a finite `max_cycles`.

The scheduler hook has no live provider implementation yet. Adding one requires Cai's source/rights confirmation and a reviewed contract decision.
