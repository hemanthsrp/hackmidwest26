# Agent working agreement

**Repo:** `hackmidwest` under the HackMidwest2026 project. **Read first:** `README.md`, `PROJECT_BRIEF.md`, `ARCHITECTURE.md`, `TASKS.md`, `DECISIONS.md`, and the original `DUMP.md`. This file is the portable instruction set for Hermes and other coding agents. Run agents with this repository root as their working directory so Hermes loads this `AGENTS.md` (it is not auto-discovered from arbitrary subdirectories).

## Mission and boundaries

Build a reliable, source-backed hackathon **research demo** with a Strands-driven Python backend, Next.js frontend and a verified Akamai path if available. The brief's MVP is a **proposal pending team confirmation**, not permission to expand scope. A score or buy/hold/sell label is a research heuristic unless evaluated; no live trades, investment-account connections or claims of proven accuracy by default.

Human lanes from the context dump: **Jet** owns backend orchestration/JEV/MCP, **Cai** sources and analysis, **Hemanth** baseline/frontend, **Allen** Akamai/observability/vector storage. Each teammate can use their own Discord-connected Hermes for their lane, with separate coding/subagents that need not be in Discord. This describes the intended workflow, not a claim that all four bots are configured or online. Agents do not replace human approval or imply the humans have accepted this plan.

## Four-agent topology

| Agent lane | Human counterpart | Owns | Initial task IDs | Must not change without coordination |
|---|---|---|---|---|
| A — orchestration/API | Jet | Python API, Strands flow, decision/MCP adapter, validation | A1, A2, A3 | B's ingestion modules, C's UI, D's infra configs |
| B — evidence/quant | Cai | licensed source adapter(s), normalized evidence, dated market indicators and tests | B1, B2 | API routing/orchestration, frontend, cloud resources |
| C — product/UI | Hemanth | baseline audit/import recommendation, Next.js screens, demo states, frontend tests | C1, C2 | backend internals, live data-provider credentials, deployment |
| D — platform/QA | Allen | Akamai investigation/deployment, safe environment template, health/logging, smoke checks | D1, D2 | product/API semantics, source scraping, financial assessment logic |

Jet (or a designated integration lead) coordinates the contract checkpoint and merges. Each member's Hermes is accountable for its own private subagents. If actual teammates choose different boundaries, record that in `DECISIONS.md` and update `TASKS.md` before dispatch.

## Discord coordination between members' Hermes agents

- Use the team's agreed Hack Midwest Discord coordination channel for **short, attributed task messages**. Each member's Hermes posts on behalf of its lane; private coding agents report to that Hermes, which verifies and relays material updates. Do not assume a private subagent can read Discord or that Discord messages are automatically injected into another agent's context. Confirm the bots are invited, permitted to post/read the chosen channel, and authorized by their owners before relying on this workflow.
- **Before coding:** post `CLAIM <task ID> | <member/lane> | <branch/worktree> | <files or interfaces touched> | <expected handoff>`. Check recent claims and `TASKS.md`; if ownership overlaps, stop and coordinate *before* either agent edits. The member's Hermes records the claim in `TASKS.md` or the agreed shared task board, since Discord alone is not a lock.
- **During work:** post only meaningful `UPDATE` or `BLOCKED` messages with task ID, changed paths and concrete blocker. For a schema/API change, post `CONTRACT PROPOSAL` with affected lanes and wait for their explicit acknowledgement; record the accepted decision in `ARCHITECTURE.md`/`DECISIONS.md` before proceeding. Do not let bots recursively respond to each other's routine status posts.
- **At handoff:** post `READY FOR REVIEW <task ID> | branch/commit | changed paths | tests actually run/results | contract changes | remaining risks`. The integrator checks the diff and runs integration tests, then posts `VERIFIED` or `CHANGES NEEDED` with evidence. `DONE` means integrated and verified, not merely that a worker stopped.
- Keep messages concise; link to code/docs for detail. Never post secrets, account data, raw financial records, or long logs. Identify the sending bot/member and task ID so four similar agents cannot be mistaken for one another. If an agent cannot see the shared channel or its bot cannot send, its human or coordinating Hermes relays the same structured handoff; do not claim cross-agent communication succeeded without a visible message.
- Discord is the **coordination bus**, not the source of truth or a concurrency lock. The repo's `TASKS.md`, contract, decisions and separate branches/worktrees govern actual ownership. No auto-polling, autonomous bot-to-bot conversation, status relay, or multi-bot access is assumed until configured and tested.

