"""Tavily News Search adapter with deterministic fixtures and bounded results."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "tavily_news_sample.json"
_TAVILY_URL = "https://api.tavily.com/search"
_MAX_RESULTS = 10


@dataclass(frozen=True)
class SearchResult:
    symbol: str
    title: str
    summary: str
    source_name: str
    source_url: str
    published_at: datetime | None
    retrieved_at: datetime


@dataclass(frozen=True)
class SearchResponse:
    results: list[SearchResult] = field(default_factory=list)
    data_mode: str = "sample"
    error: dict[str, Any] | None = None


class TavilyNewsSearch:
    """Search Tavily News without turning provider relevance into financial advice."""

    def __init__(
        self,
        api_key: str | None = None,
        transport: Callable[[dict[str, object]], dict[str, object]] | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("TAVILY_API_KEY")
        self._transport = transport or self._request

    def search(
        self,
        *,
        symbol: str,
        query: str,
        start_date: str | None = None,
        end_date: str | None = None,
        domains: list[str] | None = None,
        max_results: int = _MAX_RESULTS,
        mode: str = "sample",
    ) -> SearchResponse:
        if mode not in {"sample", "live"}:
            return _error("invalid_mode", "mode must be sample or live", False)
        if not symbol.isalpha() or not (1 <= len(symbol) <= 5):
            return _error("invalid_symbol", "symbol must contain 1 to 5 letters", False)
        if not query.strip():
            return _error("invalid_query", "query must not be empty", False)
        dates = _parse_range(start_date, end_date)
        if isinstance(dates, dict):
            return SearchResponse(data_mode=mode, error=dates)
        if not 1 <= max_results <= _MAX_RESULTS:
            return _error("invalid_max_results", f"max_results must be between 1 and {_MAX_RESULTS}", False)
        normalized_symbol = symbol.upper()
        if mode == "sample":
            return SearchResponse(
                results=_filter_results(_sample_results(normalized_symbol), dates, domains, max_results),
                data_mode="sample",
            )
        if not self._api_key:
            return _error("provider_unavailable", "Tavily search is not configured; no live search was performed.", False)
        payload: dict[str, object] = {
            "api_key": self._api_key,
            "query": f"{normalized_symbol} {query.strip()}",
            "topic": "news",
            "max_results": max_results,
        }
        if domains:
            payload["include_domains"] = domains
        try:
            raw = self._transport(payload)
            raw_results = raw.get("results", [])
            if not isinstance(raw_results, list):
                raise ValueError("Tavily response results is not a list")
            results = [_normalize(normalized_symbol, item) for item in raw_results if isinstance(item, dict)]
        except Exception:
            return _error("provider_unavailable", "Tavily search is unavailable; no live search was performed.", True)
        return SearchResponse(results=_filter_results(results, dates, domains, max_results), data_mode="live")

    @staticmethod
    def _request(payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            _TAVILY_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            return json.load(response)


def _sample_results(symbol: str) -> list[SearchResult]:
    now = datetime.now(timezone.utc)
    records = json.loads(_FIXTURE_PATH.read_text())
    return [_normalize(symbol, record, retrieved_at=now) for record in records]


def _normalize(symbol: str, item: dict[str, Any], retrieved_at: datetime | None = None) -> SearchResult:
    url = str(item["url"])
    return SearchResult(
        symbol=symbol,
        title=str(item.get("title", "Untitled result")),
        summary=str(item.get("content", item.get("summary", ""))),
        source_name=urlparse(url).netloc,
        source_url=url,
        published_at=_parse_timestamp(item.get("published_date")),
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
    )


def _parse_range(start_date: str | None, end_date: str | None) -> tuple[date | None, date | None] | dict[str, Any]:
    if bool(start_date) != bool(end_date):
        return {"code": "invalid_date_range", "message": "start_date and end_date must be provided together", "retryable": False}
    if not start_date:
        return None, None
    try:
        assert end_date is not None
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except ValueError:
        return {"code": "invalid_date_range", "message": "dates must use YYYY-MM-DD", "retryable": False}
    if start >= end:
        return {"code": "invalid_date_range", "message": "start_date must be earlier than end_date", "retryable": False}
    return start, end


def _filter_results(
    results: list[SearchResult], dates: tuple[date | None, date | None], domains: list[str] | None, max_results: int
) -> list[SearchResult]:
    start, end = dates
    allowed = {domain.lower() for domain in domains or []}
    filtered = []
    for result in results:
        if allowed and result.source_name.lower() not in allowed:
            continue
        if start and end and (not result.published_at or not start <= result.published_at.date() < end):
            continue
        filtered.append(result)
    return filtered[:max_results]


def _parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _error(code: str, message: str, retryable: bool) -> SearchResponse:
    return SearchResponse(error={"code": code, "message": message, "retryable": retryable})
