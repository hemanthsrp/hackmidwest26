"""General news adapter via MarketAux's free tier (licensed financial news
API -- avoids scraping paywalled Bloomberg/WSJ, which PROJECT_BRIEF.md says
not to assume access to). Swap NEWS_API_KEY / this module for another
provider without touching the pipeline -- it only depends on RawRecord."""

from datetime import datetime, timezone
from typing import ClassVar

import httpx

from ..config import get_settings
from .base import RawRecord, SourceAdapter, SourceUnavailableError

API_URL = "https://api.marketaux.com/v1/news/all"


class MarketauxNewsAdapter(SourceAdapter):
    name: ClassVar[str] = "marketaux"
    source_type: ClassVar[str] = "general_news"
    fixture_file: ClassVar[str] = "news_sample.json"

    def fetch_live(self, symbol: str) -> list[RawRecord]:
        settings = get_settings()
        if not settings.news_api_key:
            raise SourceUnavailableError("NEWS_API_KEY not configured")

        params = {
            "symbols": symbol,
            "language": "en",
            "limit": 10,
            "api_token": settings.news_api_key,
        }
        try:
            resp = httpx.get(API_URL, params=params, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceUnavailableError(str(exc)) from exc

        now = datetime.now(timezone.utc)
        records: list[RawRecord] = []
        for article in data.get("data", []):
            published_at = _parse_dt(article.get("published_at"))
            records.append(
                RawRecord(
                    source_name=article.get("source", self.name),
                    source_type=self.source_type,
                    symbol=symbol,
                    payload={
                        "title": article.get("title"),
                        "description": article.get("description"),
                        "entities": article.get("entities", []),
                    },
                    retrieved_at=now,
                    published_at=published_at,
                    observed_at=published_at,
                    url=article.get("url"),
                )
            )
        return records


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