## Parallel execution protocol

1. **Gate 0:** Confirm MVP, permitted data sources, task ownership, and a small v0 API/data contract from `ARCHITECTURE.md`. A1/B1/C1/D1 can investigate independently; A2/B2/C2/D2 depend on the shared contract or discoveries as noted in `TASKS.md`.
2. Claim exactly one dependency-ready task from `TASKS.md` with a branch name and integration owner; announce the claim in Discord and persist it in the shared task record before editing. Use **separate Git worktrees/branches** for concurrent coding agents; never share one working tree for overlapping edits. The integrator owns cross-lane docs/schema and integrates changes.
3. Before writing across another lane's surface, propose the change with the affected interface, rationale, and migration/test plan. Do not silently modify shared types, routes, or fixtures. Avoid two agents editing the same file.
4. Produce a handoff: task ID, changed paths, example payload or UI screenshot when relevant, tests run and exact result, unresolved risks, and branch/commit reference if one exists. The member's Hermes relays it to Discord for other lanes and the integrator. Do not invent test output or claim remote deployment without a URL and smoke result.
5. The integrator reviews diff and dependencies, runs targeted tests plus an end-to-end demo check, then decides whether to merge. **Routine task coordination posts in the approved Discord channel are permitted for each member's authorized Hermes.** Agents may not push, merge, deploy, provision paid resources, publish elsewhere, or contact third parties outside that workflow without Jet's authorization. Preserve a recovery path for destructive changes.

### Ready-to-use dispatch prompt

> Work on task `<ID>` in your own branch/worktree of this repository. Read `AGENTS.md`, `PROJECT_BRIEF.md`, `ARCHITECTURE.md`, `TASKS.md`, `DECISIONS.md`, and the relevant parts of `DUMP.md`. Stay within your lane's files; ask the integration lead before changing shared contracts. Implement the task's acceptance criteria, use deterministic fixtures for unconfigured services, run real checks, and return changed paths, command/results, blockers, and any contract proposal to your member's Hermes for the Discord handoff. Do not push, deploy, spend credits, or use real account data.

## Safety and correctness

- **Source rights:** obey provider terms, robots/rate limits and attribution; do not scrape paywalls or assume WSJ/Bloomberg access. Distinguish sample, cached and live data.
- **Finance:** never execute trades. Do not call a numerical score a probability or imply a backtested edge without validation. Surface insufficient data, horizon, freshness and uncertainty.
- **Secrets/privacy:** don't commit `.env`, access tokens, financial account data, identifiable user records, or provider credentials. No private bank/employer information in this repo or third-party AI tools.
- **Availability:** Jev has recorded real calls; Akamai inference and managed PostgreSQL have recorded preflight checks. Their use by the complete application, brokerage MCP, and remote deployment remain unverified. Use adapters, explicit feature flags and graceful fallbacks; don't silently replace a sponsor integration with a mock and claim it was implemented.
- **Options analytics:** the imported volatility-surface service is for option-IV diagnostics. Keep its `sample` and `live` modes explicit; do not turn its skew or SVI outputs into a stock-price forecast or assessment label without a separate reviewed method.
- **Jev:** before adding any Jev call, read [`microservices/jev-tool/AGENT_GUIDE.md`](../microservices/jev-tool/AGENT_GUIDE.md). All Jev calls go through the shared `jev_tool` package; do not call the TypeSafe API or SDK from another service.
- **Testing:** add tests for logic you introduce; report exact commands and outcomes. Update `README.md` with verified run commands once code exists. Failure and unsupported paths matter as much as the happy path.

## Definition of done for any task

Acceptance criteria in `TASKS.md` pass; changed files stay within agreed ownership or are reviewed; docs and example environment names are accurate; tests/smoke steps are actually run and reported; remaining unknowns are recorded. No implementation task is marked done by prose alone.
