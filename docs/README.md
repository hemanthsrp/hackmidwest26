# Hack Midwest 2026 — financial research assistant

> **Status:** Several local backend components are implemented; the full product, frontend, and deployment are not yet verified. The MVP contract remains a proposal pending team confirmation.

Build an evidence-backed stock research experience that brings together permitted news sources and market data, derives quantitative signals, and presents an explainable **buy / hold / sell research assessment** with uncertainty and a stated time horizon. The intended demo includes personalized context and a stock detail view. This is decision support, **not an automated trading system or a guarantee of returns**.

The hackathon concept aims to use a Python backend orchestrated with **Strands Agents SDK**, a **Next.js/TypeScript** frontend, and **Akamai Cloud** infrastructure. The shared Jev Python/MCP tool and Akamai inference preflight have been exercised; the full application path is still pending. See [PROJECT_BRIEF.md](PROJECT_BRIEF.md) for MVP scope and [ARCHITECTURE.md](ARCHITECTURE.md) for system boundaries.

## Current state

- `DUMP.md` is the source record for the challenge, ideas, team ownership, and uncertainties.
- `microservices/research-api` serves a labeled local research fixture. Its Akamai inference and Jev adapters exist but are not wired into the assessment route.
- `microservices/scraper-analysis` has source adapters, normalized evidence/signals, and local fixtures. Provider rights and live behavior still need review for the agreed demo.
- Hemanth's option-volatility baseline is imported into [volatility-surface-builder](../microservices/volatility-surface-builder/README.md), with its original math/tests, notebook, methodology, chart CLI, and a standalone API. It is an options diagnostic and does not make stock assessments.
- The shared `jev-tool` has offline tests and recorded real calls. Akamai inference and PostgreSQL have been preflighted, but the frontend, full Strands workflow, and deployment remain incomplete.

## For contributors and the four-agent team

1. Read [PROJECT_BRIEF.md](PROJECT_BRIEF.md), [AGENTS.md](AGENTS.md), [ARCHITECTURE.md](ARCHITECTURE.md), [TASKS.md](TASKS.md), and [DECISIONS.md](DECISIONS.md). Refer back to `DUMP.md` for the original wording.
2. Pick one unclaimed, dependency-ready task from `TASKS.md`. Follow the lane and branch/worktree boundaries in `AGENTS.md`.
3. Agree on a small API/data contract before parallel implementation. Keep external calls behind adapters and keep the demo usable with explicitly labeled sample data if feeds are unavailable.
4. Run the relevant checks you actually have. Report what you ran, what passed or failed, and what remains unverified. No task is complete based solely on an agent's claim.

API routes and MCP tools are indexed in [API.md](API.md); update it whenever an endpoint changes.

## Local development

Each implemented service has local setup and test commands in its README. The volatility service's sample mode runs without credentials. Frontend commands and a deployment URL remain TBD. Never commit tokens, brokerage credentials, or personal account data.

## Demo target

A judge chooses a stock; the app displays dated source evidence, market/quant signals, an explainable assessment (including its horizon and uncertainty), and an interactive detail view. A user preference can change the *presentation/context* of the research without silently rewriting market facts. A live Akamai-hosted path is the target; a local, labeled sample-data fallback should be ready. See the MVP/acceptance criteria in `PROJECT_BRIEF.md`.

## Project navigation

- [Original context and challenge text](DUMP.md)
- [Scope and success criteria](PROJECT_BRIEF.md)
- [System boundaries and proposed contracts](ARCHITECTURE.md)
- [Four-agent collaboration rules](AGENTS.md)
- [Prioritized work and owners](TASKS.md)
- [Decisions and unresolved questions](DECISIONS.md)
- [Imported volatility-surface service](../microservices/volatility-surface-builder/README.md)
