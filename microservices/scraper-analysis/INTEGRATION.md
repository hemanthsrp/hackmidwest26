# scraper-analysis: integration guide

For the A3 wiring in `research-api` (`adapters/source`, `adapters/quant`). This service owns evidence collection, quant signals and an optional synthesis briefing. It does **not** produce a buy/hold/sell assessment; that stays in the decision lane.

## Run it

```
cd microservices/scraper-analysis
python -m venv .venv && source .venv/Scripts/activate   # Windows git-bash; use .venv/bin/activate elsewhere
pip install -e ".[dev]"
pip install -e ../jev-tool    # optional: only needed when JEV_ENABLED=true (see "Jev judgment" below)
cp .env.example .env        # fill in values; never commit .env
uvicorn scraper_analysis.api:app --port 8001 --app-dir src
```

Storage is in-memory unless `DATABASE_URL` is set (then Postgres + pgvector; run `src/scraper_analysis/storage/schema.sql` once, it is idempotent). With no live credentials every source falls back to labeled fixtures (`data_mode: "sample"`), so the service runs offline.

## Endpoints

| Route | Purpose |
|---|---|
| `POST /ingest/run?symbol=AAPL&live=true&fallback=true&tag=true` | Collect from all sources, score, dedupe, store. Returns **only newly stored** items, `signals`, a per-source `sources` report and `warnings`; a repeat run returns `evidence: []`. `live=false` forces fixtures; `fallback=false` refuses fixtures (see below); `tag=false` skips the Bedrock tagging call; `judge=false` skips the optional Jev judgment (see below) |
| `GET /evidence?symbol=AAPL` | Everything stored for the symbol. `status` is `ok` or `insufficient_data` |
| `GET /signals?symbol=AAPL` | Stored quant signals, same `status` convention |
| `GET /divergence?symbol=AAPL[&as_of=ISO8601]` | Where independent source types disagree (price vs discretionary insider trades vs congressional (Senate/House) trades vs news tone). Live, recent, never future-dated data only; a past `as_of` is labelled historical, a future one is rejected (400); deterministic, thresholds returned in the response |
| `POST /briefing?symbol=AAPL` | Cited research briefing from stored data (one Bedrock call, hence POST) |
| `GET /health` | Liveness |

Symbols are validated (`^[A-Z]{1,5}(\.[A-Z])?$`); invalid input returns `400 {"detail": ...}`. `/briefing` errors use the contract's envelope: `503 {"error": {"code": "briefing_unavailable", "message": ..., "retryable": true}}`.

Commodity symbols `CORN`, `SOYB`, `WEAT` additionally get futures, precipitation and drought signals.

## Evidence record

Superset of the v0 contract in `docs/api-contract-v0.md`: every field there is present with the same meaning. Extras are marked.

```json
{
  "id": "13124c2c-19a8-501f-b700-8734b165bf03",
  "symbol": "AAPL",
  "title": "Newstead Jennifer (SVP, GC and Government Affairs) sold 2,399 shares (open market, ~$796,492) of AAPL -- Form 4 [pre-scheduled 10b5-1 plan]",
  "summary": null,
  "source_name": "SEC EDGAR",
  "source_type": "sec_filing",
  "source_url": "https://www.sec.gov/Archives/edgar/data/320193/.../form4.xml",
  "published_at": "2026-10-08T00:00:00Z",
  "observed_at": "2026-10-06T00:00:00Z",
  "retrieved_at": "2026-10-10T23:51:58Z",
  "reporting_lag_days": 2.0,
  "details": {"insider": "Newstead Jennifer", "is_10b5_1": true, "sell_shares": 2399.0, "buy_shares": 0.0, "sell_value_usd": 796491.99},
  "entities": {"tickers": [], "sectors": [], "key_people": []},
  "sentiment": {"direction": null, "score": null},
  "credibility": {"overall_score": 1.0, "source_reliability_weight": 1.0, "verified_filing": true},
  "data_mode": "live"
}
```

