"""Official, sanctioned RSS feeds -- each outlet's own distribution channel,
not scraping. Verified live before wiring in (2026-10-10):

- Yahoo Finance: per-symbol feed, ideal fit, no filtering needed.
- CNBC: category feeds (no per-symbol feed exists), filtered by symbol/
  company-name mention.
- MarketWatch: top-stories feed (Dow Jones' own RSS CDN), filtered.
- Seeking Alpha: official feed, but its own <description> states "limited
  to personal, non-commercial use" -- fine for pulling into our analysis
  pipeline, do not republish the raw feed.

Reuters (killed public RSS in 2020) and Bloomberg/WSJ (no RSS, explicit
anti-bot ToS) are deliberately not included here -- see the conversation
record for why.
"""

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import ClassVar
from xml.etree import ElementTree

import httpx

from .base import RawRecord, SourceAdapter, SourceUnavailableError

# Small curated ticker -> company-name hint table for filtering general
# (non-per-symbol) feeds. Best-effort recall, not a full ticker database --
# a documented limitation, not silently hidden.
SYMBOL_NAME_HINTS: dict[str, str] = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "TSLA": "Tesla",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet",
    "GOOG": "Alphabet",
    "META": "Meta",
    "NVDA": "Nvidia",
    "NFLX": "Netflix",
    "JPM": "JPMorgan",
}


def _parse_rss_items(xml_text: str) -> list[dict]:
    root = ElementTree.fromstring(xml_text)
    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        description = (item.findtext("description") or "").strip()
        link = (item.findtext("link") or "").strip() or None
        pub_date_raw = item.findtext("pubDate")
        pub_date = None
        if pub_date_raw:
            try:
                pub_date = parsedate_to_datetime(pub_date_raw)
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pub_date = None
        items.append({"title": title, "description": description, "link": link, "published_at": pub_date})
    return items


def _matches_symbol(item: dict, symbol: str) -> bool:
    haystack = f"{item['title']} {item['description']}".lower()
    if re.search(rf"\b{re.escape(symbol.lower())}\b", haystack):
        return True
    hint = SYMBOL_NAME_HINTS.get(symbol.upper())
    return bool(hint and hint.lower() in haystack)


def _fetch_rss(url: str) -> list[dict]:
    try:
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10.0, follow_redirects=True)
        resp.raise_for_status()
        return _parse_rss_items(resp.text)
    except (httpx.HTTPError, ElementTree.ParseError) as exc:
        raise SourceUnavailableError(str(exc)) from exc


class YahooFinanceNewsAdapter(SourceAdapter):
    name: ClassVar[str] = "yahoo_finance"
    source_type: ClassVar[str] = "general_news"
    fixture_file: ClassVar[str] = "yahoo_finance_sample.json"

    FEED_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"

    def fetch_live(self, symbol: str) -> list[RawRecord]:
        items = _fetch_rss(self.FEED_URL.format(symbol=symbol))
        now = datetime.now(timezone.utc)
        return [
            RawRecord(
                source_name="Yahoo Finance",
                source_type=self.source_type,
                symbol=symbol,
                payload={"title": item["title"], "description": item["description"]},
                retrieved_at=now,
                published_at=item["published_at"],
                observed_at=item["published_at"],
                url=item["link"],
            )
            for item in items
        ]


class _CategoryRssAdapter(SourceAdapter):
    """Shared base for outlets with only general-category feeds (no
    per-symbol feed exists) -- filters items by symbol/company mention."""

    source_type: ClassVar[str] = "general_news"
    source_display_name: ClassVar[str]
    feed_urls: ClassVar[list[str]]

    def fetch_live(self, symbol: str) -> list[RawRecord]:
        now = datetime.now(timezone.utc)
        records: list[RawRecord] = []
        errors = 0
        for url in self.feed_urls:
            try:
                items = _fetch_rss(url)
            except SourceUnavailableError:
                errors += 1
                continue
            for item in items:
                if not _matches_symbol(item, symbol):
                    continue
                records.append(
                    RawRecord(
                        source_name=self.source_display_name,
                        source_type=self.source_type,
                        symbol=symbol,
                        payload={"title": item["title"], "description": item["description"]},
                        retrieved_at=now,
                        published_at=item["published_at"],
                        observed_at=item["published_at"],
                        url=item["link"],
                    )
                )
        if errors == len(self.feed_urls):
            raise SourceUnavailableError(f"all {self.source_display_name} feeds unreachable")
        return records


class CnbcNewsAdapter(_CategoryRssAdapter):
    name: ClassVar[str] = "cnbc"
    fixture_file: ClassVar[str] = "cnbc_sample.json"
    source_display_name: ClassVar[str] = "CNBC"
    # CNBC's own RSS infra (search.cnbc.com), ids verified live: Business, Economy.
    feed_urls: ClassVar[list[str]] = [
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000115",
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    ]


class MarketWatchNewsAdapter(_CategoryRssAdapter):
    name: ClassVar[str] = "marketwatch"
    fixture_file: ClassVar[str] = "marketwatch_sample.json"
    source_display_name: ClassVar[str] = "MarketWatch"
    feed_urls: ClassVar[list[str]] = [
        "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    ]


class SeekingAlphaNewsAdapter(_CategoryRssAdapter):
    name: ClassVar[str] = "seeking_alpha"
    fixture_file: ClassVar[str] = "seekingalpha_sample.json"
    # Feed's own <description> restricts this to personal/non-commercial
    # use -- fine to pull into our own analysis, do not republish the feed.
    source_display_name: ClassVar[str] = "Seeking Alpha"
    feed_urls: ClassVar[list[str]] = [
        "https://seekingalpha.com/market_currents.xml",
    ]


ADAPTERS: list[SourceAdapter] = [
    YahooFinanceNewsAdapter(),
    CnbcNewsAdapter(),
    MarketWatchNewsAdapter(),
    SeekingAlphaNewsAdapter(),
]
