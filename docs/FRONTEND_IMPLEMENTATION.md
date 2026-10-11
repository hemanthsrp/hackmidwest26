# Frontend and account implementation — 2026-10-11

Owner: Hemanth / frontend lane. Integration owner: Jet. User authorized the
expanded full-stack implementation in the current workspace. No remote claims,
messages, pushes, or provisioning were performed.

## Product decisions from the user

Next.js; persistent left navigation, center page, right assistant; Home, Trending,
Industries; stock detail routes; centered account settings dialog; light default
with dark mode; desktop-first. Real accounts and persistence are the target.
Email/password with scrypt plus Google, Apple, and Microsoft; Robinhood first;
holdings only; research proposals with no order execution; public-beta target.
Chat memory retains preferences across chats, never the raw conversation.
Notifications are in-app and email.

## Implemented boundaries

- `frontend/`: runnable demo, application shell, routes, filtered cards, charts,
  settings, chat, sign-in/registration/recovery UI, Auth.js, Drizzle migrations,
  same-origin BFF, account export/deletion, email digest entrypoint.
- `microservices/research-api/`: `/v1` authenticated routes, SQLAlchemy-owned
  research records, source adapter requests, live-only freshness filtering,
  evidence-direction assessments, category rankings, structured memories,
  account isolation, notification/outbox creation, read-only broker adapter seam.
- Existing `/v0/research-assessments` behavior remains compatible.
- Existing scraper tables and Jev package were not modified.

## Contract

The BFF authenticates users and signs `{sub, aud: "research-api", exp}` with
HMAC-SHA256; expiry is 60 seconds. Python validates the signature, audience,
expiry, and subject. Provider tokens never enter a browser response.

Private resource responses use `{data, data_mode, as_of, warnings, next_cursor}`.
The current bounded feed returns all supported results, with `next_cursor: null`.
Stock responses retain `{symbol, snapshot, evidence, signals, assessment,
data_mode, warnings}`. Errors use `{error:{code,message,retryable}}`.

Auth.js credentials require JWT sessions; the implementation therefore uses
encrypted JWT cookies plus a revocable database registry instead of the original
plan's database session strategy. Users, identity-provider accounts, action
tokens, rate counters, and session registry use Drizzle migrations. Research-owned
records use an explicit `python -m research_api.storage` schema initialization.

## Outstanding before public beta

Robinhood custom-platform approval and a verified authorization/refresh/revocation
flow; real provider credentials and end-to-end auth/email tests; live data and
inference verification; formal migration upgrades/rollback beyond initial tables;
production monitoring, retention/backup policy, legal copy,
and an approved HTTPS deployment. The research chat currently uses the Akamai
client directly; a Strands orchestration path for this new chat remains outstanding.

This document records implementation status, not a claim that public beta or live
brokerage connectivity is complete. See `frontend/README.md` for reproducible commands.
