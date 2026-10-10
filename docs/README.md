# Hack Midwest 2026 — financial research assistant

> **Status:** Planning. The repository currently contains the original [context dump](DUMP.md); the product, implementation, and deployment are not yet verified. This README describes the intended direction, not a working application.

Build an evidence-backed stock research experience that brings together permitted news sources and market data, derives quantitative signals, and presents an explainable **buy / hold / sell research assessment** with uncertainty and a stated time horizon. The intended demo includes personalized context and a stock detail view. This is decision support, **not an automated trading system or a guarantee of returns**.

The hackathon concept aims to use a Python backend orchestrated with **Strands Agents SDK**, a **Next.js/TypeScript** frontend, and **Akamai Cloud** infrastructure. JEV is proposed for a narrow classification/decision step through MCP. These integrations are targets, not verified working components. See [PROJECT_BRIEF.md](PROJECT_BRIEF.md) for MVP scope and [ARCHITECTURE.md](ARCHITECTURE.md) for proposed boundaries.

## Current state

- `DUMP.md` is the source record for the challenge, ideas, team ownership, and uncertainties.
- No application code or runnable setup is present in this repository yet. Hemanth's prior `vol-surface-builder` is described in `DUMP.md` but **has not been imported here**.
- No live data providers, Akamai resources, Strands workflow, JEV/MCP connection, or brokerage integrations have been verified here.

## For contributors and the four-agent team

1. Read [PROJECT_BRIEF.md](PROJECT_BRIEF.md), [AGENTS.md](AGENTS.md), [ARCHITECTURE.md](ARCHITECTURE.md), [TASKS.md](TASKS.md), and [DECISIONS.md](DECISIONS.md). Refer back to `DUMP.md` for the original wording.
2. Pick one unclaimed, dependency-ready task from `TASKS.md`. Follow the lane and branch/worktree boundaries in `AGENTS.md`.
3. Agree on a small API/data contract before parallel implementation. Keep external calls behind adapters and keep the demo usable with explicitly labeled sample data if feeds are unavailable.
4. Run the relevant checks you actually have. Report what you ran, what passed or failed, and what remains unverified. No task is complete based solely on an agent's claim.

## Local development

**TBD after scaffolding.** The frontend and backend commands, required environment variable *names*, test commands, and deployment URL belong here once verified. Never commit tokens, brokerage credentials, or personal account data. There is currently no verified install/run command to copy.

## Demo target

A judge chooses a stock; the app displays dated source evidence, market/quant signals, an explainable assessment (including its horizon and uncertainty), and an interactive detail view. A user preference can change the *presentation/context* of the research without silently rewriting market facts. A live Akamai-hosted path is the target; a local, labeled sample-data fallback should be ready. See the MVP/acceptance criteria in `PROJECT_BRIEF.md`.

## Project navigation

- [Original context and challenge text](DUMP.md)
- [Scope and success criteria](PROJECT_BRIEF.md)
- [System boundaries and proposed contracts](ARCHITECTURE.md)
- [Four-agent collaboration rules](AGENTS.md)
- [Prioritized work and owners](TASKS.md)
- [Decisions and unresolved questions](DECISIONS.md)
