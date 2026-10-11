# decision-maker

The combination layer. Evidence from the store, an optional user question and the quant math go in; a **buy / hold / sell / insufficient_data research assessment** with a cited explanation comes out.

It is a library, not a service. `research-api` imports it, builds it from the environment and passes the math in (`microservices/research-api/src/research_api/assessment.py`).

> **Status:** 136 offline tests, and run live on 2026-10-10 through `POST /v0/research-assessments` for AAPL against the shared Postgres store, Akamai inference and TypeSafe (see "What the live runs showed"). The options math is wired to `microservices/volatility-surface-builder` and checked against that service's sample output; a live option chain has not been run through it yet. The label is a rule-based research heuristic. Nothing here is investment advice, a probability or a validated prediction.

## How a request is handled

```text
validate -> retrieve -> legs -> quant -> combine -> explain -> review -> respond
```

| Step | Module | What happens |
|---|---|---|
| retrieve | `retrieval.py` | Read-only SQL over the `evidence` and `signals` tables `scraper-analysis` writes; pgvector search for the user's question |
| judge | `judging.py` | News stored without a Jev judgment is judged now, so it can count |
| legs | `legs.py` | Four direction readings: news, insider, congress, price |
| quant | `quant.py` | The vol-surface math becomes named buckets and signal rows |
| combine | `combiner.py` | **The label is decided here**, by a pure function (`combiner-v1`) |
| explain | `explain.py` | A Strands agent writes cited points and answers the question |
| review | `review.py` | Jev checks the model's text before it is returned |

Two rules shape the design:

- **Code decides, the agent explains.** The label is not part of the agent's output, so it cannot change it.
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
| `use_agent_tools` | `True` also gives the agent two lookup tools. Default `False`. | `DECISION_AGENT_TOOLS` |
| `article_judge` | judges news stored without a Jev judgment | `JevDecisionAdapter` |
| `explanation_checker` | reviews model-written text | `JevExplanationAdapter` |
| `stale_after_seconds` | freshness window, default 86400 | `DECISION_STALE_AFTER_SECONDS` |

## Where the math comes from

The math is [`microservices/volatility-surface-builder`](../volatility-surface-builder/README.md). `research-api` asks that service for a symbol's surface and maps the reply onto a `QuantInput` (`research_api/quant.py`, switched on by `VOL_SURFACE_URL`):

| Service reply (`POST /v0/volatility-surfaces`) | `VolSurfaceSnapshot` field | Notes |
|---|---|---|
| `spot`, `source`, `data_mode` | same names | A `sample` surface is ignored by a live assessment |
| `retrieved_at` | `as_of` | The service gives no quote time (`market_observed_at` is null), so this is when the chain was fetched |
| `statistics.atm_iv_decimal` | `atm_iv_mean` | Annualized volatility as a fraction (0.24 = 24%). Null is accepted. |
| `statistics.skew_25d_proxy_decimal` | `skew_25d_proxy` | |
| `statistics.n_points`, `n_expiries` | same names | |
| `statistics.iv_range_decimal`, `maturity_range_years`, `strike_range` | `iv_range`, `T_range`, `strike_range` | Carried for reference |
| `surface` grid | `atm_iv_by_expiry` | One `{T, iv}` per maturity, read at the strike nearest spot. Enables the term structure. |

Any other source of math can be registered by hand; `VolSurfaceSnapshot` uses the key names of the builder's `compute_surface_statistics(df, S)`, ignores keys it does not know, accepts numpy values and reads NaN as missing:

```python
from decision_maker import QuantInput, VolSurfaceSnapshot
from research_api import assessment

assessment.set_quant_provider(
    lambda symbol, horizon: QuantInput(vol_surface=VolSurfaceSnapshot(**stats, spot=spot, as_of=when, source="...", data_mode="live"))
)
```

`svi_fits` (rows of `calibrate_svi_surface(df)`; only `T`, `rmse`, `converged` are read) and `QuantInput.signals` (other dated signals in the contract shape) are optional. A provider that returns `None` or raises does not block the assessment: it is produced from evidence and says the math was unavailable or failed.

