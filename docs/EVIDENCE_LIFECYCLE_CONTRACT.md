# D5 evidence lifecycle and attribution contract proposal

**Status:** proposed 2026-10-11. This document records a read-only audit and a
schema/API proposal. It is not accepted until Cai approves the scraper/storage
changes and Jet approves the Research API response changes.

## Audit result

The shared managed PostgreSQL store was queried read-only without printing
article text, URLs, credentials, or embeddings.

| Check | Result |
|---|---:|
| Evidence records | 614 |
| Records with source URL | 614 |
| Records with publication date | 614 |
| Records with a 1,024-dimension embedding | 614 |
| Records with stored Jev judgment | 0 |
| Records with stored grade | 0 |
| Records older than 30 days by retrieval time | 0 |
| Explicit lifecycle/provenance-category columns | 0 |

The rows comprise 429 live `general_news`, 132 live `sec_filing`, and 53 live
`congressional_disclosure` records. The signal store has 25 live Yahoo Finance
30-day price-change records plus weather/commodity signals. Every current row
is source-attributable and vectorized, but the database cannot currently state:

- whether a result is fresh, stale, archived, or past a provider-retention date;
- the policy/rationale for retaining an archived record;
- whether a frontend value comes from Yahoo market data, an options surface,
  a filing/disclosure, or an attributable article;
- a frontend-sortable impact category or importance label.

Existing article text and citations must remain retained; no migration may
re-embed, overwrite, or delete a source record merely to add these fields.

## Important distinction: vectors are not scores

`evidence.embedding` is a 1,024-number semantic representation of the
attributable title and permitted summary. It is not a market-mover value,
confidence score, impact score, prediction, or source of truth. The frontend
must never display vector coordinates or infer a ranking from them.

Semantic search is only an optional retrieval aid. It must first filter by
symbol, lifecycle status, time window, data mode, source/right-to-retain policy,
and evidence category. The returned item must show its citation and its typed
value origin.

Numeric Yahoo and volatility values remain authoritative typed `signals` or
quant-snapshot fields. They should not be converted to text embeddings just to
make them searchable. A response can cite an associated market-data source, but
must state the numerical measurement, unit, window, as-of timestamp, and
provider separately from article evidence.

## Proposed data model

### Article, filing, and disclosure evidence (`evidence`)

Keep the current identity, source, source URL, publication/observation/retrieval
times, data mode, Jev details, grade details, and `vector(1024)` embedding. Add
these fields with non-destructive defaults:

| Field | Type / allowed values | Purpose |
|---|---|---|
| `provider` | text | Source system, for example `marketaux`, `sec_edgar`, `congressional_disclosure`, or `exa`. Not an unverified publisher name. |
| `value_origin` | text enum | `article`, `filing`, `congressional_disclosure`, `market_signal`, `options_surface`, or `derived_assessment`. A row may never be ambiguous. |
| `impact_category` | text enum | `market_mover`, `company_event`, `fundamental`, `insider_trade`, `regulatory_or_filing`, `congressional_trade`, `options_risk`, `macro`, or `other`. |
| `impact_level` | text enum | `unknown`, `low`, `medium`, or `high`. It means evidence triage importance, never a price-move probability. |
| `impact_basis` | JSONB | Versioned deterministic/Jev factors and source evidence IDs used to assign the category/level. An unavailable Jev result is recorded as unknown, not guessed. |
| `embedding_status` | text enum | `available`, `unavailable`, or `not_applicable`; distinguishes a missing vector from an intentional non-text record. |
| `lifecycle_status` | text enum | `fresh`, `stale`, or `archived`. |
| `fresh_until` | timestamptz | Last time this item can contribute to a current assessment under the source/category policy. |
| `stale_at` | timestamptz | Time at which the frontend must label the record stale. |
| `archived_at` | timestamptz nullable | When it stopped appearing in default current-result views. |
| `retention_until` | timestamptz nullable | Latest permitted retention time; a worker must delete/redact after it. |
| `retention_reason` | text nullable | Policy basis such as `historical_research`, `provider_terms`, or `user_requested_deletion`. |

`lifecycle_status` is a stored serving state refreshed by a scheduled lifecycle
job. Query-time checks still enforce timestamps so an overdue job cannot make a
stale row look current.

### Market and volatility values (`signals` and quant snapshots)

Signals retain their current numeric `value`, `unit`, `window`, `as_of`,
`source`, and `data_mode`. Add:

| Field | Requirement |
|---|---|
| `value_origin` | `yahoo_market` for Yahoo Finance values; `options_surface` for implied-volatility diagnostics; other provider-specific explicit values for future adapters. |
| `impact_category` | `market_mover` for a realized price/volume/realized-volatility measurement; `options_risk` for IV/skew/term-structure; never `article`. |
| `impact_level` and `impact_basis` | A documented deterministic threshold/version, or `unknown`. No LLM-decided numerical market significance. |
| `source_url` or `source_reference` | A provider/reference link when allowed, plus a source retrieval identifier if a stable URL is unavailable. |
| `retrieved_at` and lifecycle fields | Needed for freshness and historical rendering just as for evidence. |

