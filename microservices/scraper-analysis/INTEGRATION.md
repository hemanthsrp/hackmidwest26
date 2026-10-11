# scraper-analysis: integration guide

For the A3 wiring in `research-api` (`adapters/source`, `adapters/quant`). This service owns evidence collection, quant signals and an optional synthesis briefing. It does **not** produce a buy/hold/sell assessment; that stays in the decision lane.

## Run it

```
cd microservices/scraper-analysis
python -m venv .venv && source .venv/Scripts/activate   # Windows git-bash; use .venv/bin/activate elsewhere
pip install -e ".[dev]"
cp .env.example .env        # fill in values; never commit .env
uvicorn scraper_analysis.api:app --port 8001 --app-dir src
```

Storage is in-memory unless `DATABASE_URL` is set (then Postgres + pgvector; run `src/scraper_analysis/storage/schema.sql` once, it is idempotent). With no live credentials every source falls back to labeled fixtures (`data_mode: "sample"`), so the service runs offline.

## Endpoints

| Route | Purpose |
|---|---|
| `POST /ingest/run?symbol=AAPL&live=true&fallback=true&tag=true` | Collect from all sources, score, dedupe, store. Returns **only newly stored** items, `signals`, a per-source `sources` report and `warnings`; a repeat run returns `evidence: []`. `live=false` forces fixtures; `fallback=false` refuses fixtures (see below); `tag=false` skips the Bedrock tagging call |
| `GET /evidence?symbol=AAPL` | Everything stored for the symbol. `status` is `ok` or `insufficient_data` |
| `GET /signals?symbol=AAPL` | Stored quant signals, same `status` convention |
| `GET /divergence?symbol=AAPL` | Where independent source types disagree (price vs discretionary insider trades vs Senate trades vs news tone). Live, recent data only; deterministic, thresholds returned in the response |
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
- **Extras beyond v0:** `source_type`, `reporting_lag_days`, `details`, `entities`, `sentiment`, `credibility`. `details` holds structured, source-specific facts (Form 4 buy/sell totals, Senate transaction type and amount range). `entities`/`sentiment` are only filled when `tag=true` and Bedrock is reachable.
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

## Briefing

`POST /briefing` returns `{status, briefing, meta, warnings}`. `briefing` has `headline`, `overall_tone`, `points[]` (each with `theme`, `text`, `direction`, `evidence_ids`), `conflicts[]`, `data_gaps[]`, `uncertainty`. It never gives a recommendation or score. Citations are verified server-side: IDs the agent did not actually retrieve are stripped, and uncited points are dropped (reported in `warnings`). Fixture records (evidence and signals) are excluded whenever any live evidence or signal exists. Model or agent-setup failures return the `503 briefing_unavailable` envelope, never a 500. With no stored data it returns `status: "insufficient_data"` without calling the model.

## Divergence

`GET /divergence` compares the **direction** of four legs, each backed by cited records, and flags the pairs that disagree: `price` (30-day change), `insider` (discretionary Form 4 open-market P/S net; filings that are only pre-scheduled 10b5-1 trades, tax withholding, option exercises or grants do not make the leg usable and are explained in `notes`), `congress` (congressional purchases vs sales) and `news` (credibility-weighted tone of Bedrock-tagged items, needs at least 3). Response: `status` (`ok` needs 2+ usable legs, else `insufficient_data`), `legs`, `flags[]` (each with the legs involved and `evidence_ids`), `notes`, `warnings`, `excluded` (`sample`, `cached`, `stale_price`, `out_of_window`, `undated`, `invalid_date` counts), `window` (`request_time`, `anchor`, `start`, `end`, `lookback_days`, `price_as_of`, `price_age_days`, ...), `thresholds`, `data_modes` (modes actually compared: `["live"]` or `[]`).

- **Live only.** Only `data_mode: "live"` records are compared. Fixtures (`sample`) and `cached` records never contribute to any leg or flag; the endpoint passes the raw stored records so every dropped record is counted in `excluded.sample` / `excluded.cached` and warned about. If only fixtures are stored the response is `insufficient_data` with a sample-only warning.
- **Fresh price only.** The price leg is the latest live price signal, usable only if its `as_of` is at most `MAX_PRICE_SIGNAL_AGE_DAYS` (7) before the request time. A stale (e.g. 2010) or future-dated price leaves the leg unusable, is counted in `excluded.stale_price`, is warned about, and does not anchor the window, so old data is never presented as a current flag. `window.price_as_of` / `price_age_days` make the age explicit.
- **Window = the price move's period.** With a fresh price, evidence must fall inside the price signal's own change window (its `window`, e.g. `30d`, ending at its `as_of`) plus `RECENCY_FORWARD_GRACE_DAYS` (1, since daily closes are stamped at midnight of the session date); every flag therefore compares the price move with evidence from the period that move covers. Without a fresh price the window is `RECENCY_LOOKBACK_DAYS` (30) before the request time.
- **Event dates.** The event date is `observed_at` (Form 4 / congressional trade date), falling back to `published_at` for news. Congressional records use the trade date only, never the filing date, and any record with `details.date_issue` (e.g. a House trade dated after its filing) is excluded as `invalid_date`. Congressional trades are windowed on the trade date even though they are disclosed up to 45 days later, so the congress leg is often empty; that is deliberate (no stale pairings). Out-of-window, undated and invalid-date records are not counted and are reported in `excluded` and `warnings`. The synthesis agent can call the same analysis as a tool.

This is deliberately **not** the README's social-volume z-score "squeeze engine": that needs a social feed (Reddit is blocked, X was dropped) and a history baseline we don't have, so the number would be invented precision. A flag means "these sources point different ways", never that a price will move, and it is not a score.

## Do not claim

- Credibility scores, tone, divergence flags, or the briefing as validated or predictive.
- Coverage of Bloomberg/WSJ/Reuters (excluded: no sanctioned access) or House of Representatives disclosures (not implemented).
- Reddit data: the adapter exists but Reddit blocks it (403); it is off by default.
- Commodity fundamentals (WASDE/stocks-to-use, crop yield, soil moisture): not collected.

## Secrets

Server-side only. `DATABASE_URL` must carry `sslmode=require` for any non-localhost host (enforced in `config.py`). Nothing here should reach the browser, logs, fixtures or docs. Upstream error text is sanitized before it is returned in `sources[].error`, `warnings`, or any error envelope: URL query strings and credentials, `key=value` secrets, and configured secret values are replaced with `<redacted>` (`sources/base.py: sanitize_error`).
