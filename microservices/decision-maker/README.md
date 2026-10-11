# decision-maker

The combination layer. Evidence from the store, an optional user question and the quant math go in; a **buy / hold / sell / insufficient_data research assessment** with a cited explanation comes out.

It is a library, not a service. `research-api` imports it, builds it from the environment and passes the math in (`microservices/research-api/src/research_api/assessment.py`).

> **Status:** tested offline (119 tests, no network). The live paths (reading the shared Postgres store, the Strands agent on Akamai inference, Jev review) are built against the documented interfaces but **have not been run against the real services yet**. The label is a rule-based research heuristic. Nothing here is investment advice, a probability or a validated prediction.

## How a request is handled

```text
validate -> retrieve -> legs -> quant -> combine -> explain -> review -> respond
```

| Step | Module | What happens |
|---|---|---|
| retrieve | `retrieval.py` | Read-only SQL over the `evidence` and `signals` tables `scraper-analysis` writes; pgvector search for the user's question |
| legs | `legs.py` | Four direction readings: news, insider, congress, price |
| quant | `quant.py` | The vol-surface math becomes named buckets and signal rows |
| combine | `combiner.py` | **The label is decided here**, by a pure function (`combiner-v1`) |
| explain | `explain.py` | A Strands agent writes cited points and answers the question |
| review | `review.py` | Jev checks the model's text before it is returned |

Two rules shape the design:

- **Code decides, the agent explains.** The label is not part of the agent's output, so it cannot change it. The same inputs always give the same label.
- **The question never moves the label.** The label uses every in-window record for the symbol. The question only decides which records the explanation looks at first and what it answers.

## Use

```python
from decision_maker import DecisionMaker, DecisionRequest

response = DecisionMaker().decide(DecisionRequest(symbol="NVDA", query="What about the inquiry?", mode="sample"))
response.assessment.label, response.assessment.explanation, response.assessment.uncertainty
```

`mode="sample"` runs over the packaged fixture (`src/decision_maker/fixtures/sample_inputs.json`): invented records, all labelled `data_mode: "sample"`, no network. `mode="live"` (the default) needs an evidence source and is never answered from fixtures.