The volatility API response should be persisted as an immutable quant snapshot
(or its returned diagnostics attached to the assessment) before it can be cited
as an assessment input. A failed volatility request creates no fabricated
snapshot and must preserve `quant_provider_failed` or `quant_unavailable`.

### Citation and frontend projection

Every assessment contribution must project one of these explicit forms:

```json
{
  "contribution_id": "stable ID",
  "kind": "article_evidence | market_signal | options_surface | filing | congressional_disclosure",
  "value_origin": "article | yahoo_market | options_surface | filing | congressional_disclosure",
  "impact_category": "market_mover | company_event | ...",
  "impact_level": "unknown | low | medium | high",
  "value": 3.2,
  "unit": "percent",
  "as_of": "2026-10-11T00:00:00Z",
  "source_name": "Yahoo Finance (yfinance)",
  "source_url": null,
  "published_at": null,
  "retrieved_at": "2026-10-11T06:54:00Z",
  "lifecycle_status": "fresh",
  "data_mode": "live",
  "reasoning": {
    "method": "realized_price_change_30d",
    "version": "...",
    "limitations": ["historical measurement, not a forecast"]
  }
}
```

Article entries set `value` and `unit` to `null` unless the source has a
structured, verified measurement. Their `source_url`, `published_at`,
`retrieved_at`, content type, Jev/grade state, and citations remain present.
`explanation_points[].evidence_ids` and `reason_codes` must continue to resolve
to the complete visible article/signal source list.

The frontend sorts and filters typed metadata (`lifecycle_status`, dates,
`value_origin`, `impact_category`, `impact_level`, `data_mode`) rather than
semantic-vector distance. Default views show `fresh`; a labelled historical
view may include `stale` and `archived` records subject to `retention_until`.

## Required ingestion and grounding order

1. Fetch a permitted source through its bounded adapter; retain source result,
   date, URL/reference, provider, and data mode.
2. Normalize, validate dates/units/URLs, deduplicate, and assign a stable ID.
3. For articles only, run Jev article judgment when enabled and permitted;
   require `engine == "jev"` before using it for classification. Persist
   `unavailable` honestly. Reuse a stored judgment rather than re-calling Jev.
4. Apply the versioned deterministic grade. Do not drop off-topic/unusable
   records; preserve and mark them. Use only ungated records for aggregate
   tone/decision contributions.
5. Assign `value_origin`, category, impact basis, and lifecycle/retention
   policy. Numeric Yahoo/volatility values use deterministic source-specific
   rules; Jev classifies article text only.
6. Generate the embedding from permitted title/summary text. Validate its
   dimension is exactly 1,024; failure stores the record with explicit
   `embedding_status: unavailable` rather than a fake vector.
7. In one transaction, persist the immutable source metadata, grounding
   outputs, lifecycle state, typed signal/quant measurement, and embedding.
8. On assessment read, structurally filter to live/cached permitted data,
   fresh lifecycle state, correct symbol, and horizon before optional vector
   ranking. The deterministic combiner chooses the label; volatility adjusts
   uncertainty only.
9. Generate an explanation from the bounded cited sources, enforce known IDs,
   and run Jev explanation review. Drop unsupported factual sentences and
   block personal advice or promised outcomes. Return review state/warnings.

## Migration and verification gates

1. Cai approves schema ownership, source-retention policy, and ingestion
   behavior; Jet approves the response projection. Record acceptance in
   `DECISIONS.md`.
2. Add an idempotent migration with nullable/additive columns and indexes for
   default frontend filters. Do not rewrite stored article text or embeddings.
3. Backfill current rows as `value_origin` based on `source_type`; set
   `impact_level=unknown`, `lifecycle_status=fresh`, and policy-derived
   timestamps. Do not claim old rows were Jev-grounded: the audit shows zero
   contain Jev or grade details.
4. Add a lifecycle job with a dry-run report and an explicit apply mode. It
   must archive only records past `stale_at`; it must delete/redact only after
   `retention_until` and a source-rights review.
5. Add tests for source/date preservation, category validation, Jev success and
   unavailable states, embedding dimension failure, retention transition,
   structural-before-vector query ordering, and article-versus-Yahoo frontend
   projections.
6. Run a strict live demo: ingest with `fallback=false`, verify persisted
   provenance/grounding metadata, call the live volatility service, call the
   Research API live assessment, verify Jev review status, and render the
   returned citations and lifecycle labels in the frontend.

No step above validates a price prediction or turns an impact label into a buy
or sell guarantee.
