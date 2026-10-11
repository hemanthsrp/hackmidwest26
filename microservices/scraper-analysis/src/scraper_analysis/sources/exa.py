"""Exa news search as a bounded, attributable scraper source."""

from __future__ import annotations

from agentic_search.exa import ExaSearch

from .base import RawRecord, SourceAdapter, SourceUnavailableError


class ExaNewsAdapter(SourceAdapter):
    name = "exa_search"
    source_type = "general_news"
    fixture_file = "exa_news_sample.json"
    query = "company news and material events"

    def __init__(self, search: ExaSearch | None = None) -> None:
        self._search = search or ExaSearch()

    def fetch_live(self, symbol: str) -> list[RawRecord]:
        response = self._search.search(
            symbol=symbol,
            query=self.query,
            max_results=5,
            mode="live",
        )
        if response.error:
            raise SourceUnavailableError(response.error["message"])
        return [
            RawRecord(
                source_name=result.source_name,
                source_type=self.source_type,
                symbol=symbol.upper(),
                payload={
                    "title": result.title,
                    "description": result.summary,
                    "provider": "exa",
                    "query": self.query,
                },
                retrieved_at=result.retrieved_at,
                published_at=result.published_at,
                observed_at=result.published_at,
                url=result.source_url,
            )
            for result in response.results
        ]
