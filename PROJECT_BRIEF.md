# Project brief

## Problem and audience

Investors must reconcile fragmented market information, news, and quantitative data before making decisions. Our proposed product is a **research aid** that centralizes source-backed evidence and makes an assessment understandable to a nonexpert. The primary hackathon audience is judges acting as prospective retail users; actual investor suitability, predictive value, and legal compliance are **not established**.

## Hackathon targets (from `DUMP.md`)

- **Akamai:** useful AI-powered app on Akamai Cloud that goes beyond a basic chatbot; judging includes impact, Akamai use, technical execution, and creativity.
- **Flex:** meaningful FinTech integration.
- **AWS Strands:** use the Strands Agents SDK for substantive agent/tool orchestration, not just a dependency in the manifest.
- **Team ownership:** Jet — Strands/JEV/MCP backend; Cai — source ingestion and analysis; Hemanth — existing baseline and frontend; Allen — Akamai infrastructure, observability, and vector storage. Four Hermes agents can support these lanes; human teammates retain decision and account ownership.

## Recommended hackathon MVP — proposed, awaiting team confirmation

**One reliable vertical slice beats a broad but broken financial platform.**

1. User enters or selects **one stock symbol** from a small supported set; app works with clearly labeled sample/recorded data if live APIs fail.
2. Backend combines at least one **permitted, attributable news/data source** with historical/market indicators. Each datum carries source, observed/published timestamp where available, and retrieval timestamp.
3. Strands coordinates retrieval/analysis/assessment stages; each stage has a testable interface and a graceful failure path. Use MCP/JEV in the decision path **only after** its availability, data policy, latency, and interface have been verified; otherwise report the gap rather than claim that sponsor requirement is met.
4. Detail view shows a dated evidence list, a market chart or quantitative signal, an explainable assessment with **time horizon and uncertainty**, and a traceable reason for the assessment. A 0–100 score, if used, is a labeled heuristic, **not a probability or validated prediction**.
5. Run the end-to-end demo on Akamai Cloud if credentials and time permit; capture evidence of the actual service/resources used. Keep a local reproducible fallback and don't claim Akamai hosting until verified.

**Demo script (target, not implemented):** open the app → select a symbol → inspect source-backed news and quant evidence → request an assessment → see reasons, horizon, uncertainty and source timestamps → change a preference and see how the explanation/presentation responds. Do not show a real brokerage connection unless authorized and actually tested.

## Explicitly deferred unless the core slice works

- Brokerage OAuth/account connections (Robinhood, Schwab), real holdings, and any trading/action execution.
- Login and persistent personal financial profiles. A temporary or fake preference profile is enough for a demo if labeled.
- Broad scraping of paywalled sites, social feeds, automated ingestion at scale, universal stock coverage, portfolio-level optimization, advanced RAG and vector search, and 2-/3-day volatility forecasts without suitable data/validation.
- Multiple competing recommendation models or numerical accuracy claims without out-of-sample evaluation.

## Acceptance / stop conditions

- A teammate can run the demo using documented commands and safe example config without private credentials, or the blocker is explicitly documented.
- For at least one supported symbol, the UI renders evidence, indicator(s), assessment and provenance through real frontend/backend wiring; use a deterministic sample-data fallback when a live source is down.
- No claim of prediction accuracy or calibrated confidence without time-split evaluation. No retrospective data is presented as a live forecast.
- Unit tests cover normalized records, stale/missing data, empty evidence and decision output; an end-to-end smoke test exercises the actual flow.
- Akamai and Strands claims are backed by running code and recorded verification; JEV/MCP claims similarly require an observed call, not a placeholder.

## Risks and guardrails

- **Financial:** present research context and uncertainty; do not place trades or call a categorical output personalized financial advice. Preference/risk inputs do not imply validated suitability.
- **Data:** respect source licenses, robots/terms, attribution and rate limits. WSJ/Bloomberg access is not assumed. Keep timestamps to avoid look-ahead leakage in historical evaluation.
- **Secrets and privacy:** no account tokens, real holdings, personal records or secret environment values in Git, agent prompts, or demo recordings. Obtain approval before provisioning paid resources or linking accounts.
- **Fallback honesty:** distinguish live data, cached data, synthetic fixtures and unavailable integrations in both UI and README.

## Open questions

See `DECISIONS.md` for choices that must be confirmed (data provider rights, source universe, JEV/MCP interface, vector DB need, hosting plan, brokerage policy, scoring horizon, and team sign-off).
