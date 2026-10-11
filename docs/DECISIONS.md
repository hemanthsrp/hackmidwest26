# Decisions and open questions

Keep **confirmed decisions** separate from the recommended MVP and unverified integrations. Change this file when the team actually chooses an option. `DUMP.md` remains the original context, including sponsor wording and brainstormed features.

## Recorded direction from the dump (not implementation proof)

| Area | Recorded direction | Status / caveat |
|---|---|---|
| Goal | FinTech stock research with aggregated information, historical/quant analysis and buy/hold/sell assessment | Concept, not a working or validated predictor |
| Backend | Python and Strands Agents SDK orchestration, with MCP and JEV for a narrow decision step | Local Research API and shared Jev tool exist; full Strands assessment flow is not connected |
| Frontend | Next.js/TypeScript | Proposed, not scaffolded |
| Infrastructure | Akamai Cloud deployment and potentially hosted inference; vector storage for retrieval | Akamai inference and managed PostgreSQL preflight are recorded; application deployment remains open |
| Team | Jet: backend/JEV/MCP; Cai: data/analysis; Hemanth: baseline/frontend; Allen: infra/DB | From `DUMP.md`; agent lanes are a proposal pending team confirmation |
| Prior work | `vol-surface-builder` options-data/volatility tooling | Imported into `microservices/volatility-surface-builder` with tests, CLI, notebook, methodology and standalone API; not a stock-price prediction model |

## Proposed MVP choices — require team sign-off

1. One stock-detail vertical slice, not a full portfolio management system.
2. At least one permitted attributable source plus historical/market indicators; preserve timestamps and source IDs.
3. Strands in an actually executed orchestration path. JEV/MCP integration only if the interface works; otherwise mark as incomplete, not silently equivalent.
4. A categorical research assessment with horizon and uncertainty; `insufficient_data` is valid. Treat any 0–100 score as a heuristic unless evaluated.
5. Real brokerage account connections, login, live holdings, trade execution and broad scraping deferred. Use a labeled local/demo preference profile instead.
6. Akamai deployment if feasible and approved; demonstrate actual resources used and retain a reproducible local fallback.

## Resolve before parallel implementation (Gate 0)

| Question | Decision owner / evidence needed | Current status |
|---|---|---|
| Which symbol(s), user journey and judge-facing demo are essential? | Team/Jet; agree on a short script | Open |
| Which news and market sources permit our use, storage, links and demo? | Cai + team; terms, rate limits, API availability | Open; no assumed WSJ/Bloomberg access |
| What is the v0 JSON/API schema, timestamp semantics, units, score meaning and error behavior? | Jet with Cai/Hemanth/Allen; example payload + review | Open; `ARCHITECTURE.md` contains a proposal |
| Is JEV accessible and callable through MCP; what is its input/output contract? | Jet; observed test call and policy/latency | Real Jev calls and MCP round trips recorded; full assessment integration open |
| Which model/inference backend is available through Akamai; how is auth handled? | Jet + Allen; kickoff docs, harmless test call | Endpoint preflight recorded; application adapter integration open |
| Is a vector DB necessary for the small MVP evidence set? If so which service and retention policy? | Allen + Jet; measured need, cost, setup | Open; simple retrieval is acceptable until justified |
| How will the imported option-volatility service appear in the stock-detail flow? | Hemanth + Jet + Cai; agree chart contract, provenance/freshness, and whether options data belong in the MVP | Open; standalone service works locally; no research API connection yet |
| What are the redistribution terms of the original volatility code? | Hemanth; original README states MIT but supplied checkout has no license file | Open for separate redistribution |
| Are brokerage connections legal/feasible/safe for this event? | Team; provider policy, OAuth scope, test account and user approval | Deferred from MVP, not authorized |
| What is the actual deployment target, available credit and approval to provision? | Allen + Jet; account access and spend approval | Open |
| What is the evaluation horizon and baseline for any predictive claim? | Cai + Jet; time-split data and metric | Open; no accuracy claims pending evidence |

## A1 contract proposal — pending Gate 0 review

The reviewable A1 proposal is [api-contract-v0.md](api-contract-v0.md). It is **not a recorded decision** and must not be treated as authorization to begin A2. The proposed route is `POST /v0/research-assessments`; it models `live`, `cached`, and `sample` data modes; reserves `insufficient_data` for a truthful successful response; and supplies stable examples for invalid input, unavailable providers, and stale data. It also proposes a server-side-only Akamai OpenAI-compatible inference adapter with an explicitly selected deterministic fixture adapter, while retaining the existing shared `microservices/jev-tool` boundary.

Gate 0 must still accept or revise the route and fields; supported symbols; data-provider rights; timestamp/freshness semantics; stale-data status behavior; assessment horizon/score meaning; integration of the observed Jev and Akamai capabilities; vector-storage scope; and deployment approval. The example contract values remain fixtures.

## Decision log template

Add entries only after agreement; don't rewrite prior choices silently.

```text
Date:
Decision:
Owner / participants:
Why / evidence:
Alternatives and tradeoffs:
Impact on API, tasks, demo and deployment:
Follow-up and reviewer:
```
