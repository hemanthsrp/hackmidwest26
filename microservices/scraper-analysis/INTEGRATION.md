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
| `GET /divergence?symbol=AAPL` | Where independent source types disagree (price vs discretionary insider trades vs congressional (Senate and House) trades vs news tone). Live, recent data only; deterministic, thresholds returned in the response |
| `POST /briefing?symbol=AAPL` | Cited research briefing from stored data (one Bedrock call, hence POST) |
| `GET /scheduler/status` | Whether the background scheduler is on, its interval, and each symbol's last run (new items, per-source status, error) |
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

- **IDs are deterministic**: the same item keeps the same ID across runs, so `reason_codes` can reference them safely. SEC filings hash the filing URL only (one row per accession number), so Form 4 enrichment, which rewrites the title and moves `observed_at` to the trade date, never mints a second ID; a stored copy is replaced only by a strictly better one (live beats sample, then parsed Form 4 details beat metadata-only), so a persisted fixture never blocks its live filing and a later fixture or metadata-only copy never downgrades it. Other records hash source URL + title + observed date; House PTR rows also hash `details.owner`, `details.asset_name` and `details.filing_row` (the Nth identical row in that PDF), so same-day Self/Spouse/Joint rows or repeated lots in one filing keep separate IDs (Senate IDs are unchanged). Stores populated before this rule: run `python -m scraper_analysis.storage.migrations` (dry run), then `--apply`, to re-key old SEC rows and delete their duplicates; it is idempotent.
- **Form 4 dates:** `observed_at` is the earliest actual `transactionDate` in the filing, not `periodOfReport`. `details.transaction_dates` lists every trade date (the title shows the range when there are several) and `details.period_of_report` keeps the filing's reporting period.
- **Three timestamps, never invented:** `published_at` (filing/article time), `observed_at` (when the underlying event happened, e.g. the trade date), `retrieved_at` (when we fetched it). Either of the first two can be `null` if the source doesn't give it.
- **Extras beyond v0:** `source_type`, `reporting_lag_days`, `details`, `entities`, `sentiment`, `credibility`. `details` holds structured, source-specific facts (Form 4 buy/sell totals, Senate transaction type and amount range). `entities`/`sentiment` are only filled when `tag=true` and Bedrock is reachable.
- **`source_type`** is one of `sec_filing`, `congressional_disclosure`, `general_news`, `social_media`. Congressional records come from both chambers: `details.chamber` is `Senate` or `House` (titles start `Sen.` / `Rep.`), with the same `transaction_type` values (`Purchase`, `Sale (Full)`, `Sale (Partial)`, `Exchange`). A House row whose reported trade date is unparseable, in the future, after the filing date, or after its notification date has `observed_at`, `reporting_lag_days` and `details.timing` all `null`, with the reason in `details.date_issue` (`unparseable` / `future` / `after_filing` / `after_notification`) and the raw text in `details.transaction_date_reported`; its title ends `-- invalid trade date, not dated`, and the briefing agent's evidence tools mark congressional rows with `date_valid` / `direction_usable` (false for these), so it never counts as dated buying or selling anywhere; a negative lag never gets a timing class for either chamber.
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
| `live` | the real source answered. If `error` is also set, the answer was partial (e.g. `house_clerk`: `partial: 3 of 30 House PTR filings skipped (2 no text layer, 1 download failed)`); the records are real but coverage is incomplete, and the source is also listed in `warnings`. It still counts as live for strict mode |
| `sample` | fixtures, because you passed `live=false` |
| `fallback` | the live source failed and its fixture was substituted (records are `data_mode: "sample"`); also listed in `warnings` |
| `unavailable` | the live source failed and you passed `fallback=false`; nothing was substituted |

**Recommended for `research-api`: `live=true&fallback=false`.** That satisfies `docs/api-contract-v0.md` ("do not silently substitute a live provider response with a fixture"): failed sources are omitted and reported, and if **no** source was live the endpoint returns `503 {"error": {"code": "provider_unavailable", "retryable": true, "details": {"sources": [...]}}}` with nothing stored. The default (`fallback=true`) keeps an offline demo working, but then your adapter must treat `sample` records as unavailable if it asked for live data. A partial outage in strict mode is a normal `200` with the failed sources marked `unavailable`.

Fixtures are persisted like any other record (labeled), so a store that has ever seen a fallback run can hold `sample` rows next to live ones: filter on `data_mode` when reading `/evidence`. `/briefing` decides once across evidence and signals together: if any live record of either kind exists, every fixture (evidence and signal) is excluded.

