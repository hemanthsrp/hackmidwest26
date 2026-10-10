"""Phase-1 ingestion orchestration: SEC EDGAR + general news. Later phases
(Reddit, congressional, commodities) register additional adapters here --
the API layer and the rest of the pipeline don't change."""

import re

from ..agents.tagging_agent import tag_evidence
from ..models.evidence import Evidence
from ..models.signal import Signal
from ..sources import market_signals
from ..sources.base import SourceAdapter
from ..sources.news_marketaux import MarketauxNewsAdapter
from ..sources.official_rss import ADAPTERS as OFFICIAL_RSS_ADAPTERS
from ..sources.sec_edgar import SecEdgarAdapter
from ..storage.store import get_store
from .dedup import dedup_evidence
from .normalize import normalize
from .router import filter_records

SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")

ADAPTERS: list[SourceAdapter] = [
    SecEdgarAdapter(),
    MarketauxNewsAdapter(),
    *OFFICIAL_RSS_ADAPTERS,
]


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

    for adapter in ADAPTERS:
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
