-- Additive lifecycle/provenance migration. Review, then run with:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f storage/lifecycle_schema.sql
-- It preserves existing source text, URLs, dates, IDs, and embeddings.

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

UPDATE evidence
SET provider = COALESCE(provider, CASE source_type
    WHEN 'general_news' THEN 'news_adapter'
    WHEN 'sec_filing' THEN 'sec_edgar'
    WHEN 'congressional_disclosure' THEN 'congressional_disclosure'
    ELSE source_type END),
    value_origin = CASE source_type
        WHEN 'general_news' THEN 'article'
        WHEN 'sec_filing' THEN 'filing'
        WHEN 'congressional_disclosure' THEN 'congressional_disclosure'
        ELSE value_origin END,
    impact_category = CASE source_type
        WHEN 'sec_filing' THEN 'regulatory_or_filing'
        WHEN 'congressional_disclosure' THEN 'congressional_trade'
        ELSE impact_category END,
    stale_at = COALESCE(stale_at, retrieved_at + interval '7 days'),
    fresh_until = COALESCE(fresh_until, retrieved_at + interval '24 hours'),
    retention_reason = COALESCE(retention_reason, 'historical_research');

UPDATE signals
SET value_origin = CASE WHEN source ILIKE '%yahoo%' THEN 'yahoo_market' ELSE value_origin END,
    impact_category = CASE WHEN source ILIKE '%yahoo%' THEN 'market_mover' ELSE impact_category END,
    retrieved_at = COALESCE(retrieved_at, as_of),
    stale_at = COALESCE(stale_at, as_of + interval '1 day');

CREATE INDEX IF NOT EXISTS idx_evidence_current_filters
    ON evidence (symbol, lifecycle_status, value_origin, impact_category, retrieved_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_current_filters
    ON signals (symbol, lifecycle_status, value_origin, impact_category, as_of DESC);
