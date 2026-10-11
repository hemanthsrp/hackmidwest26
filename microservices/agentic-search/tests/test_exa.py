from datetime import datetime, timezone

from agentic_search.exa import ExaSearch


def test_sample_search_returns_deterministic_symbol_matched_records() -> None:
    search = ExaSearch()

    first = search.search(
        symbol="AAPL",
        query="earnings guidance",
        start_date="2026-10-01",
        end_date="2026-10-11",
        domains=["example.com"],
        mode="sample",
    )
    second = search.search(
        symbol="AAPL",
        query="earnings guidance",
        start_date="2026-10-01",
        end_date="2026-10-11",
        domains=["example.com"],
        mode="sample",
    )

    assert first.data_mode == "sample"
    assert len(first.results) == 1
    assert [item.symbol for item in first.results] == ["AAPL"]
    assert first.results[0].source_name == "example.com"
    assert first.results[0].published_at == datetime(2026, 10, 5, tzinfo=timezone.utc)
    assert first.results[0].retrieved_at == datetime(2026, 10, 10, 18, 5, tzinfo=timezone.utc)
    assert first.results == second.results


def test_live_search_without_a_key_is_explicitly_unavailable() -> None:
    response = ExaSearch().search(symbol="AAPL", query="earnings", mode="live")

    assert response.error == {
        "code": "provider_unavailable",
        "message": "Exa search is not configured; no live search was performed.",
        "retryable": False,
    }


def test_live_search_uses_exa_search_api_with_all_bounded_filters() -> None:
    observed: dict[str, object] = {}

    def transport(payload: dict[str, object]) -> dict[str, object]:
        observed.update(payload)
        return {
            "results": [
                {
                    "title": "Apple updates guidance",
                    "url": "https://www.news.example.com/apple-guidance",
                    "highlights": ["Company guidance summary."],
                    "publishedDate": "2026-10-05T12:00:00Z",
                    "text": "this raw page text must never be selected as an excerpt",
                }
            ]
        }

    response = ExaSearch(api_key="test-key", transport=transport).search(
        symbol="AAPL",
        query="Apple guidance",
        start_date="2026-10-01",
        end_date="2026-10-11",
        domains=["news.example.com"],
        max_results=3,
        mode="live",
    )

    assert observed == {
        "query": "AAPL Apple guidance",
        "type": "fast",
        "category": "news",
        "numResults": 3,
        "includeDomains": ["news.example.com"],
        "startPublishedDate": "2026-10-01T00:00:00Z",
        "endPublishedDate": "2026-10-11T00:00:00Z",
        "contents": {"highlights": True},
    }
    assert response.data_mode == "live"
    assert response.results[0].source_name == "news.example.com"
    assert response.results[0].summary == "Company guidance summary."
    assert not hasattr(response.results[0], "buy_sell_confidence")


def test_live_search_caps_excerpt_without_reading_raw_text() -> None:
    response = ExaSearch(
        api_key="test-key",
        transport=lambda _: {
            "results": [
                {
                    "title": "Long highlight",
                    "url": "https://news.example.com/long",
                    "highlights": ["x" * 700],
                    "text": "must not be used",
                    "publishedDate": "2026-10-05T12:00:00Z",
                }
            ]
        },
    ).search(symbol="AAPL", query="news", mode="live")

    assert len(response.results[0].summary) == 500
    assert response.results[0].summary == "x" * 500


def test_invalid_request_values_return_safe_non_retryable_envelopes() -> None:
    search = ExaSearch()

    max_results = search.search(symbol="AAPL", query="news", max_results="1")
    domains = search.search(symbol="AAPL", query="news", domains=[1])

    assert max_results.error == {
        "code": "invalid_max_results",
        "message": "max_results must be an integer between 1 and 10",
        "retryable": False,
    }
    assert domains.error == {
        "code": "invalid_domains",
        "message": "domains must be a list of non-empty strings",
        "retryable": False,
    }
