import json
import re
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

# Any URL's query string or userinfo can carry credentials (MarketAux puts
# api_token in the query; DATABASE_URL carries a password). Upstream error
# text routinely embeds the request URL (httpx: "Client error '401' for url
# 'https://...?api_token=...'"), so it is never returned verbatim.
_URL_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^\s'\"<>]+)")
_SECRET_PARAM_RE = re.compile(
    r"(?i)\b(api[_-]?token|api[_-]?key|access[_-]?key|token|key|secret|password|passwd|sig|signature)=([^&\s'\"]+)"
)
_SECRET_SETTINGS = (
    "news_api_key",
    "noaa_cdo_token",
    "akamai_inference_api_key",
    "aws_access_key_id",
    "aws_secret_access_key",
    "aws_session_token",
    "database_url",
)
MAX_ERROR_CHARS = 300


def _redact_url(match: re.Match) -> str:
    scheme, rest = match.group(1), match.group(2)
    rest = re.sub(r"^[^/@]*@", "", rest)  # drop user:password@
    base = rest.split("?", 1)[0].split("#", 1)[0]
    return f"{scheme}{base}" + ("?<redacted>" if "?" in rest else "")


def sanitize_error(error: object) -> str:
    """Make upstream error text safe to return to API clients or logs:
    strip URL query strings and credentials, mask key=value secrets, and
    remove any configured secret values that still appear verbatim."""
    text = str(error)
    text = _URL_RE.sub(_redact_url, text)
    text = _SECRET_PARAM_RE.sub(lambda m: f"{m.group(1)}=<redacted>", text)
    try:
        from ..config import get_settings

        settings = get_settings()
        for name in _SECRET_SETTINGS:
            value = getattr(settings, name, None)
            if value and len(value) >= 4:
                text = text.replace(value, "<redacted>")
    except ValueError:  # invalid settings (pydantic ValidationError) must not break error reporting
        return text[:MAX_ERROR_CHARS]
    if len(text) > MAX_ERROR_CHARS:
        text = text[:MAX_ERROR_CHARS] + "..."
    return text


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
        error = sanitize_error(exc)
        if fallback:
            return FetchResult(sample_fn(), "sample", "fallback", error)
        return FetchResult([], "live", "unavailable", error)


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
