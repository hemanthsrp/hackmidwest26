import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"


class SourceUnavailableError(Exception):
    """Raised by an adapter when the live source cannot be reached or
    returns an unusable response. Callers should fall back to fixtures
    rather than let this propagate to the API layer."""


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

    def fetch(self, symbol: str, allow_live: bool = True) -> tuple[list[RawRecord], str]:
        """Returns (records, data_mode). Tries live first (if allowed and
        configured), falls back to deterministic fixtures on any failure so
        the demo never breaks when an upstream source is down."""
        if allow_live:
            try:
                return self.fetch_live(symbol), "live"
            except SourceUnavailableError:
                pass
        return self.fetch_sample(symbol), "sample"


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
