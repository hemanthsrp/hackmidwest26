import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Literal

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"


class SourceUnavailableError(Exception):
    """Raised by an adapter when the live source cannot be reached or
    returns an unusable response. Callers should fall back to fixtures
    rather than let this propagate to the API layer."""


SourceStatus = Literal["live", "sample", "fallback", "unavailable"]


@dataclass
class FetchResult:
    """What a fetch actually did. `status` keeps substitution visible:
    live      real source answered
    sample    fixtures, because the caller asked for them (live=false)
    fallback  live failed and fixtures were substituted (data_mode "sample")
    unavailable  live failed and the caller refused fixtures (no items)"""

    items: list
    data_mode: str
    status: SourceStatus
    error: str | None = None


def resolve(live_fn, sample_fn, allow_live: bool, fallback: bool) -> FetchResult:
    if not allow_live:
        return FetchResult(sample_fn(), "sample", "sample")
    try:
        return FetchResult(live_fn(), "live", "live")
    except SourceUnavailableError as exc:
        if fallback:
            return FetchResult(sample_fn(), "sample", "fallback", str(exc))
        return FetchResult([], "live", "unavailable", str(exc))


@dataclass
class RawRecord:
    source_name: str
    source_type: str
    symbol: str
    payload: dict[str, Any]
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: datetime | None = None
    observed_at: datetime | None = None
    url: str | None = None


class SourceAdapter(ABC):
    name: ClassVar[str]
    source_type: ClassVar[str]
    fixture_file: ClassVar[str]

    @abstractmethod
    def fetch_live(self, symbol: str) -> list[RawRecord]:
        """Hit the real upstream source. Raise SourceUnavailableError on any
        network/auth/parse failure -- never raise anything else out of here."""

    def fetch_sample(self, symbol: str) -> list[RawRecord]:
        records = load_fixture(self.fixture_file)
        now = datetime.now(timezone.utc)
        return [
            RawRecord(
                source_name=self.name,
                source_type=self.source_type,
                symbol=symbol,
                payload=raw,
                retrieved_at=now,
                published_at=_parse_dt(raw.get("published_at")),
                observed_at=_parse_dt(raw.get("observed_at")) or _parse_dt(raw.get("published_at")),
                url=raw.get("url"),
            )
            for raw in records
            if raw.get("symbol", symbol).upper() == symbol.upper()
        ]

    def fetch_result(self, symbol: str, allow_live: bool = True, fallback: bool = True) -> "FetchResult":
        return resolve(
            lambda: self.fetch_live(symbol), lambda: self.fetch_sample(symbol), allow_live, fallback
        )

    def fetch(self, symbol: str, allow_live: bool = True) -> tuple[list[RawRecord], str]:
        """Returns (records, data_mode). Tries live first (if allowed), and
        falls back to labeled fixtures on failure so the demo survives an
        upstream outage. Callers that must not accept that substitution use
        fetch_result(fallback=False) and read the status instead."""
        result = self.fetch_result(symbol, allow_live)
        return result.items, result.data_mode


def load_fixture(filename: str) -> list[dict[str, Any]]:
    path = FIXTURES_DIR / filename
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
