# Managed PostgreSQL + pgvector preflight

## Scope

This directory prepares one managed PostgreSQL database with the pgvector extension for the Hack Midwest demo. It is intended to store permitted evidence metadata, attributable excerpts/chunks, retrieval embeddings, embedding-model version, and retrieval results. It must not store brokerage credentials, account data, or API tokens.

This is a preflight/runbook only. It creates no cloud resource by itself.

## Required local configuration

1. Copy the root template:

   ```sh
   cp .env.example .env
   ```

2. Fill only these cloud fields in the local ignored `.env`:

   ```ini
   LINODE_CLI_TOKEN=<short-lived Akamai Cloud/Linode PAT>
   AKAMAI_CLOUD_REGION=<approved region after preflight>
   VECTOR_DB_LABEL=hackmidwest-vector-db
   VECTOR_DB_PLAN=<available approved PostgreSQL plan after preflight>
   VECTOR_DB_ALLOWED_CIDR=<the single approved application/public IP CIDR>
   ```

The PAT is separate from `OPENAI_API_KEY`. Grant it only **Account: Read Only** and **Databases: Read/Write**. Do not send it in chat or commit it.

## Preflight checklist

Before creation, the authorized account holder and Allen verify:

- Cloud Manager shows the promotion/credit balance and expiry.
- The account is activated and the PAT identifies the intended team account.
- The selected region supports Managed PostgreSQL and the selected plan.
- Current hourly/monthly price fits the approved database-only spend ceiling.
- The allowed CIDR is restricted to the current application/developer address; never use an open allow list.
- The label does not collide with another project resource.
- The team accepts a retention policy: delete demo chunks/vectors and revoke the PAT after the hackathon unless a human explicitly keeps them.

## Provisioning shape after approval

Use a one-node Managed PostgreSQL instance with TLS required. After it reaches `active` and DNS resolves:

1. Obtain the generated connection details without logging the password.
2. Store the resulting `DATABASE_URL` only in local `.env` or a deployment secret store.
3. Connect with TLS and verify `CREATE EXTENSION IF NOT EXISTS vector` succeeds.
4. Create project-owned tables only after the evidence/retrieval schema is agreed.
5. Run a smoke test that inserts one explicitly labeled sample evidence row, a 1024-dimensional fixture vector matching the workshop embedding configuration, retrieves it by vector distance, then deletes the test row.

Do not run `akamai-workshop-hackmidwest/scripts/up.sh`: it also creates Object Storage resources that are not part of this database-only scope.

## Runtime policy

The database supports retrieval, not a recommendation engine. Retrieval must preserve evidence ID, source, URL when permitted, timestamps, `data_mode`, and embedding-model version. If the database is unreachable, the API returns a labeled unavailable/insufficient-data state; it must not fabricate retrieved evidence.
