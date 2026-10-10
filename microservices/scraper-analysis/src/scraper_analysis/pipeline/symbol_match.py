"""Shared ticker/company-name matching for sources that aren't already
scoped to one symbol (general feeds, subreddit listings). Best-effort
recall, not a full ticker database -- a documented limitation, not hidden."""

import re

# Small curated ticker -> company-name hint table. Extend as demo symbols
# are added.
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


def matches_symbol(text: str, symbol: str) -> bool:
    haystack = text.lower()
    if re.search(rf"\b\$?{re.escape(symbol.lower())}\b", haystack):
        return True
    hint = SYMBOL_NAME_HINTS.get(symbol.upper())
    return bool(hint and hint.lower() in haystack)
