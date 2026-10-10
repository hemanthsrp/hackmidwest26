from datetime import datetime, timezone

from scraper_analysis.models.evidence import Evidence
from scraper_analysis.pipeline.dedup import dedup_evidence

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def make_evidence(**overrides) -> Evidence:
    defaults = dict(
        symbol="AAPL",
        title="Some headline",
        source_name="Sample Wire",
        source_type="general_news",
        source_url="https://example.com/a",
        retrieved_at=NOW,
    )
    defaults.update(overrides)
    return Evidence(**defaults)


def test_dedup_removes_exact_url_duplicates():
    items = [make_evidence(), make_evidence()]
    result = dedup_evidence(items)
    assert len(result) == 1


def test_dedup_keeps_distinct_urls():
    items = [make_evidence(source_url="https://example.com/a"), make_evidence(source_url="https://example.com/b")]
    result = dedup_evidence(items)
    assert len(result) == 2


def test_dedup_falls_back_to_title_when_no_url():
    items = [
        make_evidence(source_url=None, title="Same Headline  "),
        make_evidence(source_url=None, title="same headline"),
    ]
    result = dedup_evidence(items)
    assert len(result) == 1


def test_dedup_empty_list_returns_empty():
    assert dedup_evidence([]) == []