- **IDs are deterministic**: the same item keeps the same ID across runs, so `reason_codes` can reference them safely. SEC filings hash the filing URL only (one row per accession number), so Form 4 enrichment, which rewrites the title and moves `observed_at` to the trade date, never mints a second ID; a stored copy is replaced only by a strictly better one (live beats sample, then parsed Form 4 details beat metadata-only), so a persisted fixture never blocks its live filing and a later fixture or metadata-only copy never downgrades it. Other records hash source URL + title + observed date. Stores populated before this rule: run `python -m scraper_analysis.storage.migrations` (dry run), then `--apply`, to re-key old SEC rows and delete their duplicates; it is idempotent.
- **Form 4 dates:** `observed_at` is the earliest actual `transactionDate` in the filing, not `periodOfReport`. `details.transaction_dates` lists every trade date (the title shows the range when there are several) and `details.period_of_report` keeps the filing's reporting period.
- **Three timestamps, never invented:** `published_at` (filing/article time), `observed_at` (when the underlying event happened, e.g. the trade date), `retrieved_at` (when we fetched it). Either of the first two can be `null` if the source doesn't give it.
- **Extras beyond v0:** `source_type`, `reporting_lag_days`, `details`, `entities`, `sentiment`, `credibility`. `details` holds structured, source-specific facts (Form 4 buy/sell totals plus the per-trade `transactions` breakdown, Senate transaction type and amount range). `entities`/`sentiment` are only filled when `tag=true` and Bedrock is reachable.
- **`source_type`** is one of `sec_filing`, `congressional_disclosure`, `general_news`, `social_media`.
- **`credibility.overall_score`** is a heuristic (outlet prior + cross-source corroboration, see `pipeline/scoring.py`), not a validated measure. Official filings are `1.0` by definition.

## Signal record

```json
{"id": "3606605f-...", "symbol": "AAPL", "name": "30-day price change", "value": 8.8217,
 "unit": "percent", "window": "30d", "as_of": "2026-10-09T00:00:00Z",
 "source": "Yahoo Finance (yfinance)", "data_mode": "live"}
```

Realized, historical measures only, never forecasts.

## `data_mode`, fallback, and freshness

`data_mode` on a record is `live` (fetched from the real source this run) or `sample` (deterministic fixture). Every `/ingest/run` response also carries a `sources` array so substitution is never invisible:

```json
"sources": [
  {"name": "sec_edgar", "status": "live", "count": 10, "error": null},
  {"name": "marketaux", "status": "fallback", "count": 2, "error": "NEWS_API_KEY not configured"}
]
```

| status | meaning |
|---|---|
| `live` | the real source answered |
| `sample` | fixtures, because you passed `live=false` |
| `fallback` | the live source failed and its fixture was substituted (records are `data_mode: "sample"`); also listed in `warnings` |
| `unavailable` | the live source failed and you passed `fallback=false`; nothing was substituted |

**Recommended for `research-api`: `live=true&fallback=false`.** That satisfies `docs/api-contract-v0.md` ("do not silently substitute a live provider response with a fixture"): failed sources are omitted and reported, and if **no** source was live the endpoint returns `503 {"error": {"code": "provider_unavailable", "retryable": true, "details": {"sources": [...]}}}` with nothing stored. The default (`fallback=true`) keeps an offline demo working, but then your adapter must treat `sample` records as unavailable if it asked for live data. A partial outage in strict mode is a normal `200` with the failed sources marked `unavailable`.

Fixtures are persisted like any other record (labeled), so a store that has ever seen a fallback run can hold `sample` rows next to live ones: filter on `data_mode` when reading `/evidence`. `/briefing` decides once across evidence and signals together: if any live record of either kind exists, every fixture (evidence and signal) is excluded.

Staleness is the caller's decision: compare `retrieved_at` / `published_at` to your freshness window. There is no scheduler yet, so data only refreshes when `/ingest/run` is called.

## Jev judgment (optional, off by default)

With `JEV_ENABLED=true` and `TYPESAFE_API_KEY` set (and the shared package installed: `pip install -e ../jev-tool`), each **new** `general_news` and `social_media` record gets one Jev call at ingestion and gains `details.jev`:

```json
"details": {"jev": {
  "engine": "jev", "model": "jev-1.13.0", "question_set_version": "article-v4", "request_id": "req_...",
  "relevant": 0.98, "direction": "positive", "direction_confidence": 0.91,
  "content_type": "news_report", "content_type_confidence": 0.95,
  "event_type": "earnings_or_guidance", "event_type_confidence": 0.9,
  "upcoming_event": 0.05, "sensational": 0.06, "usable_content": 0.97,
  "materiality": 1.9, "materiality_confidence": 0.8,
  "same_story_as": ["<id of another new record>"]}}
```