Staleness is the caller's decision: compare `retrieved_at` / `published_at` to your freshness window. Data refreshes when `/ingest/run` is called or, if enabled, when the optional scheduler runs (see below).

## Briefing

`POST /briefing` returns `{status, briefing, meta, warnings}`. `briefing` has `headline`, `overall_tone`, `points[]` (each with `theme`, `text`, `direction`, `evidence_ids`), `conflicts[]`, `data_gaps[]`, `uncertainty`. It never gives a recommendation or score. Citations are verified server-side: IDs the agent did not actually retrieve are stripped, and uncited points are dropped (reported in `warnings`). Fixture records (evidence and signals) are excluded whenever any live evidence or signal exists. Model or agent-setup failures return the `503 briefing_unavailable` envelope, never a 500. With no stored data it returns `status: "insufficient_data"` without calling the model.

## Scheduler

Optional background ingestion so data refreshes without calling `/ingest/run`. **Off by default**; enable with `ENABLE_SCHEDULER=true` plus `SCHEDULER_SYMBOLS` (comma-separated), `SCHEDULER_INTERVAL_MINUTES`, `SCHEDULER_OFFHOURS_FACTOR` (interval multiplier on weekends and outside 08:00-18:00 New York) and `SCHEDULER_TAG`. It writes to whatever `DATABASE_URL` points at, so on the shared cluster enable it deliberately and only after the SEC re-key migration (`python -m scraper_analysis.storage.migrations --apply`) has been run; before that, any live ingest re-inserts SEC filings under their new IDs.

- **Strict:** live data only, fixtures are never substituted or persisted; a failed source is omitted and reported in `/scheduler/status`. One symbol failing never stops the others, and stored errors are sanitized.
- **Config validation:** interval and off-hours factor must be finite numbers greater than 0; `nan`, `inf`, `0` or negatives fail settings validation at startup. Positive values below the floors are clamped (interval to 5 minutes, factor to 1).
- **Symbols** are trimmed, upper-cased, validated and de-duplicated in order (`aapl, AAPL , Aapl` runs once as `AAPL`); invalid entries are skipped and listed under `skipped_invalid_symbols`.
- **Single owner, enforced across processes when `DATABASE_URL` is set.** On start the scheduler takes a Postgres session-level advisory lock (`pg_try_advisory_lock`, fixed project key `SCHEDULER_ADVISORY_LOCK_KEY`) on a dedicated connection held for its lifetime; any other uvicorn worker or replica with `ENABLE_SCHEDULER=true` fails to get it, stays idle and reports `start_error` ("another process already owns the scheduler") in `/scheduler/status`. The lock is released on shutdown, or by Postgres automatically if the owning process dies. If the lock cannot be taken (e.g. the database is unreachable) the scheduler does not start and says why (sanitized). Within a process only one scheduler can run, and a process-wide guard means two scheduled ingests never overlap. **Without `DATABASE_URL`** (in-memory store) only the in-process guard applies: each process has its own private store, so it is single-process only. Manual `/ingest/run` calls are not serialized against scheduled runs.
- **Shutdown:** each start gets its own cancellation token; shutdown sets it (a later restart never clears it) and ingestion checks it immediately before every database write, then waits up to 30 s for the in-flight ingest to finish. If that wait times out, the scheduler keeps ownership (in-process and the advisory lock) until the stuck ingest thread actually exits, so neither a restart nor another process can start meanwhile (`start_error` says the previous run is still draining; `/scheduler/status` shows `draining: true`). After shutdown returns, no new write starts; the only write that can still land is one that had already passed its last stop check. An interrupted symbol shows `ok: false` with a shutdown error, and the run counts under `runs_interrupted`, not `runs_completed`.

## Divergence

`GET /divergence` compares the **direction** of four legs, each backed by cited records, and flags the pairs that disagree: `price` (30-day change), `insider` (discretionary Form 4 open-market P/S net; filings that are only pre-scheduled 10b5-1 trades, tax withholding, option exercises or grants do not make the leg usable and are explained in `notes`), `congress` (congressional purchases vs sales) and `news` (credibility-weighted tone of Bedrock-tagged items, needs at least 3). Response: `status` (`ok` needs 2+ usable legs, else `insufficient_data`), `legs`, `flags[]` (each with the legs involved and `evidence_ids`), `notes`, `warnings`, `excluded` (`sample`, `cached`, `stale_price`, `out_of_window`, `undated`, `invalid_date` counts), `window` (`request_time`, `anchor`, `start`, `end`, `lookback_days`, `price_as_of`, `price_age_days`, ...), `thresholds`, `data_modes` (modes actually compared: `["live"]` or `[]`).

