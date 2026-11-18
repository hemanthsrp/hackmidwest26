-- One-off backfill for rows stored before the lifecycle columns existed.
-- The columns, indexes and volatility_snapshots table are created by the scraper's
-- bootstrap (src/scraper_analysis/storage/schema.sql), which runs on every start;
-- run that first. Review, then run with:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f storage/lifecycle_schema.sql
-- It preserves existing source text, URLs, dates, IDs, and embeddings.

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