| Field | Meaning |
|---|---|
| `relevant` | 0 to 1: how likely the item is mainly about this company (an article about a supplier scores around 0.5 to 0.7) |
| `direction` | `negative`, `neutral`, `positive` or `mixed`: what the item reports about the company's business |
| `content_type` | `company_announcement`, `news_report`, `opinion_or_analysis`, `social_media_post`, `other` |
| `event_type` | `earnings_or_guidance`, `legal_or_regulatory`, `product_or_service`, `deal_or_partnership`, `management_or_workforce`, `operations_or_supply`, `market_or_macro`, `stock_or_valuation_view`, `other` |
| `upcoming_event` | 0 to 1: the item names a scheduled event still to come |
| `sensational` | 0 to 1: the text is written as hype, alarm or clickbait |
| `usable_content` | 0 to 1: real content, as opposed to a paywall notice, error page or cookie prompt |
| `materiality` | 0 to 2: 0 routine or promotional, 1 notable, 2 major |
| `same_story_as` | Present only when found: ids of other records **from this same run and a different outlet** that Jev judged to report the same event. A marker only; dedup and the corroboration score are unchanged |
| `filled_sentiment` | Present and `true` only when the opt-in below wrote `sentiment` |
| `*_confidence` | 0 to 1: how peaked Jev's answer was; treat low-confidence answers as unknown |

- **Additive only.** Nothing is filtered or dropped, and `sentiment`, `entities` and `credibility` are not touched. With Jev off (the default) records are byte-for-byte what they were before.
- **One opt-in exception: `JEV_FILL_SENTIMENT=true`.** Only when Bedrock is not configured at all (so the tagging agent cannot run) and Jev's direction confidence is at least 0.5, `sentiment` is filled: positive → `Bullish`, negative → `Bearish`, neutral and mixed → `Neutral`, with `score` set to Jev's confidence. A value written by the tagging agent is never overwritten. Off by default.
- **`engine` must be checked.** If Jev was enabled but did not answer, the record carries `{"engine": "unavailable", "error": "..."}` and no judgment fields. A record with no `details.jev` at all was not sent to Jev.
- **Filings are skipped.** `sec_filing` and `congressional_disclosure` records are never sent: they are parsed deterministically here, and Jev is unreliable with numbers and dates.
- **Runs just before tagging, and is judged once.** The Jev step does not read or depend on the tagging agent's output, and tagging runs on every record exactly as before. Only newly stored records are judged, so a repeat run costs nothing. A record stored while Jev was off or unavailable is not judged later.
- **Text leaves the service.** The record's `title` and `summary` are sent to TypeSafe's API. Do not enable this for sources whose terms forbid passing content to a third party.
- **Heuristic, not validated.** These are model judgments checked only on a small hand-written sample (`microservices/jev-tool/evals/`). None is a probability that a price will move.
- **The briefing sees it.** `/briefing` already passes `details` to the synthesis agent, so judged records reach it with their Jev judgment attached.

### Grade: how much weight a record deserves

When Jev is enabled every newly ingested record also gets `details.grade`, computed once at ingestion and stored with it (so it is in Postgres next to the vector):

```json
"grade": {"version": "grade-v1", "basis": "jev", "strength": 0.3712, "gated": false, "gate_reasons": [],
  "relevance_gate": 0.3,
  "factors": {"relevance": 0.99, "credibility": 0.75, "content_type": 1.0, "materiality": 0.7,
              "direction_confidence": 1.0, "hype": 1.0, "same_story": 1.0}}
```

- **`strength`** is the product of the listed factors. It is a ranking aid: compare records with it, do not read it as a rating out of 1 (several factors below 1 multiply to a small number; live news records ran from about 0.01 to 0.4). It is not a probability and says nothing about price direction.
- **`gated` / `gate_reasons`**: `off_topic` when Jev's relevance is below `JEV_RELEVANCE_GATE` (default 0.3), `unusable_content` for paywall or error pages. **Gated records are kept and labelled, never dropped.** The tagging agent still tags them; the label is how a reader knows that sentiment may not be about this symbol. In live runs the per-symbol Yahoo feed was 40 to 90 percent off-topic, and the tagging agent gave about half of those a Bullish or Bearish direction for the symbol.
- **`basis: "source_only"`**: filings, congressional disclosures and anything Jev did not answer for are graded on `credibility` alone and are never gated.
- **Factors and weights** are hand-set heuristics in `pipeline/grade.py` (content type: news 1.0, company announcement 0.8, opinion 0.6, social 0.4; materiality 0.4 to 1.0; a 0.7 penalty only when `sensational` is 0.8 or more; a small bonus per other outlet with the same story). Not fitted, not validated.
- **Freshness is not stored.** It is applied when you ask: `strength_now` halves every 72 hours from `published_at`.

