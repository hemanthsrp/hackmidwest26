from datetime import datetime, timezone

from scraper_analysis.pipeline.normalize import normalize
from scraper_analysis.sources.base import RawRecord


def test_normalize_sec_filing_builds_title_and_marks_verified():
    record = RawRecord(
        source_name="sec_edgar",
        source_type="sec_filing",
        symbol="AAPL",
        payload={"form_type": "8-K", "items": "2.02", "company_name": "Apple Inc."},
        retrieved_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        published_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        observed_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
        url="https://example.com/8k",
    )

    evidence = normalize(record, "sample")

    assert evidence.symbol == "AAPL"
    assert "8-K" in evidence.title
    assert evidence.credibility.verified_filing is True
    assert evidence.data_mode == "sample"
    assert evidence.reporting_lag_days == 1.0


def test_normalize_general_news_uses_title_and_description():
    record = RawRecord(
        source_name="Sample Wire",
        source_type="general_news",
        symbol="AAPL",
        payload={"title": "Headline", "description": "Body"},
        retrieved_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        published_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        observed_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        url="https://example.com/a",
    )

    evidence = normalize(record, "live")

    assert evidence.title == "Headline"
    assert evidence.summary == "Body"
    assert evidence.data_mode == "live"


def test_normalize_unknown_source_type_falls_back_to_generic():
    record = RawRecord(
        source_name="mystery",
        source_type="something_new",
        symbol="MSFT",
        payload={"title": "Fallback title"},
        retrieved_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
    )

    evidence = normalize(record, "sample")

    assert evidence.title == "Fallback title"
    assert evidence.symbol == "MSFT"
