# Proposed v0 research-assessment API contract

> Repository-status update (2026-10-10): the standalone option-volatility endpoint is documented in [the volatility service README](../microservices/volatility-surface-builder/README.md). It does not alter or freeze the research-assessment contract below.

> **Status: A1 proposal for Gate 0 review, not an implemented or frozen endpoint.**
>
> This contract exists so the frontend, evidence/quant, platform, and orchestration lanes can integrate against one small, deterministic shape. It does not authorize A2 implementation. All field values below are examples using fixtures, not live market data or investment advice.

## Scope and route

**Proposed route:** `POST /v0/research-assessments`

The endpoint accepts one supported stock symbol and optional non-sensitive presentation preferences. It returns source-backed evidence, dated signals, an assessment, freshness metadata, and warnings. It never accepts brokerage credentials, account data, or trading instructions.

### Request

```json
{
  "symbol": "ACME",
  "preferences": {
    "horizon": "30d",
    "risk_profile": "balanced"
  }
}
```

| Field | Type | Required | Proposed rule |
|---|---|---:|---|
| `symbol` | string | yes | Trim, uppercase, validate as `^[A-Z]{1,5}$`, then check against the Gate-0 supported-symbol set. |
| `preferences` | object | no | Demo-only, non-sensitive display/context input. No account identifiers, holdings, credentials, or trade intent. |
| `preferences.horizon` | string | no | Proposed enum: `7d`, `30d`, `90d`; final horizon needs Gate-0 approval. |
| `preferences.risk_profile` | string | no | Proposed enum: `conservative`, `balanced`, `growth`; influences explanation/presentation only until suitability methodology is approved. |

Unknown request fields are rejected until the team explicitly chooses forward-compatible behavior.

## Success response

**Proposed status:** `200 OK`

```json
{
  "request_id": "fixture-acme-20261010-001",
  "symbol": "ACME",
  "data_mode": "sample",
  "freshness": {
    "as_of": "2026-10-10T18:00:00Z",
    "retrieved_at": "2026-10-10T18:05:00Z",
    "status": "fresh",
    "stale_after_seconds": 86400
  },
  "evidence": [
    {
      "id": "sample-acme-news-001",
      "symbol": "ACME",
      "title": "Sample ACME earnings update",
      "summary": "Fixture-only summary for the demo.",
      "source_name": "Fixture News",
      "source_url": "https://example.invalid/fixtures/acme-news-001",
      "published_at": "2026-10-10T16:00:00Z",
      "observed_at": "2026-10-10T16:02:00Z",
      "retrieved_at": "2026-10-10T18:05:00Z",
      "data_mode": "sample"
    }
  ],
  "signals": [
    {
      "id": "sample-acme-signal-001",
      "symbol": "ACME",
      "name": "30-day price change",
      "value": 2.4,
      "unit": "percent",
      "window": "30d",
      "as_of": "2026-10-10T16:00:00Z",
      "source": "Fixture Market Data",
      "data_mode": "sample"
    }
  ],
  "assessment": {
    "label": "hold",
    "horizon": "30d",
    "reason_codes": ["sample-acme-news-001", "sample-acme-signal-001"],
    "explanation": "Fixture assessment: evidence and the dated signal are mixed.",
    "uncertainty": "Sample data only; this is a research heuristic, not investment advice or a validated prediction.",
    "generated_at": "2026-10-10T18:05:01Z",
    "data_mode": "sample",
    "decision_engine": {
      "name": "deterministic_fixture",
      "status": "used"
    }
  },
  "warnings": []
}
```

### Response invariants

- All timestamps are ISO 8601 UTC strings. `published_at` may be `null` only when a source does not provide it; `observed_at` and `retrieved_at` must not be invented.
- `data_mode` is one of `live`, `cached`, or `sample` and is explicit at both response and record level.
- `assessment.label` is one of `buy`, `hold`, `sell`, or `insufficient_data`. It is a categorical research heuristic, not a probability, personalized recommendation, or validated forecast.
- `reason_codes` reference IDs in `evidence` and/or `signals`, **or** a documented system reason code when no corresponding record can exist. The initial proposed system code is `missing_attributable_evidence`; future system codes require a contract update. The final implementation must not produce undeclared codes or dangling record references.
- A numeric score is deliberately absent. If later added, Gate 0 must define its range, interpretation, evaluation limits, and UI label.
- `warnings` is an array of structured warning objects using the same `code`, `message`, and `retryable` fields as errors, but a successful response may still include it.

## Error envelope

Every non-2xx response uses this stable envelope:

```json
{
  "error": {
    "code": "invalid_symbol",
    "message": "symbol must be an uppercase ticker containing 1 to 5 letters",
    "retryable": false,
    "details": {"field": "symbol", "received": "ACME!"}
  },
  "request_id": "req-example-001"
}
```

`details` is optional and must remain safe to show in the UI and logs: never include credentials, raw provider payloads, or private account data.

### Required failure examples

#### Invalid symbol — `400 Bad Request`

