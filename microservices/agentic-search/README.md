# Agentic Search

A project-owned, fixture-first search boundary for building attributable research
context. It is not an assessment or trading-score engine.

## Tavily adapter

`TavilyNewsSearch` accepts a bounded request:

- `symbol` — 1–5 letter ticker
- `query` — required search terms
- `start_date` / `end_date` — optional inclusive-start, exclusive-end dates
- `domains` — optional approved-domain allow-list
- `max_results` — 1–10
- `mode` — `sample` (default) or `live`

Sample mode returns deterministic records from `fixtures/`. Live mode requires
server-only `TAVILY_API_KEY`; missing configuration returns an explicit
`provider_unavailable` envelope and never substitutes a fixture response.

Tavily's News API request is bounded by the adapter. Publication timestamps are
normalized and filtered locally after retrieval, so results without a usable
published date are excluded from explicit date-range requests. This is not a
claim that Tavily itself provides complete historical coverage for every range.

## Exa seam

Exa is the intended supplementary provider for a later adapter because it
supports semantic search and documented publication-date filters. Do not add an
`EXA_API_KEY` or enable a live Exa path until its source policy, retention
rights, and normalized-result contract have been reviewed. The caller-facing
result shape must remain identical to the Tavily adapter.

## Evidence and scoring guardrails

Search results provide context, not a buy/sell signal. Persist only permitted
metadata/excerpts with source URL, published/retrieved timestamps, query, and
data mode. Any eventual assessment must cite evidence IDs and preserve
uncertainty; provider relevance is not a trading-confidence score.

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
