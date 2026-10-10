# Akamai feasibility — D1 (Allen lane)

**Status:** managed PostgreSQL preflight and provisioning are verified; application deployment remains blocked pending Gate 0, a runnable frontend, and a chosen compute target. The supplied Akamai workshop identifies a candidate shared inference endpoint, but this team has not made an authenticated inference call or deployed an application.

## Scope and decision

The MVP has a small, deterministic evidence set. One managed PostgreSQL database was provisioned after explicit human approval for the vector-storage path; do not provision further LKE, GPU, object-storage, DNS, or inference resources until their specific need, cost, and deployment plan are approved.

**Recommendation for Gate 0:** keep source/evidence retrieval in the backend's deterministic fixture path for the first vertical slice. The already-provisioned vector database must not be integrated unless the agreed source corpus requires semantic retrieval that a bounded, structured in-process store cannot support. This avoids coupling the core API/UI flow to an as-yet-unapproved embedding model, ingestion pipeline, and retention policy.

If the team later approves deployment, use a single regional Akamai Cloud compute target for the API and serve the static frontend from the same application boundary or another explicitly selected service. Treat Kubernetes/App Platform as a later option, not the default for the hackathon MVP: Akamai documents App Platform as integrated with LKE, which adds cluster setup and operations beyond the first-slice need.

## Verified local discovery

Checked 2026-10-10 in the Allen D1 worktree:

- No environment variable name containing `AKAMAI`, `LINODE`, `OPENAI`, or `INFERENCE` was present.
- Neither `linode-cli` nor `akamai` was installed.
- The tracked project repository has no runnable application code, deployment configuration, or safe environment template yet. The two newly added untracked reference repositories are excluded from this branch and are not project deliverables.
- At that time, account identity, credit balance, enabled regions/services, this team's inference-key availability, deployment target, and end-to-end setup time were **unverified**. The managed-database facts that have since been verified are recorded below; hosted inference and application-deployment facts remain unverified.

## Verified managed database outcome

On 2026-10-10, the authorized account was confirmed active with Managed Databases capability and a $300 hackathon promotion available through 2027-01-01. The following approved resource is now active:

- Label: `hackmidwest-vector-db`
- Region: `us-ord` (Chicago); region status `ok` with Managed Databases capability
- Plan: one-node `g6-nanode-1`, priced at $0.024/hour and $16/month
- Engine: PostgreSQL 17.11; TLS required and a single-host `/32` allow list configured
- Verification: the generated local-only `DATABASE_URL` connected with TLS, and `CREATE EXTENSION IF NOT EXISTS vector` succeeded with pgvector 0.8.6

The connection URL and generated credentials are stored only in the Allen D2 worktree's ignored `.env`; they are not recorded here. The database is ready for project-owned tables after Cai and Jet agree the evidence schema, retention/deletion policy, and embedding model/dimension. It currently permits only the developer address; a deployed workload needs its own approved allow-list or private-network path before it can connect.

## Verified hosted inference outcome

On 2026-10-10, a server-side, credential-redacted probe of the configured Akamai OpenAI-compatible endpoint succeeded:

- `GET /models` returned HTTP 200 with three models; the configured chat and embedding aliases were both present.
- A bounded chat-completions request returned HTTP 200 with a response choice.
- A one-sentence embeddings request returned HTTP 200 with a 1,024-dimension vector, matching the managed pgvector candidate schema.

This verifies endpoint reachability, authorization, the current model aliases, and the expected embedding dimension. It does not establish production quota, latency guarantees, structured-output behavior, or a deployed application integration. Jet must still keep inference server-side, use bounded retry/error handling, and retain the explicit fixture/unavailable behavior until those application paths are implemented and tested.

## Platform findings and sources