```json
{
  "error": {
    "code": "invalid_symbol",
    "message": "symbol must be an uppercase ticker containing 1 to 5 letters",
    "retryable": false,
    "details": {"field": "symbol", "received": "ACME!"}
  },
  "request_id": "req-invalid-symbol-001"
}
```

A syntactically valid but unsupported ticker is proposed to use `unsupported_symbol` with `400`; Gate 0 must confirm this rather than overload `invalid_symbol`.

#### Provider unavailable — `503 Service Unavailable`

```json
{
  "error": {
    "code": "provider_unavailable",
    "message": "The evidence provider is temporarily unavailable; no assessment was generated.",
    "retryable": true,
    "details": {"provider": "news"}
  },
  "request_id": "req-provider-unavailable-001"
}
```

Do not silently substitute a live provider response with a fixture. The caller may explicitly retry or choose a separate, visibly labeled fixture-demo action after Gate 0 defines it.

#### Stale data — `409 Conflict`

```json
{
  "error": {
    "code": "stale_data",
    "message": "Available evidence is older than the allowed freshness window; no current assessment was generated.",
    "retryable": true,
    "details": {
      "oldest_as_of": "2026-10-07T16:00:00Z",
      "stale_after_seconds": 86400
    }
  },
  "request_id": "req-stale-data-001"
}
```

Whether stale data may instead yield `200` plus `assessment.label: insufficient_data` is unresolved and must be selected at Gate 0. This proposal chooses a blocking error to avoid presenting old data as current.

#### Insufficient data — `200 OK`

```json
{
  "request_id": "fixture-acme-insufficient-001",
  "symbol": "ACME",
  "data_mode": "sample",
  "freshness": {
    "as_of": "2026-10-10T18:00:00Z",
    "retrieved_at": "2026-10-10T18:05:00Z",
    "status": "fresh",
    "stale_after_seconds": 86400
  },
  "evidence": [],
  "signals": [
    {
      "id": "sample-acme-signal-001",
      "symbol": "ACME",
      "name": "30-day price change",
      "value": 2.4,
      "unit": "percent",
      "window": "30d",
      "as_of": "2026-10-10T16:00:00Z",
      "source": "Fixture Market Data",
      "data_mode": "sample"
    }
  ],
  "assessment": {
    "label": "insufficient_data",
    "horizon": "30d",
    "reason_codes": ["missing_attributable_evidence"],
    "explanation": "An assessment was not generated because attributable evidence is missing.",
    "uncertainty": "Insufficient evidence to support a research assessment.",
    "generated_at": "2026-10-10T18:05:01Z",
    "data_mode": "sample",
    "decision_engine": {
      "name": "deterministic_fixture",
      "status": "not_run"
    }
  },
  "warnings": [
    {
      "code": "insufficient_evidence",
      "message": "No attributable evidence records are available for this symbol.",
      "retryable": false
    }
  ]
}
```

`insufficient_data` represents a completed, truthful assessment attempt; it is not a transport failure. The front end must render it distinctly from provider failure and stale data.

## Project-owned Akamai OpenAI-compatible inference adapter

This boundary is proposed for the Strands text-generation client only. It is separate from the shared Jev tool, which calls TypeSafe's non-OpenAI-compatible System One API through its existing SDK wrapper.

```text
route / orchestration (Jet) → InferenceAdapter protocol → AkamaiOpenAICompatibleAdapter
                                                     └→ DeterministicFixtureAdapter
```

### Boundary requirements

1. **Server-side only:** the Akamai base URL, API token, model/deployment ID, and any headers remain in backend process configuration. The browser receives only the API response; it never receives provider credentials or calls Akamai inference directly.
2. **Adapter interface, not provider leakage:** orchestration requests a typed `generate_assessment_explanation(...)` result from an `InferenceAdapter`. It does not construct Akamai HTTP requests or inspect provider-specific response bodies.
3. **Explicit availability:** if `AKAMAI_INFERENCE_ENABLED` is false, configuration is incomplete, or the provider call fails, `AkamaiOpenAICompatibleAdapter` returns an explicit unavailable result. It does not fabricate model output.
4. **Deterministic fixture fallback:** `DeterministicFixtureAdapter` is an offline implementation that returns fixed, versioned fixture text from supplied fixture inputs. It is selected only by an explicit demo/test configuration or endpoint mode, returns `engine: deterministic_fixture`, and causes response `data_mode: sample`. It must not be silently selected after a failed live request.
5. **No implementation or credentials in A1:** this is a documented interface boundary only. A2 may implement it after Gate 0 and after Allen/Jet confirm the actual OpenAI-compatible endpoint, authentication header, available model, rate limits, and harmless server-side test procedure.
6. **Logging:** record provider name, selected adapter, model/deployment identifier, request ID if supplied, latency, and safe failure class. Never log authorization values, raw prompts containing private data, raw provider payloads, or account data.
7. **Jev remains project-owned and shared:** retain `microservices/jev-tool` as the shared Python/MCP wrapper. It stays independently feature-gated by `JEV_ENABLED`; its `engine: unavailable` result must propagate as an explicit decision-path limitation, never become a disguised live or fixture Jev result.

