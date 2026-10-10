# Proposed architecture and integration contracts

> **Design proposal, not implemented.** The repository currently contains documentation only. Verify service APIs, model availability, source rights and Akamai resources before committing to a provider.

## Vertical slice

```text
Next.js UI (Hemanth lane)
   │ select symbol / preferences; display sources, chart, assessment
   ▼
Python HTTP API + Strands orchestration (Jet lane)
   ├── source adapter → normalized article evidence (Cai lane)
   ├── market/quant adapter → dated, unit-labeled signals (Cai lane)
   ├── optional retrieval index → evidence by symbol/time (Allen lane)
   └── decision adapter → JEV via MCP if verified (Jet lane)
   ▼
Akamai deployment / storage / logs / health checks (Allen lane)
```

The baseline `vol-surface-builder` described in `DUMP.md` is **not** a price predictor or news collector. Hemanth should identify transferable source-adapter patterns, tests and charting before any copy/import; don't treat its Black–Scholes/SVI outputs as validated buy/sell signals.

## Contract-first rule

The lane owners agree on concrete JSON schemas and API paths **before** building both sides. Below is a minimal *proposed* contract for discussion, not a pre-existing endpoint. Record final choices in `DECISIONS.md` and update this document when implementation lands.

- Request: `symbol` (normalized uppercase ticker) and optional non-sensitive demo preferences. Validate allowed symbols and inputs.
- Evidence item: stable `id`, `symbol`, `title`/summary, `source_name`, `source_url` if permitted, `published_at` if known, `observed_at`, `retrieved_at`, and `data_mode` (`live`, `cached`, `sample`); do not fabricate timestamps.
- Quant signal: `symbol`, `name`, `value`, `unit`, `window`, `as_of`, `source`, and `data_mode`. Separate historical realized measures from forward-looking claims.
- Assessment: `symbol`, `label` (`buy`/`hold`/`sell` or an explicit `insufficient_data`), `horizon`, `reason_codes` or evidence IDs, explanation, `generated_at`, `data_mode`, and an uncertainty statement. A numeric score is optional and must have a documented meaning.
- API response: includes evidence, signals, assessment, warnings/errors, and freshness metadata. When data is missing, preserve `insufficient_data` rather than manufacturing a recommendation.
- Errors: predictable shape/status for invalid symbol, unavailable provider, stale data and incomplete decision flow. UI must surface failures without showing old data as current.

**Contract checkpoint:** Jet/Cai/Hemanth/Allen review sample payloads, units, timestamp semantics, and failure cases. Freeze a small v0 schema before parallel UI/data/infrastructure implementations; changes require an explicit handoff in `TASKS.md` and `DECISIONS.md`.

## Data and safety boundaries

- All outside services sit behind adapters; source retrieval/market retrieval, Strands, MCP/JEV, and storage can be exercised with deterministic fixtures offline.
- Attribute news; store only allowed excerpts/metadata. A vector DB is optional for the MVP if a small evidence set can be retrieved directly. Never treat a semantic match as proof of a claim.
- Keep audit-friendly IDs and timestamps from ingest through assessment. Logs must avoid tokens, raw financial account data and unnecessary personal information.
- Put secrets in local environment/secret manager, never code or Markdown. Use a safe example config with names only. Never commit credentials from Akamai kickoff.
- No trade placement or account mutation. Brokerage access is a separate, explicitly approved extension, not required for the first demo.

## Test seams and deployment evidence

- Unit: adapter normalization/deduplication; missing/stale records; numeric bounds/units; deterministic assessment fallback.
- Integration: route → Strands/tool calls → fixtures → response schema, plus frontend error/loading/sample labels.
- Deployment: documented Akamai service topology, health endpoint, logs without secrets, environment names, URL and an actual remote smoke test. If unavailable, mark deployment as blocked and use local fallback.
- Future evaluation: preserve historical snapshots and time-split labels before any predictive accuracy claim; compare against a simple baseline rather than cherry-picking examples.
