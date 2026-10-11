"""Does a piece of text (headline, post) mention a given stock? Used by
sources that aren't already scoped to one symbol (category RSS feeds,
subreddit listings). Best-effort, and deliberately biased toward missing a
mention over inventing one.

Ticker rules (this used to lowercase everything, so the ticker `A` matched
every headline containing the word "a", `IT` matched "it", `ON` matched
"on"):
- Cashtags ($AAPL) match case-insensitively.
- Parenthesized or exchange-prefixed forms match: "(AAPL)", "(NASDAQ: AAPL)",
  "NYSE: F".
- A bare ticker must be written in UPPERCASE and be 3+ letters ("AAPL moves"
  matches; "aapl", and any 1-2 letter bare token, do not). Short tickers
  therefore need a cashtag, an exchange form, or a company-name hit.

Company-name rules:
- Names come from a small curated override table (distinctive short forms
  such as "Alphabet") and, when the SEC ticker file is already cached by the
  SEC adapter, from its company titles with legal suffixes stripped
  ("Apple Inc." -> "Apple"). This module never triggers a download.
- Single-word names that are also ordinary English ("Target", "Visa",
  "Block", "General") are NOT used as names: they would match unrelated
  headlines, so those stocks match by ticker form only.
"""

import re
from functools import lru_cache

from ..sources import sec_tickers

# Curated distinctive short names; checked before the SEC-derived name.
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

_LEGAL_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "llc",
    "lp", "holdings", "holding", "group", "the", "de", "sa", "nv", "ag", "com", "class", "new",
}
# One-word names that are everyday words; matching them as names is noise.
_AMBIGUOUS_NAMES = {
    "target", "visa", "block", "gap", "general", "american", "united", "first", "national", "southern",
    "western", "eastern", "global", "international", "digital", "energy", "financial", "health", "medical",
    "capital", "public", "community", "home", "central", "atlas", "cardinal", "genuine", "continental",
    "pacific", "northern", "universal", "premier", "select", "spirit", "frontier", "delta", "summit",
    "sun", "carrier", "ally", "key", "square", "snap", "match", "live", "wolf", "gold", "silver", "ross",
    "kohl", "best", "dollar", "wayfair", "paramount", "discovery", "hess", "mosaic", "waters", "rocket",
}
MIN_NAME_LENGTH = 4
_EXCHANGES = r"(?:NASDAQ|NYSE|NYSEARCA|NYSEAMERICAN|AMEX|OTC|TSX)"


def distinctive_name(title: str | None) -> str | None:
    """'Apple Inc.' -> 'Apple'; 'Berkshire Hathaway Inc.' -> 'Berkshire Hathaway';
    ambiguous or too-short names -> None."""
    if not title:
        return None
    tokens = re.findall(r"[A-Za-z0-9&'-]+", title)
    while tokens and tokens[-1].lower() in _LEGAL_SUFFIXES:
        tokens.pop()
    while tokens and tokens[0].lower() in _LEGAL_SUFFIXES:
        tokens.pop(0)
    name = " ".join(tokens)
    if len(name) < MIN_NAME_LENGTH:
        return None
    if len(tokens) == 1 and name.lower() in _AMBIGUOUS_NAMES:
        return None
    return name


def company_name(symbol: str) -> str | None:
    hint = SYMBOL_NAME_HINTS.get(symbol.upper())
    return hint or distinctive_name(sec_tickers.cached_title(symbol))


@lru_cache(maxsize=512)
def _ticker_patterns(symbol: str) -> tuple[re.Pattern, ...]:
    forms = {symbol, symbol.replace(".", "-")}
    alt = "|".join(re.escape(f) for f in sorted(forms))
    patterns = [
        # cashtag, any case
        re.compile(rf"(?<![A-Za-z0-9])\${alt}(?![A-Za-z0-9])", re.IGNORECASE),
        # "(AAPL)" / "(NASDAQ: AAPL)" and "NYSE: F"
        re.compile(rf"\(\s*(?:{_EXCHANGES}\s*:\s*)?(?:{alt})\s*\)"),
        re.compile(rf"\b{_EXCHANGES}\s*:\s*(?:{alt})(?![A-Za-z0-9])"),
    ]
    if len(symbol) >= 3:
        # bare mention: uppercase only, so "aapl" / ordinary words never match
        patterns.append(re.compile(rf"(?<![A-Za-z0-9$.-])(?:{alt})(?![A-Za-z0-9])"))
    return tuple(patterns)


@lru_cache(maxsize=512)
def _name_pattern(name: str) -> re.Pattern:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", re.IGNORECASE)


def matches_symbol(text: str, symbol: str) -> bool:
    symbol = symbol.upper()
    if any(p.search(text) for p in _ticker_patterns(symbol)):
        return True
    name = company_name(symbol)
    return bool(name and _name_pattern(name).search(text))
