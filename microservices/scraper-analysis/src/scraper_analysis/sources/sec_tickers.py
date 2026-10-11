"""SEC's ticker -> CIK/company-name file, cached.

The SEC adapter used to download this ~1.5 MB file in full on every single
ingest just to find one CIK. SEC's fair-access guidance asks automated
clients to keep request volume down, so it is now fetched at most once per
TTL per process. The company names in it also feed ticker/name matching for
sources that aren't scoped to one symbol (pipeline/symbol_match.py), which
only ever READS the cache and never triggers a download itself.

Loading is single-flight: concurrent cold lookups (e.g. parallel ingests)
share one download instead of each fetching the file. A failed, malformed or
empty download (no usable ticker entries) is not cached, so the next lookup
retries instead of serving an empty table for a whole TTL; malformed and
empty tables raise fixed ValueError messages (never the response body).
"""

import threading
import time
from dataclasses import dataclass

import httpx

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
TTL_SECONDS = 24 * 3600


@dataclass(frozen=True)
class TickerInfo:
    cik: int
    title: str


MALFORMED_MESSAGE = "SEC company_tickers.json was malformed"
EMPTY_MESSAGE = "SEC company_tickers.json had no usable entries"

_cache: tuple[float, dict[str, TickerInfo]] | None = None
_load_lock = threading.Lock()


def _parse(raw: dict) -> dict[str, TickerInfo]:
    if not isinstance(raw, dict):
        raise ValueError(MALFORMED_MESSAGE)
    table: dict[str, TickerInfo] = {}
    for entry in raw.values():
        if not isinstance(entry, dict):
            continue
        ticker = str(entry.get("ticker", "")).upper()
        if ticker and "cik_str" in entry:
            try:
                cik = int(entry["cik_str"])
            except (TypeError, ValueError):
                continue
            table.setdefault(ticker, TickerInfo(cik, str(entry.get("title", ""))))
    if not table:  # a 200 with {} (or only junk) is an outage, not "no tickers exist"
        raise ValueError(EMPTY_MESSAGE)
    return table


def _fresh() -> dict[str, TickerInfo] | None:
    cached = _cache
    if cached is not None and time.monotonic() - cached[0] < TTL_SECONDS:
        return cached[1]
    return None


def load(client: httpx.Client) -> dict[str, TickerInfo]:
    global _cache
    table = _fresh()
    if table is not None:
        return table
    with _load_lock:  # single-flight: re-check once we hold the lock
        table = _fresh()
        if table is not None:
            return table
        resp = client.get(TICKERS_URL)
        resp.raise_for_status()
        try:
            raw = resp.json()
        except ValueError:
            raise ValueError(MALFORMED_MESSAGE) from None
        table = _parse(raw)
        _cache = (time.monotonic(), table)
        return table


def lookup(symbol: str, client: httpx.Client) -> TickerInfo | None:
    return load(client).get(symbol.upper())


def cached_title(symbol: str) -> str | None:
    """Company title if (and only if) the table is already loaded: pure,
    never touches the network."""
    cached = _cache
    if cached is None:
        return None
    info = cached[1].get(symbol.upper())
    return info.title if info else None
