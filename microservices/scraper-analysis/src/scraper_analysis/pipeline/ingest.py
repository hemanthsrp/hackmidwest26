"""Ingestion orchestration: SEC EDGAR, news (MarketAux + official RSS),
congressional disclosures, and -- feature-flagged -- Reddit. Commodities
(Phase 3) register additional adapters here; the API layer and the rest of
the pipeline don't change."""

import re
from collections.abc import Callable
from dataclasses import dataclass

from ..agents.tagging_agent import tag_evidence
from ..config import get_settings
from ..models.evidence import Evidence
from ..models.signal import Signal
from ..sources import commodities, market_signals
from ..sources.base import SourceAdapter, SourceStatus
from ..sources.congressional import SenateEfdAdapter
from ..sources.news_marketaux import MarketauxNewsAdapter
from ..sources.official_rss import ADAPTERS as OFFICIAL_RSS_ADAPTERS
from ..sources.reddit_unofficial import RedditUnofficialAdapter
from ..sources.sec_edgar import SecEdgarAdapter
from ..storage.store import get_store
from .dedup import assign_stable_ids, dedup_evidence
from .normalize import normalize
from .router import filter_records
from .scoring import apply_credibility

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


class IngestCancelled(RuntimeError):
    """Raised instead of persisting when the caller's should_stop() is true
    (the background scheduler is shutting down). ``persisted`` counts what was
    already saved before the check, so the caller can report it accurately."""

    def __init__(self, message: str, evidence_saved: int = 0, signals_saved: int = 0) -> None:
        super().__init__(message)
        self.evidence_saved = evidence_saved
        self.signals_saved = signals_saved


StopCheck = Callable[[], bool] | None


def _check_stop(should_stop: StopCheck, stage: str, evidence_saved: int = 0) -> None:
    if should_stop is not None and should_stop():
        raise IngestCancelled(f"cancelled by shutdown before {stage}", evidence_saved=evidence_saved)


def validate_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not SYMBOL_RE.match(normalized):
        raise InvalidSymbolError(f"invalid symbol: {symbol!r}")
    return normalized


@dataclass
class SourceReport:
    """One source's outcome for this run, so substitution is never silent."""

    name: str
    status: SourceStatus
    count: int
    error: str | None = None


@dataclass
class IngestResult:
    evidence: list[Evidence]
    signals: list[Signal]
    sources: list[SourceReport]

    @property
    def any_live(self) -> bool:
        return any(s.status == "live" for s in self.sources)


def ingest_evidence(
    symbol: str, allow_live: bool = True, tag: bool = True, fallback: bool = True,
    should_stop: StopCheck = None,
) -> tuple[list[Evidence], list[SourceReport]]:
    symbol = validate_symbol(symbol)
    all_evidence: list[Evidence] = []
    reports: list[SourceReport] = []

    for adapter in build_adapters():
        result = adapter.fetch_result(symbol, allow_live=allow_live, fallback=fallback)
        records = filter_records(result.items)
        reports.append(SourceReport(adapter.name, result.status, len(records), result.error))
        for record in records:
            all_evidence.append(normalize(record, result.data_mode))

    deduped = dedup_evidence(all_evidence)
    assign_stable_ids(deduped)
    # Score the whole batch (corroboration needs every item), but only tag
    # and store items not already in the store: tagging is a Bedrock call
    # and storing embeds via Akamai, both wasted on rows we already have.
    apply_credibility(deduped)
    store = get_store()
    new_items = store.filter_new_evidence(deduped)
    if tag:
        new_items = [tag_evidence(e) for e in new_items]
    # Last check before the write: a shutting-down scheduler must not persist.
    _check_stop(should_stop, "saving evidence")
    store.save_evidence(new_items)
    return new_items, reports


def ingest_signals(
    symbol: str, allow_live: bool = True, fallback: bool = True,
    should_stop: StopCheck = None, evidence_saved: int = 0,
) -> tuple[list[Signal], list[SourceReport]]:
    symbol = validate_symbol(symbol)
    fetchers = [("market_signals", market_signals.fetch_result)]
    if commodities.is_commodity(symbol):
        fetchers.append(("commodities", commodities.fetch_result))
    signals: list[Signal] = []
    reports: list[SourceReport] = []
    for name, fetch_result in fetchers:
        result = fetch_result(symbol, allow_live=allow_live, fallback=fallback)
        signals += result.items
        reports.append(SourceReport(name, result.status, len(result.items), result.error))
    _check_stop(should_stop, "saving signals", evidence_saved)
    get_store().save_signals(signals)
    return signals, reports


def ingest_symbol(
    symbol: str, allow_live: bool = True, tag: bool = True, fallback: bool = True,
    should_stop: StopCheck = None,
) -> IngestResult:
    """``should_stop`` (optional) is checked immediately before each persist;
    when it returns True, IngestCancelled is raised instead of writing."""
    evidence, ev_reports = ingest_evidence(symbol, allow_live, tag, fallback, should_stop)
    signals, sig_reports = ingest_signals(symbol, allow_live, fallback, should_stop, len(evidence))
    return IngestResult(evidence, signals, ev_reports + sig_reports)


def run_ingestion(symbol: str, allow_live: bool = True, tag: bool = True) -> list[Evidence]:
    return ingest_evidence(symbol, allow_live, tag)[0]


def run_signal_ingestion(symbol: str, allow_live: bool = True) -> list[Signal]:
    return ingest_signals(symbol, allow_live)[0]
