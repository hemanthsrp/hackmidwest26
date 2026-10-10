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
