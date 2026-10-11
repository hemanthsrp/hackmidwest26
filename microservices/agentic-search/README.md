# Agentic Search

A project-owned, fixture-first Search API boundary for attributable research
context. It is not an assessment or trading-score engine.

## Exa Search adapter

`ExaSearch` uses Exa's [Search API](https://docs.exa.ai/reference/search) with
a bounded request:

- `symbol` — 1–5 letter ticker; incorporated into the Exa query
- `query` — required search terms
- `start_date` / `end_date` — optional inclusive-start, exclusive-end dates;
  sent as Exa `startPublishedDate` / `endPublishedDate`
- `domains` — optional approved-domain allow-list; sent as `includeDomains`
- `max_results` — 1–10; sent as `numResults`
- `mode` — `sample` (default) or `live`

Sample mode returns deterministic, symbol-matched records from `fixtures/`.
Every returned result is labeled with its `data_mode`. Live mode requires the
server-only `EXA_API_KEY`; missing configuration returns an explicit
`provider_unavailable` envelope and never substitutes a fixture response.

The adapter calls `POST https://api.exa.ai/search` with the key only in the
`x-api-key` request header. It requests Exa `highlights`, not raw page text;
returned excerpts are capped at 500 characters. Provider failures collapse to
a safe error envelope, so keys, request URLs, and raw provider messages are
not returned.

## Evidence and scoring guardrails

Search results provide context, not a buy/sell signal. Persist only permitted
metadata/excerpts with source URL, published/retrieved timestamps, query, and
data mode. Any eventual assessment must cite evidence IDs and preserve
uncertainty; provider relevance is not a trading-confidence score.

The downstream scraper-analysis handoff is intentionally not part of this
package. When the contract is accepted, scraper-analysis owns ingestion,
symbol matching, strict-mode handling, ID/deduplication, credibility scoring,
and database writes. This package does not write to the evidence table.

## Storage choice

Use the existing managed PostgreSQL database for the authoritative evidence
record: identifiers, symbol, title, permitted summary, source URL, dates,
provider, query metadata, data mode, and audit fields. Use its pgvector
extension only as a secondary index for semantic ranking of already-filtered
records. Retrieval order is:

1. filter PostgreSQL by symbol, time range, source/domain, and data mode;
2. optionally rank that bounded candidate set by a `vector(1024)` embedding;
3. return evidence IDs, provenance, and distances to the agent.

Do not put raw provider responses, credentials, or an unqualified buy/sell
confidence score into the vector index.

## Local verification

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
```