### Proposed configuration names (names only)

```text
AKAMAI_INFERENCE_ENABLED=false
AKAMAI_INFERENCE_BASE_URL=
AKAMAI_INFERENCE_API_KEY=
AKAMAI_INFERENCE_MODEL=
AKAMAI_INFERENCE_TIMEOUT_SECONDS=10
ASSESSMENT_INFERENCE_MODE=fixture
```

These are intentionally names and defaults only. They do not assert Akamai's final endpoint, authentication scheme, model catalog, or provisioning state.

## Additions made by the decision maker (A3)

> **Status: implemented on `jet/a3-decision-maker`, tested offline and run live for one symbol on 2026-10-10; not yet reviewed at Gate 0.** Everything above still stands. These are additive: a client written against the shapes above keeps working. Detail is in [`microservices/decision-maker/README.md`](../microservices/decision-maker/README.md).

### Request

| Field | Type | Required | Rule |
|---|---|---:|---|
| `query` | string | no | A free-text question about the symbol, at most 2,000 characters (the decision maker uses the first 500). It steers which evidence the explanation looks at and what `assessment.answer` says. **It never changes `assessment.label`.** |
| `mode` | string | no | `sample` (the fixed snapshot, unchanged), `live`, `failure`, or `sample_decision` (the decision maker over its packaged fixture, offline). |

`preferences.horizon` now scales the implied-move figure in the uncertainty statement. `preferences.risk_profile` is passed to the explanation for tone only and does not affect the label.

### Response

| Field | Meaning |
|---|---|
| `query` | The question as used (cleaned and capped), or `null` |
| `assessment.answer` | The model's short answer to the question; `null` with no question, no model, or when the answer failed review |
| `assessment.explanation_points` | `[{text, evidence_ids}]`: the cited points that `assessment.explanation` is assembled from |
| `assessment.decision_engine` | `{name: "combiner-v1", status: "used" \| "not_run"}`. `not_run` only when no evidence was in the recency window. A `buy` or `sell` needs at least one kind of attributable evidence leaning that way; a price move alone gives `hold`. |
| `freshness.status` | Adds `unknown` (no evidence to date) alongside `fresh` and `stale` |
| `meta` | `decision_trace`, `explanation_engine`, `jev_review`, `judgments_at_decision`, `retrieval`. Diagnostic; safe to show, not required to render. |

Signals now include rows derived from the options math, for example `ATM implied volatility` and `Implied one-standard-deviation move`. They describe how much movement is priced, not direction.

### System reason codes

`reason_codes` may contain, besides ids of returned evidence and signals:

| Code | When |
|---|---|
| `missing_attributable_evidence` | No evidence for the symbol inside the recency window (already declared above) |
| `insufficient_direction_signals` | Evidence exists, but fewer than two independent kinds gave a usable reading |

### Errors

Unchanged envelope. `stale_data` (`409`) carries `details.newest_retrieved_at` and `details.stale_after_seconds`. An unexpected server fault returns `500` with `code: internal_error`.

## Gate 0 decisions still unresolved

| Decision | Owner(s) | Why it blocks or constrains integration |
|---|---|---|
| Exact supported demo symbol(s) and judge-facing user journey | Team / Jet | Determines supported-symbol validation and fixture coverage. |
| Permitted news and market providers, storage/link rights, rate limits | Cai + team | Determines source attribution, retained fields, retrieval behavior, and whether a live path is allowed. |
| This contract's final route, schema, enums, error status mapping, stale policy, and fixture UX | Jet + Cai + Hemanth + Allen | Frontend, adapters, tests, and deployment cannot safely target an unapproved shape. |
| Timestamp semantics and freshness threshold by signal/evidence type | Jet + Cai | Prevents mixing observation time, publication time, retrieval time, and stale data. |
| Assessment horizon and any future numeric-score meaning | Jet + Cai + team | Avoids unsupported predictive or suitability claims. |
| Jev real-access proof, policy, latency, input/output limits | Jet | The shared tool is offline-tested only; its real availability is unverified. |
| Akamai OpenAI-compatible inference endpoint, server auth, model, limits, and safe test procedure | Allen + Jet | Required before implementing or claiming the Akamai inference adapter. |
| Whether vector storage is needed and its retention policy | Allen + Jet | Changes retrieval semantics and deployment scope; not required for this small v0. |
| Deployment target, available credits, and approval to provision | Allen + Jet | A1 must not provision or deploy. |

## Gate 0 acceptance checklist

- [ ] All lane owners accept or revise the request, success, warning, and error examples above.
- [ ] Hemanth confirms the frontend can represent `sample`, `cached`, `live`, provider-unavailable, stale-data, and insufficient-data states.
- [ ] Cai confirms source, unit, and timestamp fields meet the chosen providers' rights and data realities.
- [ ] Allen and Jet confirm the Akamai adapter's actual server-side connection details without committing secrets.
- [ ] Jet records accepted decisions in `DECISIONS.md`, freezes the v0 schema, and authorizes A2/B2/C2/D2.
