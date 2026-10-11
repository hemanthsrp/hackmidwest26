from datetime import datetime, timezone

from agentic_search.tavily import TavilyNewsSearch


def test_sample_search_honors_symbol_date_and_domain_filters() -> None:
    search = TavilyNewsSearch()

    response = search.search(
        symbol="AAPL",
        query="earnings guidance",
        start_date="2026-10-01",
        end_date="2026-10-11",
        domains=["example.com"],
        mode="sample",
    )

    assert response.data_mode == "sample"
    assert len(response.results) == 1
    result = response.results[0]
    assert result.symbol == "AAPL"
    assert result.source_url == "https://example.com/aapl-guidance"
    assert result.published_at == datetime(2026, 10, 5, tzinfo=timezone.utc)
    assert result.source_name == "example.com"


def test_live_search_without_a_key_is_explicitly_unavailable() -> None:
    response = TavilyNewsSearch().search(symbol="AAPL", query="earnings", mode="live")

    assert response.error == {
        "code": "provider_unavailable",
        "message": "Tavily search is not configured; no live search was performed.",
        "retryable": False,
    }


def test_live_search_normalizes_tavily_results_without_a_trading_score() -> None:
    observed: dict[str, object] = {}

    def transport(payload: dict[str, object]) -> dict[str, object]:
        observed.update(payload)
        return {
            "results": [
                {
                    "title": "Apple updates guidance",
                    "url": "https://news.example.com/apple-guidance",
                    "content": "Company guidance summary.",
                    "published_date": "2026-10-05T12:00:00Z",
                    "score": 0.98,
                }
            ]
        }

    response = TavilyNewsSearch(api_key="test-key", transport=transport).search(
        symbol="AAPL",
        query="Apple guidance",
        domains=["news.example.com"],
        mode="live",
    )

    assert observed["topic"] == "news"
    assert observed["include_domains"] == ["news.example.com"]
    assert response.data_mode == "live"
    assert response.results[0].summary == "Company guidance summary."
    assert not hasattr(response.results[0], "buy_sell_confidence")