Reading it:

| Call | Result |
|---|---|
| `GET /evidence?symbol=AAPL` | Unchanged. Every record, with `details.jev` and `details.grade` inside |
| `GET /evidence?symbol=AAPL&ranked=true` | Strongest first, each with `strength_now`, plus `news_tone` and `hidden_as_off_topic` |
| `GET /evidence?symbol=AAPL&relevant_only=true` | Leaves out gated records (they stay stored) |
| SQL | `(details->'grade'->>'strength')::float`, `(details->'grade'->>'gated')::boolean` |

`news_tone` is the strength-weighted direction of on-topic, Jev-judged records, with same-story records counted once: `{"label": "positive|negative|mixed_or_neutral|insufficient_data", "tone": -1..1, "stories_used", "records_gated", "by_direction", "evidence_ids"}`. It needs at least three stories. A summary of reported tone, never a forecast.

**The briefing agent sees the grade first.** Its tool rows carry `strength`, `relevance_to_symbol` and `off_topic_for_symbol` at the top level, and its prompt tells it not to treat an off-topic record's sentiment as being about the symbol. Nothing is withheld from it. Any aggregate you build over news (tone, counts, the divergence news leg) should skip gated records: `pipeline.grade.is_gated(evidence)`.

### Briefing review

With Jev enabled, `POST /briefing` also runs an advisory check of the generated text and reports it in `meta.jev_review` (it is `null` when Jev is off):

```json
"jev_review": {"engine": "jev", "model": "jev-1.13.0", "question_set_version": "explanation-v1",
  "points": [{"index": 0, "status": "checked", "supported": 0.93, "evidence_checked": 1},
             {"index": 1, "status": "not_checked", "reason": "cites no news or social records"}],
  "personal_advice": 0.03, "promises_outcome": 0.05,
  "thresholds": {"supported_below": 0.3, "flag_at_or_above": 0.5}}
```

- Only points that cite news or social records are checked. `supported` is how likely the point's text is backed by the `title` and `summary` of those records (the weakest sentence in the point). `personal_advice` and `promises_outcome` cover the whole briefing.
- Anything past a threshold is added to the response's `warnings`, prefixed `jev:`. **Nothing is edited or dropped**; the citation check above still decides what is kept.
- Points resting on filings, congressional disclosures or signals are `not_checked`: their facts are in structured `details` and numbers, which this comparison cannot see (in live runs it flagged correct filing points almost every time, so they were taken out of scope). A warning is raised only when `supported` is below 0.3.

Code: `src/scraper_analysis/pipeline/jev_judge.py`, `src/scraper_analysis/pipeline/grade.py`, `src/scraper_analysis/agents/jev_guard.py`. Caller rules for Jev: `microservices/jev-tool/AGENT_GUIDE.md`.

## Briefing

`POST /briefing` returns `{status, briefing, meta, warnings}`. `briefing` has `headline`, `overall_tone`, `points[]` (each with `theme`, `text`, `direction`, `evidence_ids`), `conflicts[]`, `data_gaps[]`, `uncertainty`. It never gives a recommendation or score. Citations are verified server-side: IDs the agent did not actually retrieve are stripped, and uncited points are dropped (reported in `warnings`). Fixture records (evidence and signals) are excluded whenever any live evidence or signal exists. Model or agent-setup failures return the `503 briefing_unavailable` envelope, never a 500. With no stored data it returns `status: "insufficient_data"` without calling the model.

## Divergence

`GET /divergence` compares the **direction** of four legs, each backed by cited records, and flags the pairs that disagree: `price` (30-day change), `insider` (discretionary Form 4 open-market P/S net; filings that are only pre-scheduled 10b5-1 trades, tax withholding, option exercises or grants do not make the leg usable and are explained in `notes`), `congress` (congressional (Senate or House) purchases vs sales; flag titles are chamber-neutral, e.g. "Members of Congress buying while insiders sell") and `news` (credibility-weighted tone of Bedrock-tagged items, needs at least 3). Response: `status` (`ok` needs 2+ usable legs, else `insufficient_data`), `legs`, `flags[]` (each with the legs involved and `evidence_ids`), `notes`, `warnings`, `excluded` (`sample`, `cached`, `stale_price`, `future_dated`, `out_of_window`, `partially_out_of_window`, `out_of_window_transactions`, `undated`, `invalid_date` counts), `window` (`request_time`, `historical`, `anchor`, `start`, `end`, `lookback_days`, `price_as_of`, `price_age_days`, ...), `thresholds`, `data_modes` (modes actually compared: `["live"]` or `[]`).

