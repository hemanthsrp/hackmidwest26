# CI/CD

Two GitHub Actions workflows. Nothing is provisioned by them: deploying needs a host you set up yourself, and stays off until you turn it on.

| Workflow | Runs on | Does |
|---|---|---|
| [`ci.yml`](../.github/workflows/ci.yml) | every push and pull request | Frontend typecheck, tests, build and `npm audit`; each Python service's tests as its own job; a build of all five Docker images (not pushed); a check of `compose.deploy.yml` |
| [`cd.yml`](../.github/workflows/cd.yml) | CI passing on a push to `main`; or by hand | **Publish:** push the five images to GitHub Container Registry as `ghcr.io/hemanthsrp/hackmidwest26/<image>:<commit sha>` and `:main`. **Deploy** (only when switched on): roll that SHA out to one Docker host over SSH, then check `/api/health` |

Images: `frontend`, `frontend-migrator`, `research-api`, `scraper-analysis`, `volatility-surface-builder` (published for later use; not part of the deployed stack yet).

## Turning on deploys

The docs in [AKAMAI_FEASIBILITY.md](AKAMAI_FEASIBILITY.md) require approval of a compute target, its cost and region before anything is created. That guide's pattern is one `g6-standard-1` Linode with a Cloud Firewall running Docker Compose. Once a host exists:

**On the host** (once)

1. Install Docker Engine with the Compose plugin; create a deploy user in the `docker` group that can log in with an SSH key.
2. Create the deploy folder (default `/opt/folio`, owned by that user) and put a `.env` there, mode `600`, with at least:

   ```sh
   POSTGRES_PASSWORD=...           # a long random value
   AUTH_SECRET=...                 # 32+ random bytes
   SERVICE_ASSERTION_SECRET=...    # 32+ random bytes, different from AUTH_SECRET
   AUTH_URL=https://your.domain    # the public HTTPS address
   HOST_PORT=3100                  # loopback port the reverse proxy forwards to
   ```

   Optional: `BROKER_ENCRYPTION_KEY`, `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `CHAT_MODEL` / `EMBEDDING_MODEL`, `RESEND_API_KEY` / `EMAIL_FROM` / `DIGEST_JOB_SECRET`, `ALLOW_REGISTRATION`, `DECISION_NLP_MODEL`, `ENABLE_SCHEDULER`. Scraper keys go in `scraper-analysis.env` in the same folder. Every name is listed in [`compose.deploy.yml`](../compose.deploy.yml); secrets never live in the repository.
3. Put an HTTPS reverse proxy (Caddy, nginx) in front of `127.0.0.1:$HOST_PORT`. The stack publishes no other port; Postgres and the internal APIs are reachable only inside the Compose network.

**On GitHub** (Settings)

| Where | Name | Value |
|---|---|---|
| Environments | `production` | Add yourself as a required reviewer, so each deploy waits for your approval |
| Secrets (production environment) | `DEPLOY_HOST` | Host name or IP |
| | `DEPLOY_USER` | The deploy user |
| | `DEPLOY_SSH_KEY` | That user's private key (a key used only for deploys) |
| | `DEPLOY_KNOWN_HOSTS` | Output of `ssh-keyscan <host>`, checked against the host's real fingerprint; the job refuses unknown host keys |
| Variables | `DEPLOY_ENABLED` | `true` to switch deploys on; anything else keeps them off |
| | `DEPLOY_PATH` | Optional, default `/opt/folio` |
| | `PUBLIC_URL` | Optional, shown on the deployment |

The deploy logs the host in to the registry with the run's short-lived token and logs out after pulling, so no registry credential is stored on the host.

## A deploy

1. A merge to `main` runs CI. When it passes, CD publishes the images for that exact commit.
2. The deploy job waits for approval in the `production` environment.
3. On the host it pulls the images for that SHA, runs `docker compose up -d --wait` (migrations and the scraper schema run first, as in local Compose), records the SHA in `DEPLOYED_TAG` and calls `/api/health`. A service that does not become healthy within 5 minutes fails the job.

Deploys run one at a time, in order. The Postgres data lives in the `folio-data` volume and survives redeploys; back it up separately.

## Rolling back

Actions → CD → Run workflow on `main`, with **image_tag** set to an earlier commit SHA (for example the one in `DEPLOYED_TAG` before the bad deploy). It skips publishing and deploys that tag. Database migrations are not reversed: a rollback across a schema change needs a manual decision.

## Not covered yet

- No HTTPS or domain setup; the reverse proxy is yours to configure.
- No database backups or log shipping.
- The volatility-surface service image is published but not deployed.
- Robinhood linking stays off on hosted deployments until the platform approval in [PUBLIC_BETA_READINESS.md](PUBLIC_BETA_READINESS.md).
