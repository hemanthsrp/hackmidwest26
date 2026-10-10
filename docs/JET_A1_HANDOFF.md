# Jet handoff — A1 backend feasibility and contract checkpoint

**Purpose:** prepare the project-owned Python backend to integrate Akamai's workshop inference service without making the project depend on the untracked workshop repository. This is an A1 discovery/contract task, not authorization to deploy, provision cloud resources, or start A2 implementation before Gate 0.

## Current repository state

- `microservices/decision-maker/` is empty except for a placeholder README; there is no tracked Python package, dependency manifest, HTTP server, test suite, or deployment configuration.
- The sibling `akamai-workshop-hackmidwest/` checkout is reference-only and must not be imported, copied wholesale, added as a submodule, or staged.
- `vol-surface-builder/` is also reference-only. Its deterministic synthetic-data pattern may inform Cai/Jet's fixtures, but it is not a stock-prediction service.
- Allen prepared root `.env.example` and `.gitignore` on branch `allen/d1-infra-feasibility`. It contains variable names only; credentials stay in a local ignored `.env`.

## Akamai inference configuration

The supplied workshop uses an **OpenAI-compatible client** pointed at an Akamai-hosted workshop endpoint. For this integration:

```ini
OPENAI_BASE_URL=https://ws.akamai-workshops.com/v1
OPENAI_API_KEY=<team key stored only in local .env>
CHAT_MODEL=hackathon-chat
EMBEDDING_MODEL=hackathon-embedding
IMAGE_MODEL=hackathon-image
```

Use `OPENAI_API_KEY` as the variable name for the organizer-issued Akamai workshop **inference** key because that endpoint follows the OpenAI client configuration shape. It is not an OpenAI-hosted service and it is not the same as `LINODE_CLI_TOKEN`.

- `OPENAI_API_KEY`: backend-only key for the Akamai workshop inference endpoint.
- `LINODE_CLI_TOKEN`: a separate Akamai Cloud/Linode personal access token, needed only for approved management/provisioning automation; A1/A2 must not require it.
- The browser/frontend must never receive either credential.
- Do not place a key in a commit, test fixture, documentation, Discord, or an agent prompt.

Before a live call is represented as working, confirm the organizer-provided endpoint, aliases, quota, policy, latency, and tool/structured-output compatibility with a harmless server-side request. If the key is absent or the service fails, return/use a deterministic fixture path and label the result accordingly.

## A1 deliverables

1. Claim A1 in a Jet-owned branch/worktree and preserve Allen's D1 boundaries.
2. Record a proposed FastAPI (or another selected Python HTTP framework) choice, Strands SDK version/example evidence, JEV/MCP availability, and verified/unverified inference facts.
3. Draft one reviewable v0 request/response plus invalid-symbol, provider-unavailable, stale-data, and insufficient-data examples. Align it with `docs/ARCHITECTURE.md` before implementation.
4. Propose the Python package boundary for A2:
   - `api`: HTTP request/response validation and error mapping
   - `orchestration`: Strands flow coordinating source, quant, and decision ports
   - `adapters/inference`: project-owned OpenAI-compatible client using the five environment variables above
   - `adapters/source` and `adapters/quant`: Cai-owned normalized-record interfaces
   - `adapters/decision`: JEV/MCP only after it has been observed; deterministic fallback otherwise
   - `fixtures`: explicit `sample` records, never presented as live data
5. Send the proposed contract to Cai, Hemanth, and Allen for Gate 0 review before creating public API routes or shared types.

## Gate 0 / A2 constraints

A2 may begin only after the team freezes the response schema, demo symbol(s), timestamp/units semantics, error behavior, and sample/live labeling. When it does begin, use strict TDD:

1. Write a failing test for one contract-valid fixture request.
2. Run the test and observe the expected failure.
3. Implement only the code needed to pass it.
4. Add tests for invalid symbol, empty evidence, stale/missing data, and inference-provider failure.
5. Verify the deterministic fixture flow before attempting an authenticated inference request.

## Platform handoff from Allen

- Keep the first vertical slice free of vector storage. Use stable evidence IDs plus symbol/time filtering.
- If Gate 0 later establishes a semantic-retrieval need, the first candidate is managed PostgreSQL with pgvector. Use the same approved embedding model for documents and queries; the workshop reference uses 1,024 dimensions. Do not create a database before spend/region/retention/network/TLS approval.
- D2 deployment waits for a runnable frontend/backend, local `/health` and actual API smoke, human-approved cloud target and spend ceiling, and verified account credits.

## Expected review handoff

Report branch/commit, changed paths, exact commands/results, an example payload, inferred/observed integration facts, unresolved risks, and any contract proposal. Do not push, merge, deploy, provision, or use real credentials without the required human authorization.
