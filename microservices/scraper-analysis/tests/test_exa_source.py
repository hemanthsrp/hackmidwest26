from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from scraper_analysis.config import Settings
from scraper_analysis.sources.base import SourceUnavailableError
from scraper_analysis.sources.exa import ExaNewsAdapter


class FakeSearch:
    def search(self, **kwargs):
        from agentic_search.exa import SearchResponse, SearchResult

        assert kwargs == {
            "symbol": "AAPL",
            "query": "company news and material events",
            "start_date": "2026-09-11",
            "end_date": "2026-10-12",
            "domains": ["example.com"],
            "max_results": 5,
            "mode": "live",
        }
        return SearchResponse(
            data_mode="live",
            results=[
                SearchResult(
                    symbol="AAPL",
                    title="Apple reports a material update",
                    summary="Permitted provider highlight.",
                    source_name="example.com",
                    source_url="https://example.com/apple",
                    published_at=datetime(2026, 10, 11, tzinfo=UTC),
                    retrieved_at=datetime(2026, 10, 11, 1, tzinfo=UTC),
                    data_mode="live",
                )
            ],
        )


def test_exa_news_adapter_turns_attributable_results_into_normalized_records():
    rows = ExaNewsAdapter(
        search=FakeSearch(),
        allowed_domains=["example.com"],
        today=lambda: datetime(2026, 10, 11, tzinfo=UTC).date(),
    ).fetch_live("AAPL")

    assert len(rows) == 1
    row = rows[0]
    assert (row.source_name, row.source_type, row.symbol, row.url) == (
        "example.com", "general_news", "AAPL", "https://example.com/apple"
    )
    assert row.payload == {
        "title": "Apple reports a material update",
        "description": "Permitted provider highlight.",
        "provider": "exa",
        "query": "company news and material events",
    }


def test_ingestion_registers_exa_only_when_the_provider_is_explicitly_enabled(monkeypatch):
    from scraper_analysis.config import get_settings
    from scraper_analysis.pipeline.ingest import build_adapters

    monkeypatch.setattr(get_settings(), "enable_exa_search", True, raising=False)

    assert "exa_search" in {adapter.name for adapter in build_adapters()}


@pytest.mark.parametrize("value", ["-1", "0", "31", "1000000000", "1.5", "nan", "inf", "-inf", "invalid", ""])
def test_exa_lookback_rejects_invalid_environment_values(monkeypatch, value):
    monkeypatch.setenv("EXA_LOOKBACK_DAYS", value)
    with pytest.raises(ValidationError, match="exa_lookback_days"):
        Settings(_env_file=None)


@pytest.mark.parametrize("value", [1, 30])
def test_exa_lookback_accepts_environment_boundaries(monkeypatch, value):
    monkeypatch.setenv("EXA_LOOKBACK_DAYS", str(value))
    assert Settings(_env_file=None).exa_lookback_days == value


@pytest.mark.parametrize("value", [-1, 0, 31, 10**100, 1.5, float("nan"), float("inf"), "30", True])
def test_exa_adapter_rejects_invalid_lookback_overrides(value):
    search = Mock()
    with pytest.raises(ValueError, match="integer between 1 and 30"):
        ExaNewsAdapter(search=search, allowed_domains=["example.com"], lookback_days=value)
    search.search.assert_not_called()


@pytest.mark.parametrize("domains", ["", " , , "])
def test_exa_empty_configured_allow_list_never_calls_live_search(monkeypatch, domains):
    from scraper_analysis.config import get_settings

    monkeypatch.setattr(get_settings(), "exa_allowed_domains", domains)
    search = Mock()
    adapter = ExaNewsAdapter(search=search)
    with pytest.raises(SourceUnavailableError, match="domain policy is not configured"):
        adapter.fetch_live("AAPL")
    search.search.assert_not_called()


def test_exa_empty_override_allow_list_never_calls_live_search(monkeypatch):
    from scraper_analysis.config import get_settings

    monkeypatch.setattr(get_settings(), "exa_allowed_domains", "example.com")
    search = Mock()
    adapter = ExaNewsAdapter(search=search, allowed_domains=[])
    with pytest.raises(SourceUnavailableError, match="domain policy is not configured"):
        adapter.fetch_live("AAPL")
    search.search.assert_not_called()