`decide()` raises `InvalidSymbolError`, `ProviderUnavailableError` or `StaleDataError` (each carries `code`, `message`, `retryable`, `details` for the contract's error envelope). Everything else, including `insufficient_data`, is a normal response.

Everything outside the package is injected, so it can be tested without a network:

| Argument | What it is | In `research-api` |
|---|---|---|
| `evidence_source` | `PgEvidenceSource(database_url, embedder=...)` | built from `DATABASE_URL` |
| `agent_factory`, `agent_model` | `openai_compatible_agent_factory(base_url=, api_key=, model_id=)` | Akamai inference settings |
| `use_agent_tools` | `False` packs the data into the prompt for a model without tool calling | `DECISION_AGENT_TOOLS` |
| `article_judge` | judges news stored without a Jev judgment | `JevDecisionAdapter` |
| `explanation_checker` | reviews model-written text | `JevExplanationAdapter` |
| `stale_after_seconds` | freshness window, default 86400 | `DECISION_STALE_AFTER_SECONDS` |

## Handing over the math

The math is written in `research-api`, based on [vol-surface-builder](https://github.com/hemanthsrp/vol-surface-builder). It reaches the decision maker as a `QuantInput`. `VolSurfaceSnapshot` uses the same key names as `compute_surface_statistics(df, S)`, ignores keys it does not know and reads NaN as missing, so the builder's dict can be passed nearly as it is:

```python
from datetime import datetime, timezone

from decision_maker import QuantInput, VolSurfaceSnapshot
from research_api import assessment


def quant(symbol: str, horizon: str) -> QuantInput | None:
    df, spot = get_option_data(source="live", ticker=symbol)
    return QuantInput(
        vol_surface=VolSurfaceSnapshot(
            **compute_surface_statistics(df, spot),
            spot=spot,
            as_of=datetime.now(timezone.utc),       # when the option chain was observed
            source="Yahoo Finance options (yfinance)",
            data_mode="live",                       # "sample" for the synthetic SVI surface
            atm_iv_by_expiry=[{"T": 0.08, "iv": 0.34}, {"T": 1.0, "iv": 0.29}],   # optional
            svi_fits=calibrate_svi_surface(df).to_dict("records"),                 # optional
        )
    )


assessment.set_quant_provider(quant)   # once, at start-up
```

| Field | Needed | Notes |
|---|---|---|
| `spot`, `as_of`, `source`, `data_mode` | yes | Provenance the builder does not emit. A `sample` surface is ignored by a live assessment. |
| `atm_iv_mean`, `skew_25d_proxy`, `n_points`, `n_expiries` | from the builder | Annualized volatility as a fraction (0.24 = 24%). NaN or missing is accepted. |
| `iv_range`, `T_range`, `strike_range` | optional | Carried for reference |
| `atm_iv_by_expiry` | optional | One `{T, iv}` per expiry, `T` in years. Without it the term structure is not read. |
| `svi_fits` | optional | Rows of `calibrate_svi_surface(df)`; only `T`, `rmse`, `converged` are read |
| `QuantInput.signals` | optional | Any other dated signals in the contract shape; returned and citable |

Returning `None`, or raising, is fine: the assessment is still produced from evidence and says the math was unavailable.

**What the math does to the result.** The surface statistics describe how much movement and downside protection options are pricing, not which way the stock will go (the builder's own `docs/methodology.md`, section 7). So the math never sets direction. It does two things:

1. It raises the amount of agreement needed to leave `hold` when priced volatility is high, the skew is steep or the term structure is inverted.
2. It supplies the implied move quoted in the uncertainty statement.

Thin surfaces (few quotes, few expiries, SVI not converging, no near-the-money strikes) are reported but not acted on.

## The rule

All of these are hand-set constants, not fitted or validated. They are returned with every response under `meta.decision_trace.thresholds`.

**Direction legs** (`legs.py`). Evidence must fall within 45 days of the request.

| Leg | Weight | Reads | Rule |
|---|---|---|---|
| news | 0.4 | news and social records with a Jev judgment (`details.jev`) | Strength-weighted tone, 72-hour half-life, one event repeated by several outlets counted once, off-topic and unusable records left out; needs 3 stories |
| insider | 0.3 | Form 4 `details` | Net discretionary open-market dollars, at least $100k either way; 10b5-1 plan trades excluded |
| price | 0.2 | the `30-day price change` signal | At least 5% either way |
| congress | 0.1 | `details.transaction_type` | Purchases against sales |

**Combiner** (`combiner.py`).

- Net direction is the weighted mean over the legs that have data.
- `buy` at or above +0.25, `sell` at or below -0.25, otherwise `hold`. The bar is 0.40 when the math says so (above) or on-topic news names a scheduled event ahead.
- `insufficient_data` with `missing_attributable_evidence` when no evidence is in the window, or `insufficient_direction_signals` when fewer than two legs have data.
- `reason_codes` are ids of returned evidence or signals behind the label, or one of those two system codes.

**Options buckets** (`quant.py`).

| Bucket | Values | Rule |
|---|---|---|
| Priced volatility | low / moderate / high | ATM implied volatility below 20%, or 40% and above. Absolute levels, not relative to the symbol's own history. |
| Implied move | percent | `atm_iv_mean * sqrt(horizon_days / 365)`, one standard deviation |
| Skew | normal / steep | `skew_25d_proxy / atm_iv_mean` of 0.30 or more is steep |
| Term structure | normal / flat / inverted | Shortest expiry (a week or more out) against the longest; a ratio of 1.10 or more is inverted |
| Data quality | ok / thin | At least 30 quotes, 3 expiries, and SVI converging on half the expiries |

The news rule and its weights are a port of `scraper-analysis/pipeline/grade.py` (`grade-v1`); a stored `details.grade` is used as it is. The insider, congress and price thresholds match `pipeline/divergence.py` on the open `achen/scraper-divergence` branch.

## Reading the evidence store

`PgEvidenceSource` reads the tables in `scraper-analysis/src/scraper_analysis/storage/schema.sql` directly.

- **Read-only.** Every session is opened with `default_transaction_read_only=on`.
- **TLS.** A non-local `DATABASE_URL` must carry `sslmode=require`, the same rule the scraper enforces.
- **Bounded.** The newest 300 evidence rows and 100 signal rows per symbol.
- **Semantic search** embeds the question with the injected embedder, scopes to the symbol first and then ranks that set by pgvector cosine distance. With no embedding it reports that search was unavailable; it does not return some other ordering.
- **Fixtures in a live store.** Rows with `data_mode: "sample"` are dropped before anything is computed, and reported.
- **Unjudged news.** Rows stored before Jev was enabled carry no `details.jev`. With an `article_judge` the newest 12 are judged at decision time; nothing is written back. Their titles and summaries go to TypeSafe, so the source-terms question in `docs/TASKS.md` applies.

## The explanation

- The agent is a Strands `Agent` on an OpenAI-compatible endpoint, with four read-only tools bound to the request: `get_decision`, `get_evidence`, `get_signals`, `search_evidence`.
- Its citations are verified in code: an id it was never shown is stripped, and a point left with no valid citation is dropped.
- If the tools attempt fails, the same agent is given the data in its prompt. If that fails too, a templated explanation built from the legs is returned, labelled `explanation_engine: template`, with a warning.
- The opening sentence and the uncertainty statement are written by code, not the model.
- Jev review (`check_explanation`): a point its cited news does not support is removed; wording that reads as personal advice or a promised outcome replaces the model's text with the template. Points resting on filings or signals are not checked. When Jev is unavailable the text passes unreviewed and `meta.jev_review` says so.

## Response

The shape in `docs/api-contract-v0.md`, with these additions: `query`, `assessment.answer`, `assessment.explanation_points`, and `meta`:

| `meta` key | Contents |
|---|---|
| `decision_trace` | Combiner version, each leg with its inputs and record ids, the options buckets, thresholds, and `net_direction` (an internal quantity, not a score for display) |
| `explanation_engine` | `strands_agent` or `template`, the model, `tools` or `context` mode, any error |
| `jev_review` | Per-point review results, or `null` when no review was attempted |
| `judgments_at_decision` | How many unjudged news items were sent to Jev and what came back |
| `retrieval` | Whether semantic search ran and which records matched the question |

Warnings are structured (`code`, `message`, `retryable`). Codes: `sample_data`, `sample_records_ignored`, `quant_unavailable`, `quant_thin`, `quant_sample_ignored`, `evidence_outside_window`, `news_judgment_unavailable`, `insufficient_evidence`, `semantic_search_unavailable`, `query_truncated`, `question_not_answered`, `explanation_model_unavailable`, `explanation_review_unavailable`, `unverifiable_citations_removed`, `uncited_points_removed`, `unsupported_point_removed`, `unsupported_answer_removed`, `explanation_replaced`.

## Known limits

- **Freshness uses `retrieved_at` of the newest evidence row.** The scraper only stores a row the first time it sees it, so a quiet symbol can read as stale even right after an ingest run, and the default 24-hour window then returns `stale_data`. Raise `DECISION_STALE_AFTER_SECONDS` for a demo, or have the scraper record when it last ran.
- With Jev off and no stored judgments, the news leg has no data. The tagging agent's sentiment is not used as a stand-in, because it gave off-topic feed items a direction in the scraper's live runs.
- Akamai's chat model has not been tested for tool calling; the prompt-only fallback covers that case.
- House of Representatives disclosures are not collected upstream, so the congress leg is Senate-only today.

## Setup and tests

Python 3.10 or newer.

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,pg,agent]"    # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m pytest
```

`pg` adds `psycopg` for the store; `agent` adds `strands-agents[openai]`. The core package and sample mode need only `pydantic`.
