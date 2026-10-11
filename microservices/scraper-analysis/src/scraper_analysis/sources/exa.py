"""Exa news search as a bounded, attributable scraper source."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from agentic_search.exa import ExaSearch

from ..config import get_settings
from .base import RawRecord, SourceAdapter, SourceUnavailableError


class ExaNewsAdapter(SourceAdapter):
    name = "exa_search"
    source_type = "general_news"
    fixture_file = "exa_news_sample.json"
    query = "company news and material events"

    def __init__(
        self,
        search: ExaSearch | None = None,
        *,
        allowed_domains: list[str] | None = None,
        lookback_days: int | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        settings = get_settings()
        self._search = search or ExaSearch()
        self._allowed_domains = allowed_domains if allowed_domains is not None else settings.exa_allowed_domains_list
        self._lookback_days = lookback_days if lookback_days is not None else settings.exa_lookback_days
        if type(self._lookback_days) is not int or not 1 <= self._lookback_days <= 30:
            raise ValueError("Exa lookback_days must be an integer between 1 and 30")
        self._today = today

    def fetch_live(self, symbol: str) -> list[RawRecord]:
        if not self._allowed_domains:
            raise SourceUnavailableError("Exa domain policy is not configured.")
        end = self._today() + timedelta(days=1)
        start = end - timedelta(days=self._lookback_days + 1)
        response = self._search.search(
            symbol=symbol,
            query=self.query,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            domains=self._allowed_domains,
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
