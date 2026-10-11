# Four-agent task board

**Status:** Proposed, unclaimed. This is a scoped handoff board, not a record that work has started. Confirm human ownership and the MVP with the team. Each implementation task requires a branch/worktree, exact acceptance checks and an integration review under `AGENTS.md`.

## Gates and dependency order

- **Gate 0 — scope/contract (integration lead with all lanes):** choose the demo symbol(s), licensed sources, response fields, timestamps/units, error behavior, and demo fallback; record decisions in `DECISIONS.md`. Circulate one example response before A2/B2/C2/D2. No code-level assumption should be promoted to a public contract without this gate.
- **Parallel discovery:** A1, B1, C1, D1 are independent; report findings rather than build broad systems.
- **Parallel build after Gate 0:** A2, B2, C2, D2 work on separate trees and stable interfaces; adapt deployment and UI to an agreed schema.
- **Integration:** A3 wires B2 and C2; D2 smoke-tests the integrated candidate. Integration lead owns review/merge and the final demo rehearsal.

## Agent A — Strands/API/decision (Jet lane)

**A1 — Feasibility and v0 API contract** (Jet; proposal published 2026-10-10; Gate 0 approval pending)
- Verify Strands SDK version/examples, JEV availability and actual MCP interface, inference auth/latency, and backend framework choice; record source, evidence, blockers. Draft a *proposed* JSON request/response and `insufficient_data` path for Gate 0.
- **A1 handoff:** [api-contract-v0.md](api-contract-v0.md) supplies the reviewable request/success response, invalid-symbol, provider-unavailable, stale-data, and insufficient-data examples; lists unresolved Gate 0 choices; and documents the server-side Akamai OpenAI-compatible adapter plus explicit deterministic-fixture fallback. It preserves the existing shared `microservices/jev-tool`; no live credentials, deployment, provisioning, or A2 code was used.
- **Done when:** an example payload and error cases are reviewable; unverified integrations are explicitly marked, not stubbed as completed. **A1 deliverable complete; do not begin A2 until Gate 0 is confirmed.**

**A2 — Backend skeleton + orchestration** (unclaimed; after Gate 0)
- Implement a testable Python HTTP API using the approved schema; orchestrate source/quant/decision adapters via Strands where supported. Keep external tools mockable; validate inputs and classify unavailable/stale data.
- **Done when:** a real local request against fixtures returns contract-valid output; tests cover empty evidence, invalid symbol and provider failure; Strands use is demonstrated in executed code, or the blocker is documented.

**A3 — Decision/integration** (unclaimed; after A2+B2, coordinate C2)
- Wire source and quant outputs into an explainable assessment with horizon/uncertainty and evidence IDs; connect JEV/MCP only if verified, otherwise retain an explicitly labeled fallback and document unmet sponsor criteria.
- **Done when:** full API demo uses real module boundaries, handles failures, and logged examples do not leak secrets; integration smoke passes locally.

**A-J1 — Jev wording-check harness** (claimed 2026-10-10: Jet via Claude Code; branch `jet/jev-wording-check`; complete, ready for review)
- Owns: `microservices/jev-tool/evals/`, `microservices/jev-tool/src/jev_tool/evals.py`, `microservices/jev-tool/src/jev_tool/presets.py`, `microservices/jev-tool/tests/test_evals.py`, and `docs/jev-integration-research.md`. Does not touch `api-contract-v0.md`, `ARCHITECTURE.md`, `DECISIONS.md`, or any A2 code. Other agents: coordinate with Jet before editing these paths.
- Hand-labelled sample headlines in the proposed v0 evidence shape, run through the `judge_article` questions and scored against an answer key, to check question wording once Jev access exists. Independent of Gate 0; not A2 work.
- **Done when:** offline tests pass (done: 22 passed, 1 live test skipped); one real run is recorded with model, request IDs and report (done 2026-10-10: reports in `microservices/jev-tool/evals/`, summary in `jev-integration-research.md` §12). This also supplies the observed Jev call for the Gate 0 access question; `judge_article` now returns `content_type` as well (question set `article-v2`).

**A-J2 — jev-tool connection surface** (claimed 2026-10-10: Jet via Claude Code; branch `jet/jev-wording-check`; complete, ready for review)
- Owns: `microservices/jev-tool/` only. Adds `.env` loading, `jev_tool.strands_mcp.mcp_client()`, and `judge_evidence` / `judge_evidence_items` for evidence items in the v0 contract shape. See "Calling Jev from the backend" in `microservices/jev-tool/README.md`.
- **Not included, left to A2:** the backend's `DecisionAdapter` / `JevDecisionAdapter` and any fixture mode. That adapter should call this package's public interface and pass `engine: unavailable` through.
- **Done when:** offline tests pass (done: 25 passed) and the live MCP check passes with the key read from `.env` (done).

**A-J3 — Jev event-type and explanation checks** (claimed 2026-10-10: Jet via Claude Code; branch `jet/jev-event-and-explanation-checks`; complete, ready for review)
- Owns: `microservices/jev-tool/` only. `judge_article` gains `event_type` and `upcoming_event` (question set `article-v3`); new `check_explanation` function and MCP tool (question set `explanation-v1`) checks a written explanation sentence by sentence against its evidence and flags advice or promised outcomes.
- **For A2/A3:** call `check_explanation` from the backend adapter once an explanation step exists; see `microservices/jev-tool/AGENT_GUIDE.md`. Thresholds and what to do on a hit are the caller's decision.
- **Done when:** offline tests pass (done: 34 passed) and both wording checks are run against real Jev with reports saved (done; reports in `microservices/jev-tool/evals/`).

