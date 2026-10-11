"""Fixture-first Exa Search adapter with bounded, attributable news results."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_EXA_SEARCH_URL = "https://api.exa.ai/search"
_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "exa_news_sample.json"
_MAX_RESULTS = 10
_MAX_EXCERPT_CHARS = 500


@dataclass(frozen=True)
class SearchResult:
    symbol: str
    title: str
    summary: str
    source_name: str
    source_url: str
    published_at: datetime | None
    retrieved_at: datetime
    data_mode: str


@dataclass(frozen=True)
class SearchResponse:
    results: list[SearchResult] = field(default_factory=list)
    data_mode: str = "sample"
    error: dict[str, Any] | None = None


class ExaSearch:
    """Search Exa's Search API without treating provider relevance as advice."""

    def __init__(
        self,
        api_key: str | None = None,
        transport: Callable[[dict[str, object]], dict[str, object]] | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("EXA_API_KEY")
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
        request_error = _validate_request(symbol, query, domains, max_results, mode)
        if request_error:
            return request_error
        dates = _parse_range(start_date, end_date)
        if isinstance(dates, dict):
            return SearchResponse(data_mode=mode, error=dates)

        normalized_symbol = symbol.upper()
        if mode == "sample":
            return SearchResponse(
                results=_filter_results(_sample_results(normalized_symbol), dates, domains, max_results),
                data_mode="sample",
            )
        if not self._api_key:
            return _error("provider_unavailable", "Exa search is not configured; no live search was performed.", False)

        payload = _build_payload(normalized_symbol, query, dates, domains, max_results)
        try:
            raw = self._transport(payload)
            raw_results = raw.get("results", [])
            if not isinstance(raw_results, list):
                raise ValueError("Exa response results is not a list")
            results = [_normalize(normalized_symbol, item, "live") for item in raw_results if isinstance(item, dict)]
        except Exception:
            return _error("provider_unavailable", "Exa search is unavailable; no live search was performed.", True)
        return SearchResponse(results=_filter_results(results, dates, domains, max_results), data_mode="live")

    def _request(self, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            _EXA_SEARCH_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "x-api-key": self._api_key or ""},
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            return json.load(response)


def _validate_request(
    symbol: object, query: object, domains: object, max_results: object, mode: object
) -> SearchResponse | None:
    if mode not in {"sample", "live"}:
        return _error("invalid_mode", "mode must be sample or live", False)
    if not isinstance(symbol, str) or not symbol.isalpha() or not (1 <= len(symbol) <= 5):
        return _error("invalid_symbol", "symbol must contain 1 to 5 letters", False)
    if not isinstance(query, str) or not query.strip():
        return _error("invalid_query", "query must not be empty", False)
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= _MAX_RESULTS:
        return _error("invalid_max_results", f"max_results must be an integer between 1 and {_MAX_RESULTS}", False)
    if domains is not None and (
        not isinstance(domains, list) or any(not isinstance(domain, str) or not domain.strip() for domain in domains)
    ):
        return _error("invalid_domains", "domains must be a list of non-empty strings", False)
    return None


def _build_payload(
    symbol: str,
    query: str,
    dates: tuple[date | None, date | None],
    domains: list[str] | None,
    max_results: int,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "query": f"{symbol} {query.strip()}",
        "type": "fast",
        "category": "news",
        "numResults": max_results,
        # Request only Exa highlights; do not request raw page text/content.
        "contents": {"highlights": True},
    }
    if domains:
        payload["includeDomains"] = domains
    start, end = dates
    if start and end:
        payload["startPublishedDate"] = f"{start.isoformat()}T00:00:00Z"
        payload["endPublishedDate"] = f"{end.isoformat()}T00:00:00Z"
    return payload


def _sample_results(symbol: str) -> list[SearchResult]:
    records = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    return [
        _normalize(symbol, record, "sample")
        for record in records
        if record.get("symbol", "").upper() == symbol
    ]


def _normalize(symbol: str, item: dict[str, Any], data_mode: str) -> SearchResult:
    url = str(item["url"])
    return SearchResult(
        symbol=symbol,
        title=str(item.get("title", "Untitled result")),
        summary=_excerpt(item),
        source_name=_bare_domain(url),
        source_url=url,
        published_at=_parse_timestamp(item.get("publishedDate", item.get("published_date"))),
        retrieved_at=_parse_timestamp(item.get("retrieved_at")) or datetime.now(timezone.utc),
        data_mode=data_mode,
    )


def _excerpt(item: dict[str, Any]) -> str:
    highlights = item.get("highlights")
    if isinstance(highlights, list):
        text = " ".join(str(highlight) for highlight in highlights if isinstance(highlight, str))
    else:
        text = ""
    # Exa's supplied summary is acceptable metadata. Deliberately never read raw `text`.
    return (text or str(item.get("summary", "")))[:_MAX_EXCERPT_CHARS]


def _bare_domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _parse_range(start_date: str | None, end_date: str | None) -> tuple[date | None, date | None] | dict[str, Any]:
    if bool(start_date) != bool(end_date):
        return {"code": "invalid_date_range", "message": "start_date and end_date must be provided together", "retryable": False}
    if not start_date:
        return None, None
    try:
        assert end_date is not None
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except (TypeError, ValueError):
        return {"code": "invalid_date_range", "message": "dates must use YYYY-MM-DD", "retryable": False}
    if start >= end:
        return {"code": "invalid_date_range", "message": "start_date must be earlier than end_date", "retryable": False}
    return start, end


def _filter_results(
    results: list[SearchResult], dates: tuple[date | None, date | None], domains: list[str] | None, max_results: int
) -> list[SearchResult]:
    start, end = dates
    allowed = {_bare_domain(f"https://{domain.strip()}") for domain in domains or []}
    filtered = []
    for result in results:
        if allowed and result.source_name not in allowed:
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
