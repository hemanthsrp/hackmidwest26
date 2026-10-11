"""SEC's ticker -> CIK/company-name file, cached.

The SEC adapter used to download this ~1.5 MB file in full on every single
ingest just to find one CIK. SEC's fair-access guidance asks automated
clients to keep request volume down, so it is now fetched at most once per
TTL per process. The company names in it also feed ticker/name matching for
sources that aren't scoped to one symbol (pipeline/symbol_match.py), which
only ever READS the cache and never triggers a download itself.

Loading is single-flight: concurrent cold lookups (e.g. parallel ingests)
share one download instead of each fetching the file.

Only a table that looks like SEC's real file is cached. A download is a
failed load (not cached, so the next lookup retries; fixed ValueError text,
never the response body) when:
- the response is served as HTML, or the body is not JSON / not a JSON object
  (null, list, string, ...), or it has more than MAX_ENTRIES rows;
- ANY row is structurally corrupt: a row that is not an object, or a present
  field of the wrong type (ticker not a string starting with a letter --
  "123", "1ABC", "", "  " included, same as a numeric ticker --, cik_str not a
  positive int / digit string -- bools and floats rejected, title not a
  string). Real SEC rows are uniform, so one such row means the body is not
  the table we expect;
- fewer than MIN_USABLE_FRACTION of rows are usable (rows merely missing
  cik_str/ticker are skipped individually, but a table that is mostly such
  rows is corrupt);
- no row is usable at all (EMPTY_MESSAGE).

Class shares are keyed "BRK-B" by SEC but written "BRK.B" by the pipeline
(ingest.SYMBOL_RE) and "BRK/B" in some press; lookups accept any of them.
"""

import re
import threading
import time
from dataclasses import dataclass

import httpx

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
TTL_SECONDS = 24 * 3600
MAX_ENTRIES = 200_000  # the real file has ~10k rows
MIN_USABLE_FRACTION = 0.75


@dataclass(frozen=True)
class TickerInfo:
    cik: int
    title: str


MALFORMED_MESSAGE = "SEC company_tickers.json was malformed"
EMPTY_MESSAGE = "SEC company_tickers.json had no usable entries"

_cache: tuple[float, dict[str, TickerInfo]] | None = None
_load_lock = threading.Lock()


# THE ticker-shape rule, applied in exactly one place (_row): a letter first,
# then letters/digits/class separators. Loose enough for every real SEC ticker
# ("BRK-B", "GAB-PG", even "NONE." which is in the live file) because one
# failing row rejects the whole table; anything else ("123", "1ABC", "", "  ",
# "-X", markup) is structural corruption, never a skipped row.
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-/]{0,19}$")
_CLASS_SEP = re.compile(r"[./]")


class _Corrupt(Exception):
    pass


def _cik(value) -> int:
    if isinstance(value, bool):
        raise _Corrupt
    if isinstance(value, int):
        cik = value
    elif isinstance(value, str) and value.strip().isdigit():
        cik = int(value)
    else:
        raise _Corrupt
    if cik <= 0:
        raise _Corrupt
    return cik


def _row(entry) -> tuple[str, TickerInfo] | None:
    """(ticker, info) for a usable row, None for a row merely missing a
    field; raises _Corrupt for a row that is structurally wrong."""
    if not isinstance(entry, dict):
        raise _Corrupt
    ticker, title = entry.get("ticker"), entry.get("title", "")
    if "ticker" in entry:  # null / number / "123" / "  " / markup is corruption, not a ticker
        if not isinstance(ticker, str):
            raise _Corrupt
        ticker = ticker.strip().upper()
        if not _TICKER_RE.match(ticker):
            raise _Corrupt
    if not isinstance(title, str):
        raise _Corrupt
    cik = _cik(entry["cik_str"]) if "cik_str" in entry else None
    if ticker is None or cik is None:  # only a MISSING field skips a row
        return None
    return ticker, TickerInfo(cik, title)


def _parse(raw) -> dict[str, TickerInfo]:
    if not isinstance(raw, dict) or len(raw) > MAX_ENTRIES:
        raise ValueError(MALFORMED_MESSAGE)
    table: dict[str, TickerInfo] = {}
    usable = 0
    corrupt = False
    for entry in raw.values():
        try:
            row = _row(entry)
        except _Corrupt:
            corrupt = True
            continue
        if row is not None:
            usable += 1
            table.setdefault(*row)
    if not table:  # a 200 with {} (or only junk) is an outage, not "no tickers exist"
        raise ValueError(EMPTY_MESSAGE)
    if corrupt or usable < MIN_USABLE_FRACTION * len(raw):
        raise ValueError(MALFORMED_MESSAGE)
    return table


def _get(table: dict[str, TickerInfo], symbol: str) -> TickerInfo | None:
    """Exact ticker, else the same class share with SEC's "-" separator."""
    symbol = symbol.strip().upper()
    return table.get(symbol) or table.get(_CLASS_SEP.sub("-", symbol)) \
        or table.get(symbol.replace("-", ".").replace("/", "."))


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
        headers = getattr(resp, "headers", None) or {}
        if "html" in str(headers.get("content-type", "")).lower():
            raise ValueError(MALFORMED_MESSAGE)  # an error page, whatever it contains
        try:
            raw = resp.json()
        except ValueError:
            raise ValueError(MALFORMED_MESSAGE) from None
        table = _parse(raw)
        _cache = (time.monotonic(), table)
        return table


def lookup(symbol: str, client: httpx.Client) -> TickerInfo | None:
    return _get(load(client), symbol)


def cached_title(symbol: str) -> str | None:
    """Company title if (and only if) the table is already loaded: pure,
    never touches the network."""
    cached = _cache
    if cached is None:
        return None
    info = _get(cached[1], symbol)
    return info.title if info else None