- **Live only.** Only `data_mode: "live"` records are compared. Fixtures (`sample`) and `cached` records never contribute to any leg or flag; the endpoint passes the raw stored records so every dropped record is counted in `excluded.sample` / `excluded.cached` and warned about. If only fixtures are stored the response is `insufficient_data` with a sample-only warning.
- **Fresh price only.** The price leg is the latest live price signal, usable only if its `as_of` is at most `MAX_PRICE_SIGNAL_AGE_DAYS` (7) before the request time. A stale (e.g. 2010) or future-dated price leaves the leg unusable, is counted in `excluded.stale_price`, is warned about, and does not anchor the window, so old data is never presented as a current flag. `window.price_as_of` / `price_age_days` make the age explicit.
- **Window = the price move's period.** With a fresh price, evidence must fall inside the price signal's own change window (its `window`, e.g. `30d`, ending at its `as_of`) plus `RECENCY_FORWARD_GRACE_DAYS` (1, since daily closes are stamped at midnight of the session date); every flag therefore compares the price move with evidence from the period that move covers. Without a fresh price the window is `RECENCY_LOOKBACK_DAYS` (30) before the request time.
- **Event dates.** The event date is `observed_at` (Form 4 / congressional trade date), falling back to `published_at` for news. Congressional records use the trade date only, never the filing date, and any record with `details.date_issue` (e.g. a House trade dated after its filing) is excluded as `invalid_date`. Congressional trades are windowed on the trade date even though they are disclosed up to 45 days later, so the congress leg is often empty; that is deliberate (no stale pairings). Out-of-window, undated and invalid-date records are not counted and are reported in `excluded` and `warnings`. The synthesis agent can call the same analysis as a tool.

This is deliberately **not** the README's social-volume z-score "squeeze engine": that needs a social feed (Reddit is blocked, X was dropped) and a history baseline we don't have, so the number would be invented precision. A flag means "these sources point different ways", never that a price will move, and it is not a score.

## Do not claim

- Credibility scores, tone, divergence flags, or the briefing as validated or predictive.
- Coverage of Bloomberg/WSJ/Reuters (excluded: no sanctioned access).
- Complete House coverage: scanned/paper PTRs have no text layer and are skipped (no OCR), assets without a ticker (bonds, funds, LLCs) are ignored, and only the newest 30 filings in a 45-day window are read. Treat House trades as a best-effort sample, not a full ledger. Lines starting with a PTR field marker (`F S:`, `S O:`, `D:`, `C:`, `L:`) are never parsed as trades, and neither are the unmarked lines a field block wraps onto. Live PDFs are parsed from pdfplumber word positions: a trade-shaped line is a row only if its type / trade date / notification date / amount tokens sit under the form's column headers (within 8pt); description or comment prose that copies a whole row, even with `(AAPL) [ST]`, flows across the line instead and is skipped. (Indentation is no help: on real PTRs, field blocks, their wrapped lines and Self-owned asset rows all start at the asset column.) Plain text without positions (tests, or a PDF whose header row is not found) uses stricter rules: after a marker a row needs the asset-type code (`[ST]`, `[OP]`, `[GS]`, ...), and after a `D:`/`C:` block also an owner code (`SP`/`DC`/`JT`), so a Self-owned row right after a description is skipped there (under-count, never a fabricated trade). A ticker/asset-type printed after the amount on the row's own line (`... $1,001 - $15,000 (AAPL) [ST]`) is read too. Filings skipped for no text layer, an unreadable PDF or a failed download are counted in that run's `sources[].error` note (see `live` above).
- Reddit data: the adapter exists but Reddit blocks it (403); it is off by default.
- Commodity fundamentals (WASDE/stocks-to-use, crop yield, soil moisture): not collected.

## Secrets

Server-side only. `DATABASE_URL` must carry `sslmode=require` for any non-localhost host (enforced in `config.py`). Nothing here should reach the browser, logs, fixtures or docs. Upstream error text is sanitized before it is returned in `sources[].error`, `warnings`, or any error envelope: URL query strings and credentials, `key=value` secrets, and configured secret values are replaced with `<redacted>` (`sources/base.py: sanitize_error`).