**A-J4 — Jev judgment at ingestion in `scraper-analysis`** (claimed 2026-10-10: Jet via Claude Code; branch `jet/jev-scraper-judgment`; built, **awaiting Cai's review before merge**)
- Cross-lane, additive only. New `microservices/scraper-analysis/src/scraper_analysis/pipeline/jev_judge.py` and `tests/test_jev_judge.py`. Small edits to Cai's files: `config.py` (three settings), `pipeline/ingest.py` (one optional step after tagging), `api.py` (`judge` flag), `.env.example`, `INTEGRATION.md` (new section). `jev-tool`: `JevTool` accepts an explicit `api_key`.
- With `JEV_ENABLED=true`, new news/social evidence gains `details.jev`. Off by default; tagging, credibility, dedup, storage schema and the briefing prompt are unchanged.
- Also on this branch: `same_story_as` marking; opt-in `JEV_FILL_SENTIMENT`; advisory briefing review in new `agents/jev_guard.py` (four added lines at the end of `generate_briefing` in `synthesis_agent.py`, reported in `meta.jev_review` and `warnings`). `jev-tool`: `sensational` and `usable_content` on `judge_article` (`article-v4`), new `same_story` (`same-story-v1`).
- `research-api` (Hermes's lane, additive): `decision.py` result carries Jev's full judgment, `judge_evidence` / `from_stored` reuse a judgment stored on an evidence record, and a new `JevExplanationAdapter` seam. Not wired into the route; existing fields and tests unchanged (29 passed, 22 before plus 7 new).
- Checked to merge cleanly with the open `achen/scraper-divergence`, `achen/scraper-house` and `achen/scraper-scheduler` branches as of 2026-10-10.
- **Done when:** scraper tests pass with Jev off (done: 153 passed, 132 before plus 21 new) and one real run over the fixtures returns judgments and a briefing review (done); the scraper's owner accepts the change (not done).

## Agent B — evidence and quant (Cai lane)

**B1 — Source/data feasibility** (unclaimed; independent discovery)
- Compare one permitted news source and one historical-market data source, including licensing/rate limits, fields and failure modes. Audit whether existing baseline code is useful for adapters (coordinate C1); propose normalization/dedup/timestamp rules.
- **Done when:** selected sources and restrictions are documented for Gate 0; no paywall bypass or unauthorized scraping.

**B2 — Normalized evidence + signals** (unclaimed; after Gate 0)
- Implement adapters returning agreed evidence and quant records with provenance, units and observation/retrieval times. Add deterministic fixtures, deduplication and stale/missing handling. Avoid interpreting options IV diagnostics as price predictions.
- **Done when:** unit tests cover normalization, duplication, missing dates and data modes; fixtures support at least the agreed demo symbol; no unstated live-data assumptions.

## Agent C — frontend and baseline (Hemanth lane)

**C1 — Existing baseline assessment + UX wireframe** (unclaimed; independent discovery)
- Inspect the actual `vol-surface-builder` repo with authorization and identify code worth reusing versus options-only math. Propose one stock detail flow and labeled demo states (loading, stale, sample, error, insufficient data).
- **Done when:** findings cite actual paths/tests, or lack of repo access is recorded; no claim that baseline predicts prices.

**C2 — Next.js demo slice** (unclaimed; after Gate 0)
- Build a Next.js/TypeScript view for symbol selection, dated evidence, chart/signals, assessment, uncertainty and source links. Consume the agreed API; fixture mode must be visually labeled. A preferences form is optional if time allows.
- **Done when:** a local browser smoke test exercises a successful response and an error/insufficient-data state; build/test commands and results are reported.

## Agent D — Akamai platform and verification (Allen lane)

**D1 — Infra feasibility and safe deployment plan** (claimed by Allen/D on `allen/d1-infra-feasibility`; integration owner: Jet; 2026-10-10)
- Verify Akamai account/credits, hosted inference options, deploy target and time-to-setup with Allen. Decide whether vector storage is justified by the MVP; prefer a simpler persistence/retrieval path if not. Never assume accounts or credentials are available.
- **Done when:** architecture, cost/resource assumptions, required env-var names and blockers are documented; no spend/provisioning without approval.
- **Claim scope:** `docs/AKAMAI_FEASIBILITY.md`, `docs/JET_A1_HANDOFF.md`, root `.env.example`, root `.gitignore`, and this D1 task record only. Discord claim cannot be posted because `COMMUNICATIONS.md` still has the placeholder channel ID `REPLACE_CHANNEL_ID`; the team/human must relay the claim or configure the channel before cross-agent messaging is used.

**D2 — Deployment/observability/smoke** (unclaimed; after Gate 0 and runnable app for remote smoke)
- Add minimal deployment configuration, health/logging, safe example environment names and a repeatable smoke test. Deploy only with approval; verify actual frontend/backend and Akamai use before claiming them. Local fallback remains runnable.
- **Done when:** local smoke actually runs, and remote URL/health/log evidence is provided if deployed; failures and remaining manual steps are explicit.

## Integration lead checklist

- [ ] Confirm MVP and selected demo symbol(s) with teammates.
- [ ] Freeze v0 fields, units, timestamps, error and fixture modes; update `ARCHITECTURE.md` + `DECISIONS.md`.
- [ ] Assign task IDs and separate branches/worktrees; note owners without overwriting teammates' work.
- [ ] Review each lane's handoff, tests, secrets/data exposure and schema changes before merge.
- [ ] Run backend tests, frontend build, local end-to-end smoke and (if approved) Akamai remote smoke.
- [ ] Rehearse the demo using both live and explicitly labeled fallback paths.
