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


## Recorded decision — local NLP reader in the news leg (2026-11-16)

**Decision:** An optional local sentiment model (`decision-maker/nlp.py`, switched on by `DECISION_NLP_MODEL`, off by default) reads news that Jev did not judge, so those records can count in the news leg at `credibility x 0.35 x reading confidence`. A record is read only when its headline names the company and no other known company, and is not a market wrap-up. A reading never changes a Jev-judged record's weight; on those records it is only compared (`nlp_cross_check`). A news leg with fewer than 3 Jev-judged stories (`backs_label: false`) can move the net direction but cannot create a label: it does not count toward the two usable legs, and cannot be the evidence leg that agrees with a buy or sell. The news leg also reports `agreement`, `coverage` and `confidence`; the combiner does not read them.

**Owner / participants:** proposed and approved by Hemanth on 2026-11-16, using his project-wide override of lane approvals (the decision-maker lane is Jet's).

**Why / evidence:** With Jev off or unavailable, unjudged news is left out of the news leg entirely. On `jev-tool/evals/article_quiz.json`, `ProsusAI/finbert` behind the headline rule gave 20 usable readings on 30 on-topic items, 19 with the right direction, and none on the 8 off-topic items (Jev: 30/30). That is a 38-item sanity check, not an evaluation. On the local live store (AAPL, NVDA, TSLA, MSFT, Yahoo Finance news ingested 2026-11-16, no Jev judgments), the first version flipped three labels on NLP-only news with a news confidence of about 0.06 (AAPL hold to buy, NVDA hold to sell, TSLA `insufficient_data` to hold) and counted headlines about other companies or the whole market. The `backs_label` rule and the other-company and market-wide filters were added for that; with them all four labels match the run without the reader.

**Alternatives and tradeoffs:** Using the reading to re-weight Jev-judged records was rejected, because FinBERT was wrong on 7 items where Jev was right, so it would only have pulled correct readings down. An LLM reader (TradingAgents, FinGPT) costs a call per article and is not deterministic. FinBERT's weights are CC BY-NC-SA 4.0 (non-commercial); the model id is configurable for that reason.

**Impact:** With the variable unset, labels and scores are unchanged (the existing tests are untouched). With it set, the news leg can become usable from NLP-only stories and move the net direction and score, but a label only changes when at least two other legs (or 3 Jev-judged news stories) already back it. `meta.decision_trace.legs[news].inputs` and `meta.nlp_readings` gain fields; no response field changes.

**Follow-up:** an evaluation on more than the quiz set before enabling it by default, and a run with Jev on, which the live store run could not include (no TypeSafe key locally).

## Recorded decision — explicit stages for six flows (2026-11-17)

**Decision:** Six flows whose stages were tracked by loose flags now have one named stage each and one place that changes it.

- **Article judgment and grading:** a grade records the judgment it was built from (`judged_by`). The decision maker ignores a grade from an earlier stage, so an article judged off-topic at decision time no longer counts in the news leg because of a `source_only` grade stored while Jev was unavailable.
- **Account:** pending verification → active (`frontend/src/lib/account.ts`). The sign-up password travels on the verify link (`action_tokens.password_hash`, migration `0001`) and is applied only when that link is opened, and a reset link also activates the account.
- **Robinhood connection:** disconnected → authorizing → connected (`broker.connection_state`). Connecting and disconnecting are one transaction, and leaving `connected` clears the cached portfolio.
- **Email outbox:** pending → sending → delivered, sending → pending, and pending → cancelled (`notifications.OUTBOX_TRANSITIONS`). Turning email alerts off cancels queued email, and a claim older than 15 minutes returns to the queue. `/v1/notification-preferences` now reads and writes the same alert keys as `/v1/me/preferences` (issue #48).
- **Evidence lifecycle:** fresh → stale → archived, worked out when a record is read and only ever moving forward (`scraper_analysis/pipeline/lifecycle.py`, ported in `decision_maker.models.current_lifecycle`). A re-ingest can no longer un-archive a row.
- **Scheduler:** each symbol reports one `outcome`. This is additive; `ok`, `partial` and `error` are unchanged.

**Owner / participants:** approved by Hemanth on 2026-11-17 under his project-wide override of lane approvals (decision-maker and research-api are Jet's lane, scraper-analysis is Cai's).

**Why / evidence:** Each change has a test that shows the combination that used to be possible. Against a throwaway Postgres database, the original sign-up flow left a verified account with the first registrant's password (`attacker_password_works=true`). The original upsert turned an archived row back to `fresh` with `archived_at` cleared.

**Not changed:** `/v1`'s own freshness cutoffs (24 hours for news, 3 days for a market close) and the decision maker's `stale_after_seconds` still decide what is used; `lifecycle_status` is now accurate but those readers do not consult it. On a weekend a signal can be labelled `stale` while `/v1` still treats the close as current.

**Follow-up:** run migration `0001` before deploying the frontend; decide whether `/v1` and the decision maker should read `lifecycle_status` instead of their own cutoffs.

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
