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

- **IDs are deterministic** (hash of source URL + title + transaction date): the same item keeps the same ID across runs, so `reason_codes` can reference them safely.
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

Fixtures are persisted like any other record (labeled), so a store that has ever seen a fallback run can hold `sample` rows next to live ones: filter on `data_mode` when reading `/evidence`. `/briefing` already prefers live records and ignores fixtures whenever any live record exists.

Staleness is the caller's decision: compare `retrieved_at` / `published_at` to your freshness window. There is no scheduler yet, so data only refreshes when `/ingest/run` is called.

## Briefing

`POST /briefing` returns `{status, briefing, meta, warnings}`. `briefing` has `headline`, `overall_tone`, `points[]` (each with `theme`, `text`, `direction`, `evidence_ids`), `conflicts[]`, `data_gaps[]`, `uncertainty`. It never gives a recommendation or score. Citations are verified server-side: IDs the agent did not actually retrieve are stripped, and uncited points are dropped (reported in `warnings`). Fixture records are excluded whenever any live record exists. With no stored data it returns `status: "insufficient_data"` without calling the model.

## Do not claim

- Credibility scores, tone, or the briefing as validated or predictive.
- Coverage of Bloomberg/WSJ/Reuters (excluded: no sanctioned access) or House of Representatives disclosures (not implemented).
- Reddit data: the adapter exists but Reddit blocks it (403); it is off by default.
- Commodity fundamentals (WASDE/stocks-to-use, crop yield, soil moisture): not collected.

## Secrets

Server-side only. `DATABASE_URL` must carry `sslmode=require` for any non-localhost host (enforced in `config.py`). Nothing here should reach the browser, logs, fixtures or docs.