- [Akamai App Platform](https://techdocs.akamai.com/cloud-computing/docs/application-platform) is documented as a ready-to-run Kubernetes platform integrated with LKE. It is viable only if an LKE cluster is explicitly approved and already justified.
- [Akamai billing information](https://techdocs.akamai.com/cloud-computing/docs/access-billing-information) and the [billing FAQ](https://techdocs.akamai.com/cloud-computing/docs/billing-faqs) say balance and promotional credits are viewed in Cloud Manager's Billing area. Allen must inspect that UI while authenticated; a repository or local shell cannot establish the available $300 credit amount.
- [GPU compute instances](https://techdocs.akamai.com/cloud-computing/docs/gpu-compute-instances) are an infrastructure option for self-hosted inference, not evidence that a hosted inference endpoint, model, quota, or API contract is available to this team.
- [Managed Databases](https://techdocs.akamai.com/cloud-computing/docs/aiven-database-clusters) and [Object Storage](https://techdocs.akamai.com/cloud-computing/docs/object-storage) are optional storage products. They are not a demonstrated vector-search solution in this repository; use neither for the initial bounded fixture corpus.

## Supplied-workshop integration evidence

The untracked `akamai-workshop-hackmidwest` folder was inspected as reference only; it is **not** staged, committed, copied into this worktree, or represented as our application. Its supplied materials establish the following candidate path for the team to verify:

- The workshop's `.env.example` and `docs/inference.md` specify an OpenAI-compatible shared endpoint at `https://ws.akamai-workshops.com/v1`, a team-supplied `OPENAI_API_KEY`, and aliases `hackathon-chat` and `hackathon-embedding`.
- Its inference reference describes chat completions, text embeddings, and image generation. The proposed finance MVP needs only backend chat/tool orchestration and optionally embeddings; it should not send keys to the browser or depend on images.
- The workshop states that one shared team key has a combined quota, including 60 requests/minute. Jet's orchestration must use bounded retries for `429`, validate structured outputs, and retain a deterministic no-key fallback. An observed call against the team's key is still required before marking inference as available.
- Its `docs/03_body.md` supplies a deployment pattern: one `g6-standard-1` Linode, Cloud Firewall, Docker Compose, application container, private Valkey container, and a `/health` wait. The same guide labels this a 15–20 minute path plus provisioning delays and says it exposes unauthenticated HTTP on port 8000; it is suitable only for the approved hackathon demo and must not carry private data.
- The workshop's cost guide lists the first deployment's resource families and requires checking Cloud Manager, promotion balance, current plan pricing, region, and cleanup. Its resource labels/scripts are workshop-specific, so D2 must not run or adapt them blindly against the Hack Midwest project account.

The separate untracked `vol-surface-builder` folder confirms a reusable module boundary, not a prediction model: `src/data_feed.py` exposes live `yfinance` or deterministic synthetic option-chain data, and `main.py` generates volatility charts. Cai/Jet may adapt its provenance-aware offline data pattern after Gate 0, but no implied-volatility output may be presented as a buy/sell forecast.

### Recommended repository boundary

Do **not** make the project application depend on the sibling `akamai-workshop-hackmidwest` checkout at runtime, import its package by relative path, or commit the workshop as a nested repository/submodule. That would make reproducible builds depend on an untracked local directory and couple this project to workshop-specific chat UI, labels, scripts, and resource assumptions.

Instead, implement a small project-owned inference adapter in the backend once Jet freezes the API contract. It should read only `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `CHAT_MODEL`, `EMBEDDING_MODEL`, and `IMAGE_MODEL` from the environment; expose separately testable chat/structured-output and embedding operations; keep the API key server-side; and provide deterministic fixture behavior when credentials or the service are unavailable. Borrow the workshop's OpenAI-compatible request shape and deployment lessons, not its application tree.

Commit the project-owned adapter, tests, Docker/deployment manifests, `.env.example`, and documentation. Keep only actual secret-bearing files ignored: `.env`, `.env.local`, deployment credentials, private keys, and generated kubeconfigs. Do not ignore production source files or hide an entire integration directory.

## Cost and resource assumptions

No price, quota, or credit balance is assumed. Akamai bills many services hourly up to monthly caps; check the authenticated Cloud Manager billing page and current product pricing before any approval.

| Phase | Approved resource posture | Cost posture | Exit criterion |
|---|---|---|---|
| D1 / local vertical slice | Local backend/frontend plus deterministic fixtures; no cloud resource | No Akamai spend | API/UI contract and local smoke exist |
| First remote smoke (only after approval) | One minimal, explicitly selected compute/deployment target; no GPU, LKE, managed DB, object storage, or vector DB by default | Confirm region availability, hourly/monthly rate, current credit balance, and spend ceiling before creation | A URL, health result, and frontend-to-backend smoke result are recorded |
| Retrieval expansion (only if measured need) | Choose a store after corpus size, query behavior, retention, and deletion needs are documented | Price storage, transfer, operations, and embeddings separately | Structured lookup cannot satisfy agreed retrieval cases |
| Self-hosted inference (not MVP default) | GPU compute only after model, image, capacity, latency, security, and budget review | Treat GPU/runtime/image transfer as separately approved spend | Observed inference call and repeatable smoke test exist |

## Review the candidate deployment without deploying it

The workshop is a reference implementation, not the project deployment. Review its implementation in this order:

1. `akamai-workshop-hackmidwest/.env.example` shows the configuration boundary and confirms that the inference key remains outside source control.
2. `agent/server.py` demonstrates the minimum HTTP surface: `GET /health` reports component status, while a real request path proves inference. A `200` health response alone is not a model-path verification.
3. `Dockerfile` and `compose.yaml` show one application container on port 8000 plus a Valkey service with no published host port.
4. `scripts/deploy_linode.sh` shows the deployment sequence: create/reuse a Cloud Firewall and Linode, wait for cloud-init/SSH, copy the application and local `.env`, run Docker Compose, then wait for `/health`.
5. `docs/03_body.md` identifies the review risks: it exposes port 8000 over unauthenticated HTTP for a workshop demo. A project deployment must constrain the firewall and add the team's approved browser/API security posture before using non-fictional data.
6. `docs/costs.md` and `scripts/down.sh` define the pre-provisioning cost/cleanup review. Review every resource label and ID before cleanup; workshop labels must not be used as project ownership proof.

No project deployment configuration has been copied from the workshop. D2 can reuse the verified pattern only after the project has a runnable API/UI and the human approval in the readiness checklist.

## Vector retrieval integration decision

**Initial MVP:** use deterministic fixture evidence indexed by stable evidence ID, symbol, and timestamp. This satisfies the small vertical slice without an embedding call, retrieval service, additional persistence, or a semantic-search claim.

**If Gate 0 demonstrates a retrieval need:** select managed PostgreSQL with the `pgvector` extension as the first candidate, following the workshop's `docs/02_memory.md`. Its supplied embedding model produces 1,024-dimensional vectors, so document and query vectors must use the same approved model and an explicit `vector(1024)` schema. Do not reuse the workshop's database, schema, labels, credentials, or allow-list settings.

The approved project boundary should be:

```text
Cai normalized evidence -> persist provenance + text chunk + embedding version
Jet orchestration -> retrieve by symbol/time first; semantic search only when requested
PostgreSQL/pgvector -> returns evidence IDs and distances, never an investment label
Assessment -> cites retrieved evidence IDs and preserves data_mode/freshness
```

Before provisioning the database, the team must approve: region; current plan/credit spend; retention/deletion policy; a dedicated least-privilege user; TLS certificate validation; explicit database-network allow list; backup/restore plan; corpus size and query evaluation; and re-embedding behavior when the embedding model changes. The product must return `insufficient_data` if retrieval is unavailable rather than silently using stale or invented evidence.

## Safe configuration contract for D2

These are names only; do not create or commit a real `.env` value. The names are safe for the future backend/frontend work, but their consumption must wait for the agreed routes and runtime.

The root `.env.example` is now a safe setup template. Copy it locally with `cp .env.example .env`, then place the organizer-provided team key only in `.env`. Root `.gitignore` excludes `.env` and all `.env.*` files except the tracked template. Do not place a key in Discord, a commit, a source file, or this document.

| Variable name | Purpose | Required for local fixture mode? |
|---|---|---|
| `APP_ENV` | Explicit runtime environment label such as `development` | Yes |
| `API_HOST` | Backend bind host | Yes |
| `API_PORT` | Backend port | Yes |
| `LOG_LEVEL` | Minimum structured-log verbosity | Yes |
| `DATA_MODE` | Explicit `sample`, `cached`, or `live` provenance mode | Yes |
| `FRONTEND_ORIGIN` | Allowed frontend origin for API/CORS configuration | Yes once the frontend is wired |
| `LINODE_CLI_TOKEN` | Akamai Cloud/Linode personal access token for approved CLI/API provisioning | No; never commit |
| `AKAMAI_CLOUD_REGION` | Approved deployment region identifier | No |
| `OPENAI_BASE_URL` | Workshop-compatible OpenAI endpoint; use only after the organizer confirms the current value | No |
| `OPENAI_API_KEY` | Workshop team inference key | No; never commit or expose to the frontend |
| `CHAT_MODEL` | Approved workshop chat alias, currently documented as `hackathon-chat` | No |
| `EMBEDDING_MODEL` | Approved workshop embedding alias, currently documented as `hackathon-embedding` | No |
| `VECTOR_STORE_URL` | Approved retrieval-store endpoint | No |
| `VECTOR_STORE_API_KEY` | Retrieval-store credential | No; never commit |

D2 must redact all values matching credential variables from logs. The health endpoint must expose no secret, account, raw financial, or model-prompt data.

## Blockers and required handoff

1. Allen must authenticate to Cloud Manager and provide the human-approved outcome of: account access, actual credit/balance, permitted regions, intended deploy product, and maximum spend.
2. Jet and Allen must verify the workshop candidate with the organizers and a harmless authenticated request: current endpoint/auth method, aliases, quotas, policy, latency, and response schema. Until then, it is unavailable rather than mocked as complete.
3. Gate 0 must freeze the API routes, frontend origin, health response semantics, demo symbol, and fixture/live-data behavior before D2 creates deployment files.
4. Cai and Jet must document the evidence corpus size and retrieval queries before vector storage is reconsidered.
5. A channel ID must replace `REPLACE_CHANNEL_ID` in `docs/COMMUNICATIONS.md`, and bot permissions must be tested, before Discord coordination is claimed as operational.

## D2 readiness checklist

- [ ] Gate 0 contract is approved and recorded in `ARCHITECTURE.md` / `DECISIONS.md`.
- [ ] Runnable backend and frontend exist with a deterministic local sample mode.
- [ ] Local `/health` and actual frontend-to-backend smoke commands are defined.
- [ ] Human approval names the cloud product, region, spend ceiling, and account owner.
- [ ] Credit/balance and current pricing are inspected by the authorized account holder.
- [ ] Required credentials are stored outside Git and injected only at deploy/runtime.
- [ ] Remote URL plus health and application smoke evidence can be recorded after deployment.
