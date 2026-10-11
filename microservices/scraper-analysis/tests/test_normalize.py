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


def test_normalize_congressional_disclosure_builds_title_and_flags_historical():
    record = RawRecord(
        source_name="Senate eFD",
        source_type="congressional_disclosure",
        symbol="AAPL",
        payload={
            "filer_name": "Jane Doe",
            "owner": "Spouse",
            "ticker": "AAPL",
            "asset_name": "Apple Inc.",
            "asset_type": "Stock",
            "transaction_type": "Purchase",
            "amount_range": "$15,001 - $50,000",
        },
        retrieved_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        published_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        observed_at=datetime(2026, 8, 15, tzinfo=timezone.utc),  # 47 days lag -> historical
        url="https://efdsearch.senate.gov/search/view/ptr/sample/",
    )

    evidence = normalize(record, "sample")

    assert "Jane Doe" in evidence.title
    assert "Historical Position Adjustment" in evidence.title
    assert evidence.credibility.verified_filing is True


def test_normalize_social_media_is_low_credibility_by_default():
    record = RawRecord(
        source_name="r/stocks",
        source_type="social_media",
        symbol="AAPL",
        payload={"title": "AAPL earnings play", "description": "thoughts?"},
        retrieved_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        published_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        observed_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )

    evidence = normalize(record, "live")

    assert evidence.title == "AAPL earnings play"
    assert evidence.credibility.verified_filing is False
    assert evidence.credibility.overall_score < 0.5


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
