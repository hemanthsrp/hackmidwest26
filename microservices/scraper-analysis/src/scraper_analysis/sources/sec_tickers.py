"""SEC's ticker -> CIK/company-name file, cached.

The SEC adapter used to download this ~1.5 MB file in full on every single
ingest just to find one CIK. SEC's fair-access guidance asks automated
clients to keep request volume down, so it is now fetched at most once per
TTL per process. The company names in it also feed ticker/name matching for
sources that aren't scoped to one symbol (pipeline/symbol_match.py), which
only ever READS the cache and never triggers a download itself.
"""

import time
from dataclasses import dataclass

import httpx

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
TTL_SECONDS = 24 * 3600


@dataclass(frozen=True)
class TickerInfo:
    cik: int
    title: str


_cache: tuple[float, dict[str, TickerInfo]] | None = None


def _parse(raw: dict) -> dict[str, TickerInfo]:
    table: dict[str, TickerInfo] = {}
    for entry in raw.values():
        ticker = str(entry.get("ticker", "")).upper()
        if ticker and "cik_str" in entry:
            table.setdefault(ticker, TickerInfo(int(entry["cik_str"]), str(entry.get("title", ""))))
    return table


def load(client: httpx.Client) -> dict[str, TickerInfo]:
    global _cache
    if _cache is not None and time.monotonic() - _cache[0] < TTL_SECONDS:
        return _cache[1]
    resp = client.get(TICKERS_URL)
    resp.raise_for_status()
    table = _parse(resp.json())
    _cache = (time.monotonic(), table)
    return table


def lookup(symbol: str, client: httpx.Client) -> TickerInfo | None:
    return load(client).get(symbol.upper())


def cached_title(symbol: str) -> str | None:
    """Company title if (and only if) the table is already loaded: pure,
    never touches the network."""
    if _cache is None:
        return None
    info = _cache[1].get(symbol.upper())
    return info.title if info else None
