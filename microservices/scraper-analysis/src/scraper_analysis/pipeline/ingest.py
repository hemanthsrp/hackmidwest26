"""Ingestion orchestration: SEC EDGAR, news (MarketAux + official RSS),
congressional disclosures, and -- feature-flagged -- Reddit. Commodities
(Phase 3) register additional adapters here; the API layer and the rest of
the pipeline don't change."""

import re

from ..agents.tagging_agent import tag_evidence
from ..config import get_settings
from ..models.evidence import Evidence
from ..models.signal import Signal
from ..sources import market_signals
from ..sources.base import SourceAdapter
from ..sources.congressional import SenateEfdAdapter
from ..sources.news_marketaux import MarketauxNewsAdapter
from ..sources.official_rss import ADAPTERS as OFFICIAL_RSS_ADAPTERS
from ..sources.reddit_unofficial import RedditUnofficialAdapter
from ..sources.sec_edgar import SecEdgarAdapter
from ..storage.store import get_store
from .dedup import dedup_evidence
from .normalize import normalize
from .router import filter_records

SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def build_adapters() -> list[SourceAdapter]:
    """Built fresh per call (not a module-level constant) so the
    feature-flagged Reddit adapter respects ENABLE_REDDIT_SCRAPER at call
    time -- including in tests that monkeypatch settings."""
    adapters: list[SourceAdapter] = [
        SecEdgarAdapter(),
        MarketauxNewsAdapter(),
        *OFFICIAL_RSS_ADAPTERS,
        SenateEfdAdapter(),
    ]
    if get_settings().enable_reddit_scraper:
        adapters.append(RedditUnofficialAdapter())
    return adapters


class InvalidSymbolError(ValueError):
    pass


def validate_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not SYMBOL_RE.match(normalized):
        raise InvalidSymbolError(f"invalid symbol: {symbol!r}")
    return normalized


def run_ingestion(symbol: str, allow_live: bool = True, tag: bool = True) -> list[Evidence]:
    symbol = validate_symbol(symbol)
    all_evidence: list[Evidence] = []

    for adapter in build_adapters():
        records, data_mode = adapter.fetch(symbol, allow_live=allow_live)
        for record in filter_records(records):
            evidence = normalize(record, data_mode)
            if tag:
                evidence = tag_evidence(evidence)
            all_evidence.append(evidence)

    deduped = dedup_evidence(all_evidence)
    get_store().save_evidence(deduped)
    return deduped


def run_signal_ingestion(symbol: str, allow_live: bool = True) -> list[Signal]:
    symbol = validate_symbol(symbol)
    signals, _data_mode = market_signals.fetch(symbol, allow_live=allow_live)
    get_store().save_signals(signals)
    return signals