**What the math does to the result.** The surface statistics describe how much movement and downside protection options are pricing, not which way the stock will go (the service's own README and `docs/methodology.md` say so). So the math never sets direction. It does two things:

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
- **A price move alone cannot carry a label.** A `buy` or `sell` also needs at least one kind of attributable evidence (news, insider, congress) leaning that way by 0.25 or more; otherwise the result is `hold` and `held_because` says `no_evidence_leg_agrees`. The first live run produced a `buy` from a rising price and neutral news, which is why this is here.
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

The volatility service prices every ticker with fixed risk-free-rate and dividend-yield assumptions (0.043 and 0.013), which its README says must be reviewed for a live ticker. The buckets above inherit that.

## Reading the evidence store

`PgEvidenceSource` reads the tables in `scraper-analysis/src/scraper_analysis/storage/schema.sql` directly.

- **Read-only.** Every session is opened with `default_transaction_read_only=on`; a write was refused in the live check.
- **TLS.** A non-local `DATABASE_URL` must carry `sslmode=require`, the same rule the scraper enforces.
- **Bounded.** The newest 300 evidence rows and 100 signal rows per symbol.
- **Semantic search** embeds the question with the injected embedder, scopes to the symbol first and then ranks that set by pgvector cosine distance. With no embedding it reports that search was unavailable; it does not return some other ordering.
- **Fixtures in a live store.** Rows with `data_mode: "sample"` are dropped before anything is computed, and reported.
- **Unjudged news.** Rows stored before Jev was enabled carry no `details.jev` (all 19 AAPL news rows, on 2026-10-10). With an `article_judge` the newest 24 are judged at decision time. Nothing is written back; answers are kept in memory for the life of the process so an article is sent once. Titles and summaries go to TypeSafe, so the source-terms question in `docs/TASKS.md` applies.

## The explanation

- The agent is a Strands `Agent` on an OpenAI-compatible endpoint. Its prompt carries a `DATA` block: the decision and its legs, the most relevant evidence (the question's matches first) and the signals, held to a character budget.
- With `use_agent_tools=True` it also gets two read-only tools bound to the request, `search_evidence` and `get_evidence`, for records outside that block. If that attempt fails, it is asked again with the data alone.
- Its citations are verified in code: an id it was never shown is stripped, and a point left with no valid citation is dropped.
- If the model fails, a templated explanation built from the legs is returned, labelled `explanation_engine: template`, with a warning.
- The opening sentence and the uncertainty statement are written by code, not the model. The user's question is capped, has angle brackets removed and is passed as data.
- Jev review (`check_explanation`): a point resting on news alone that its cited news does not support is removed, and an unsupported sentence is cut from the answer. Wording that reads as personal advice or a promised outcome replaces the model's text with the template. Text that also rests on filings or signals is not compared with the news. When Jev is unavailable the text passes unreviewed and `meta.jev_review` says so.

## What the live runs showed

One symbol, a handful of requests on 2026-10-10. Observations, not benchmarks.

| Check | Result |
|---|---|
| Store | AAPL only: 29 evidence rows (19 news, 10 filings), all with vectors, none with a Jev judgment; one price signal. Load took about 0.5s. |
| Semantic search | 1,024-dimension embedding in about 0.5s; 8 matching records returned for the question |
| Jev judging | Every unjudged news item asked was judged (12, later 19 once the limit was raised), in 0.5 to 2.7s |
| Explanation, data in the prompt | Worked in 7 of 8 runs once the endpoint issues below were handled. About 3,400 input tokens after the prompt was compacted, 450 to 870 output tokens, 15 to 28s. The one failure ended at a 700-token cap and fell back to the template; the cap is now 1,500. |
| Explanation, with tools | **Failed in all four attempts**: the token cap twice, unparseable output, and a context window overflow with rate-limit errors (about 150s under Strands' default back-off). This is why tools are off by default and retries are now bounded. |
| Jev review | Ran on every model-written explanation; no advice or promise flags, including for "Should I buy Apple stock right now?" |
| Whole request | HTTP 200 in 18 to 27s after the fixes. Label `hold`: news mixed, price up 8.8%, no usable insider or congress reading, an event ahead in the news. |

Three things about the Akamai endpoint that the code now handles:

- It answers HTTP 400 to an empty `tools` array, which Strands sends when an agent has no tools. The factory drops the field.
- Its default output limit cut replies short; `max_tokens` is set explicitly.
- A single chat request with a tool definition does return a tool call, so tool calling itself works. It was the multi-step agent loop that did not fit.

## Response

The shape in `docs/api-contract-v0.md`, with these additions: `query`, `assessment.answer`, `assessment.explanation_points`, and `meta`:

| `meta` key | Contents |
|---|---|
| `decision_trace` | Combiner version, each leg with its inputs and record ids, the options buckets, thresholds, `held_because`, and `net_direction` (an internal quantity, not a score for display) |
| `explanation_engine` | `strands_agent` or `template`, the model, `tools` or `context` mode, any error |
| `jev_review` | Per-point review results, or `null` when no review was attempted |
| `judgments_at_decision` | How many unjudged news items were sent to Jev, reused from memory, and what came back |
| `retrieval` | Whether semantic search ran and which records matched the question |

Warnings are structured (`code`, `message`, `retryable`). Codes: `sample_data`, `sample_records_ignored`, `quant_unavailable`, `quant_thin`, `quant_sample_ignored`, `evidence_outside_window`, `news_judgment_unavailable`, `insufficient_evidence`, `semantic_search_unavailable`, `query_truncated`, `question_not_answered`, `explanation_model_unavailable`, `explanation_review_unavailable`, `unverifiable_citations_removed`, `uncited_points_removed`, `unsupported_point_removed`, `unsupported_answer_sentence_removed`, `unsupported_answer_removed`, `explanation_replaced`.

## Known limits

- **A request takes roughly 20 to 30 seconds** when the model writes the explanation, nearly all of it the model's output speed.
- **The news reading can differ between processes.** When news is judged at decision time, Jev's answers vary slightly from call to call (net direction ran from 0.27 to 0.32 across live runs of the same data). Within a process they are reused. Enabling Jev in the scraper stores one judgment per article and removes this.
- **Freshness uses `retrieved_at` of the newest evidence row.** The scraper only stores a row the first time it sees it, so a quiet symbol can read as stale even right after an ingest run, and the default 24-hour window then returns `stale_data`. Raise `DECISION_STALE_AFTER_SECONDS` for a demo, or have the scraper record when it last ran.
- With Jev off and no stored judgments, the news leg has no data. The tagging agent's sentiment is not used as a stand-in, because it gave off-topic feed items a direction in the scraper's live runs.
- The agent's lookup tools did not work on the Akamai model (above), so by default the agent can only cite what fits in its prompt: about ten records.
- House of Representatives disclosures are not collected upstream, so the congress leg is Senate-only today.
- The store held one symbol when this was tested.

## Setup and tests

Python 3.10 or newer.

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,pg,agent]"    # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m pytest
```

`pg` adds `psycopg` for the store; `agent` adds `strands-agents[openai]`. The core package and sample mode need only `pydantic`.