- **Live only.** Only `data_mode: "live"` records are compared. Fixtures (`sample`) and `cached` records never contribute to any leg or flag; the endpoint passes the raw stored records so every dropped record is counted in `excluded.sample` / `excluded.cached` and warned about. If only fixtures are stored the response is `insufficient_data` with a sample-only warning.
- **Request time (`as_of`).** Defaults to now. A future `as_of` (more than `CLOCK_SKEW_TOLERANCE_HOURS` = 1 after the actual clock) is rejected with 400 (`analyze()` raises `FutureAsOfError`). A past `as_of` (e.g. 2010) is allowed for back-dated analysis but is always labelled `window.historical: true` with a "Historical analysis" warning; it is never presented as current. A default request has `window.historical: false`.
- **Nothing from the future.** Any price signal or evidence dated more than `CLOCK_SKEW_TOLERANCE_HOURS` (1) after the request time is never used, whether slightly (hours) or far in the future; it is counted in `excluded.future_dated` and warned about. The window end never extends past request time + that tolerance.
- **Fresh price only.** The price leg is the latest live, not-future price signal, usable only if its `as_of` is at most `MAX_PRICE_SIGNAL_AGE_DAYS` (7) before the request time. A stale (e.g. 2010) price leaves the leg unusable, is counted in `excluded.stale_price`, is warned about, and does not anchor the window, so old data is never presented as a current flag. `window.price_as_of` / `price_age_days` make the age explicit.
- **Window = the price move's period.** With a fresh price, evidence must fall inside the price signal's own change window (its `window`, e.g. `30d`, ending at its `as_of`) plus `RECENCY_FORWARD_GRACE_DAYS` (1, since daily closes are stamped at midnight of the session date); every flag therefore compares the price move with evidence from the period that move covers. Without a fresh price the window is `RECENCY_LOOKBACK_DAYS` (30) before the request time.
- **Event dates.** The event date is `observed_at` (Form 4 / congressional trade date), falling back to `published_at` for news. Congressional records use the trade date only, never the filing date, and any record with `details.date_issue` (e.g. a House trade dated after its filing) is excluded as `invalid_date`. Congressional trades are windowed on the trade date even though they are disclosed up to 45 days later, so the congress leg is often empty; that is deliberate (no stale pairings). Multi-day Form 4s are valued only for their in-window trades: Form 4 evidence carries `details.transactions` (`[{date, code, shares, price, value_usd}]`, open-market P/S rows) and trades dated outside the window are dropped (`excluded.out_of_window_transactions`). A legacy Form 4 without that breakdown is valued at its totals only if every `details.transaction_dates` entry is inside the window; otherwise it is excluded from the insider leg (`excluded.partially_out_of_window`, with a warning) -- out-of-window trades are never valued. Out-of-window, undated and invalid-date records are not counted and are reported in `excluded` and `warnings`. The synthesis agent can call the same analysis as a tool.

This is deliberately **not** the README's social-volume z-score "squeeze engine": that needs a social feed (Reddit is blocked, X was dropped) and a history baseline we don't have, so the number would be invented precision. A flag means "these sources point different ways", never that a price will move, and it is not a score.

## Do not claim

- Credibility scores, tone, divergence flags, or the briefing as validated or predictive.
- Coverage of Bloomberg/WSJ/Reuters (excluded: no sanctioned access) or House of Representatives disclosures (not implemented).
- Reddit data: the adapter exists but Reddit blocks it (403); it is off by default.
- Commodity fundamentals (WASDE/stocks-to-use, crop yield, soil moisture): not collected.

## Secrets

Server-side only. `DATABASE_URL` must carry `sslmode=require` for any non-localhost host (enforced in `config.py`). Nothing here should reach the browser, logs, fixtures or docs. Upstream error text is sanitized before it is returned in `sources[].error`, `warnings`, or any error envelope: URL query strings and credentials, `key=value` secrets, and configured secret values are replaced with `<redacted>` (`sources/base.py: sanitize_error`).
