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
4. A categorical research assessment with horizon and uncertainty; `insufficient_data` is valid. The accepted 0–100 score semantics are recorded below; it remains a heuristic unless evaluated.
5. Real brokerage account connections, login, live holdings, trade execution and broad scraping deferred. Use a labeled local/demo preference profile instead.
6. Akamai deployment if feasible and approved; demonstrate actual resources used and retain a reproducible local fallback.

## Resolve before parallel implementation (Gate 0)

| Question | Decision owner / evidence needed | Current status |
|---|---|---|
| Which symbol(s), user journey and judge-facing demo are essential? | Team/Jet; agree on a short script | Open |
| Which news and market sources permit our use, storage, links and demo? | Cai + team; terms, rate limits, API availability | Open; no assumed WSJ/Bloomberg access |
| Is Yahoo Finance the primary market-data source for the demo, and which data/access method is permitted? | Allen + Cai + Jet; terms, rate limits, reliability, provenance/data-mode behavior | Proposed by user direction; `yfinance` provides one merged 30-day realized-price signal, but no MCP/API integration or source-rights conclusion is approved yet. Company-fundamentals retrieval stays disabled unless an explicitly approved environment sets `YAHOO_FINANCE_FUNDAMENTALS_ENABLED=true`. |
| What is the v0 JSON/API schema, timestamp semantics, units, score meaning and error behavior? | Jet with Cai/Hemanth/Allen; example payload + review | Score semantics accepted below; remaining schema, timestamp, unit, and error behavior choices remain open. |
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

Gate 0 must still accept or revise the route and fields; supported symbols; data-provider rights; timestamp/freshness semantics; stale-data status behavior; integration of the observed Jev and Akamai capabilities; vector-storage scope; and deployment approval. The example contract values remain fixtures.

## Recorded Gate 0 decision — assessment score semantics (2026-10-11)

**Decision:** Accept `assessment.score` as an optional display value for `live` and `sample_decision` responses only. It is an integer computed as `round(50 + 50 * net_direction)`, bounded to 0–100. `net_direction` is the decision-maker's hand-set weighted heuristic over usable evidence legs; **50 means neutral**, not “50% likely.” The label remains the primary conclusion.

- `assessment.score` is `null` when `assessment.label` is `insufficient_data`; fixture-only `sample` mode omits a numeric score.
- `assessment.score_sell_at_or_below` and `assessment.score_buy_at_or_above` expose the label-transition points for the current combiner rule. They are rule metadata, not calibrated confidence thresholds.
- The UI must call it **“Heuristic score”** and present it beside the categorical label, horizon, provenance/data mode, and uncertainty. It must not describe the value as a probability, forecast, expected return, validated predictor, personalized recommendation, or trade signal.
- The value may support explainability and demo comparison, but it does not independently trigger an action. Any change to the formula, weights, label thresholds, or UI wording requires a decision-record update and regression coverage.

**Owner / participants:** Jet; contract must remain consumable by Cai/Hemanth/Allen.

**Why / evidence:** PR #26 implements and tests the same 0–100 rescale in the decision maker and Research API. Recording its exact meaning prevents the frontend from treating a hand-set directional scale as confidence or performance evidence.

**Impact:** `docs/API.md`, `docs/api-contract-v0.md`, decision-maker response models, and Research API response assembly must preserve these semantics. Provider rights, live-data behavior, score evaluation/backtesting, and broader v0 contract approval remain separate Gate 0 items.


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
