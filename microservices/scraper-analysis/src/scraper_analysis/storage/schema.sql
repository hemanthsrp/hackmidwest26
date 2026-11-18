-- Akamai Managed PostgreSQL schema for scraper-analysis.
-- Run once against the provisioned cluster (psql "$DATABASE_URL" -f schema.sql).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS evidence (
    id              UUID PRIMARY KEY,
    symbol          TEXT NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT,
    source_name     TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    source_url      TEXT,
    published_at    TIMESTAMPTZ,
    observed_at     TIMESTAMPTZ,
    retrieved_at    TIMESTAMPTZ NOT NULL,
    reporting_lag_days DOUBLE PRECISION,
    entities        JSONB NOT NULL DEFAULT '{}',
    sentiment       JSONB NOT NULL DEFAULT '{}',
    credibility     JSONB NOT NULL DEFAULT '{}',
    data_mode       TEXT NOT NULL,
    -- Confirmed dimension of Akamai's hosted "hackathon-embedding" model.
    embedding       vector(1024)
);

-- Added after the first deploy: structured source-specific facts (Form 4
-- buy/sell totals, Senate transaction type). Idempotent for existing clusters.
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS details JSONB NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_evidence_symbol ON evidence (symbol);
CREATE INDEX IF NOT EXISTS idx_evidence_embedding ON evidence
    USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS signals (
    id          UUID PRIMARY KEY,
    symbol      TEXT NOT NULL,
    name        TEXT NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    unit        TEXT NOT NULL,
    "window"    TEXT NOT NULL,  -- "window" is a reserved word in Postgres
    as_of       TIMESTAMPTZ NOT NULL,
    source      TEXT NOT NULL,
    data_mode   TEXT NOT NULL,
    UNIQUE (symbol, name, as_of, source)
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals (symbol);

-- Lifecycle and provenance columns, and the options snapshots research-api cites.
-- Every statement is safe to repeat, so a fresh database and an older one both end
-- up with the columns the store writes. (Rows stored before these columns existed
-- can be backfilled once with storage/lifecycle_schema.sql.)
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS provider TEXT,
    ADD COLUMN IF NOT EXISTS value_origin TEXT NOT NULL DEFAULT 'article',
    ADD COLUMN IF NOT EXISTS impact_category TEXT NOT NULL DEFAULT 'other',
    ADD COLUMN IF NOT EXISTS impact_level TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS impact_basis JSONB NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS embedding_status TEXT NOT NULL DEFAULT 'available',
    ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'fresh',
    ADD COLUMN IF NOT EXISTS fresh_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS stale_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS retention_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS retention_reason TEXT;

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS value_origin TEXT NOT NULL DEFAULT 'market_signal',
    ADD COLUMN IF NOT EXISTS impact_category TEXT NOT NULL DEFAULT 'market_mover',
    ADD COLUMN IF NOT EXISTS impact_level TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS impact_basis JSONB NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS retrieved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'fresh',
    ADD COLUMN IF NOT EXISTS stale_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS retention_until TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_evidence_current_filters
    ON evidence (symbol, lifecycle_status, value_origin, impact_category, retrieved_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_current_filters
    ON signals (symbol, lifecycle_status, value_origin, impact_category, as_of DESC);

-- Immutable, citable options diagnostics captured for an assessment request.
CREATE TABLE IF NOT EXISTS volatility_snapshots (
    id UUID PRIMARY KEY,
    symbol TEXT NOT NULL,
    source TEXT NOT NULL,
    data_mode TEXT NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL,
    statistics JSONB NOT NULL,
    lifecycle_status TEXT NOT NULL DEFAULT 'fresh',
    stale_at TIMESTAMPTZ,
    retention_until TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_volatility_snapshots_symbol_time
    ON volatility_snapshots (symbol, retrieved_at DESC);
