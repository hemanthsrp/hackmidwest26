"""Does a piece of text (headline, post) mention a given stock? Used by
sources that aren't already scoped to one symbol (category RSS feeds,
subreddit listings). Best-effort, and deliberately biased toward missing a
mention over inventing one.

Ticker rules (this used to lowercase everything, so the ticker `A` matched
every headline containing the word "a", `IT` matched "it", `ON` matched
"on"). A ticker is "ambiguous" when it is 1-2 letters or is also a common
English word (`WORD_TICKERS`: ON, ALL, NOW, CAT, OPEN, ...).
- Every form must be bounded: a ticker followed by `.`/`-` + letter or digit
  is a different symbol (`$F.X`, `BRK.B` are not `F` / `BRK`); a plain
  sentence-final period (`shares of $F.`) still matches.
- Cashtags: `$AAPL` matches in any case; for ambiguous tickers only the
  UPPERCASE cashtag counts (`$ON`, not `$on`), and not as a currency amount
  (`$A 50`).
- Exchange-qualified forms always match: "NYSE: F", "(NASDAQ:ON)".
- Parenthesized "(AAPL)" matches; for ambiguous tickers it must follow a
  capitalized, non-enumerator word ("ServiceNow (NOW)", but not "option (A)").
- Bare tickers must be UPPERCASE and 3+ letters ("AAPL moves" matches,
  "aapl" does not, 1-2 letter bare tokens never do). For WORD tickers a bare
  uppercase token additionally needs stock context, because uppercase words
  are routinely used for emphasis or in all-caps headlines ("Act NOW",
  "ALL EYES ON THE FED"): the text must contain lowercase letters, neither
  neighbouring word may itself be all-caps, and the token must be followed by
  a stock word ("ALL stock", "NOW shares") or preceded by "shares of/in".
- Otherwise ambiguous tickers match only via the company name.

Company-name rules:
- Names come from a small curated override table (distinctive short forms
  such as "Alphabet") and, when the SEC ticker file is already cached by the
  SEC adapter, from its company titles with legal suffixes stripped
  ("Apple Inc." -> "Apple"). This module never triggers a download.
- Single-word names that are also ordinary English ("Target", "Visa",
  "Block", "General") are NOT used as names: they would match unrelated
  headlines, so those stocks match by ticker form only.
- A name must appear capitalized as a proper noun (every word starting with
  an uppercase letter, or exactly as written in the table): "Big Lots" and
  "BIG LOTS" match BIG, "big lots of people" and "an apple a day" do not.
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
    "F": "Ford",
    "ON": "ON Semiconductor",
}

# Tickers that are also everyday English words. Bare uppercase use of these is
# usually emphasis, not a stock mention, so they need stronger forms.
WORD_TICKERS = frozenset("""
    ALL ARE CAN NOW BIG HAS OPEN LOW REAL KEY CAR CAT SEE FUN ONE TWO NEW OLD HOT
    YOU YOUR OUR WHO WHY HOW WAY DAY JOB BUY SELL HOLD RUN WIN WELL GOOD BEST MOST
    MAN MEN BOX BIO EAT LIFE LOVE HUGE PLAY RIDE CASH GAIN COST FAST EVER NICE SAVE
    CARS SAFE FLY JET AIR ICE TOP BEAT BILL DOCS TECH FREE HEAR NEAR SPOT
    LAND PEAK PATH TRUE WISH ROAD STAY SKY TEN RARE APP APPS BOOM CUBE DISH EDIT
    GRAB HOME HOOD JOBS MAIN MASS MIND MOVE NEXT PLUG PUMP ROCK ROOT SNOW SOLO
    STEM TELL TREE WORK ZONE ELSE EVEN LIVE LAZY FIVE TALK RENT VERY LOOK
    WAVE DOOR FORM HEAT LION BEAM ARMY
""".split())
_STOCK_WORDS = {
    "stock", "stocks", "share", "shares", "earnings", "options", "calls", "puts", "price",
    "dividend", "dividends", "guidance", "revenue", "results",
}
_ENUMERATOR_WORDS = {
    "option", "options", "step", "figure", "fig", "part", "section", "answer", "choice", "item", "note",
    "table", "appendix", "exhibit", "class", "series", "type", "plan", "grade", "case", "group", "list",
    "point", "question", "and", "or", "the", "of",
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


def is_ambiguous_ticker(symbol: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", symbol)
    return len(letters) <= 2 or symbol.upper() in WORD_TICKERS


# A ticker ends at a non-alphanumeric that is not the start of a class-share
# or suffix ("F.X", "BRK.B", "BRK-B"); a bare trailing "." still ends it.
_END = r"(?![A-Za-z0-9])(?![.-][A-Za-z0-9])"
_START = r"(?<![A-Za-z0-9])(?<![A-Za-z0-9][.-])"


@lru_cache(maxsize=512)
def _forms(symbol: str) -> str:
    forms = {symbol, symbol.replace(".", "-")}
    return "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))


@lru_cache(maxsize=512)
def _ticker_patterns(symbol: str) -> tuple[re.Pattern, ...]:
    alt = _forms(symbol)
    if is_ambiguous_ticker(symbol):
        # uppercase only; 1-2 letter ones also not as a currency amount ("$A 50")
        money = r"(?!\s*\d)" if len(re.sub(r"[^A-Za-z]", "", symbol)) <= 2 else ""
        cashtag = re.compile(rf"(?<![A-Za-z0-9$])\$(?:{alt}){_END}{money}")
    else:
        cashtag = re.compile(rf"(?<![A-Za-z0-9$])\$(?:{alt}){_END}", re.IGNORECASE)
    return (
        cashtag,
        # "(NASDAQ: AAPL)" and "NYSE: F"
        re.compile(rf"(?<![A-Za-z0-9]){_EXCHANGES}\s*:\s*(?:{alt}){_END}"),
    )


@lru_cache(maxsize=512)
def _paren_pattern(symbol: str) -> re.Pattern:
    return re.compile(rf"\(\s*(?:{_forms(symbol)})\s*\)")


@lru_cache(maxsize=512)
def _bare_pattern(symbol: str) -> re.Pattern:
    return re.compile(rf"(?<![A-Za-z0-9$]){_START}(?:{_forms(symbol)}){_END}")


_WORD = re.compile(r"[A-Za-z][A-Za-z'&.-]*")


def _is_caps_word(word: str | None) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", word or "")
    return len(letters) >= 2 and letters.isupper()


def _words_before(text: str, pos: int, n: int) -> list[str]:
    return _WORD.findall(text[:pos])[-n:]


def _word_after(text: str, pos: int) -> str | None:
    m = _WORD.search(text, pos)
    if not m or text[pos:m.start()].strip(" \t,"):  # punctuation in between ends the phrase
        return None
    return m.group()


def _paren_ok(text: str, m: re.Match, ambiguous: bool) -> bool:
    if not ambiguous:
        return True
    prev = _words_before(text, m.start(), 1)
    if not prev or text[:m.start()].rstrip()[-1:] in ".!?:;":
        return False
    word = prev[0]
    return word[0].isupper() and word.lower().strip(".") not in _ENUMERATOR_WORDS


def _bare_ok(text: str, m: re.Match, symbol: str) -> bool:
    if len(re.sub(r"[^A-Za-z]", "", symbol)) < 3:
        return False
    if symbol not in WORD_TICKERS:
        return True
    if not re.search(r"[a-z]", text):  # all-caps headline: every word looks like a ticker
        return False
    before = _words_before(text, m.start(), 2)
    after = _word_after(text, m.end())
    if (before and _is_caps_word(before[-1]) and not text[:m.start()].rstrip().endswith((".", "!", "?", ":"))) \
            or _is_caps_word(after):
        return False  # part of a shouted phrase ("BREAKING: CAN THE RALLY LAST")
    if after and after.lower() in _STOCK_WORDS:
        return True
    return len(before) == 2 and before[0].lower() in {"share", "shares"} and before[1].lower() in {"of", "in"}


@lru_cache(maxsize=512)
def _name_pattern(name: str) -> re.Pattern:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", re.IGNORECASE)


def _proper_noun(found: str, name: str) -> bool:
    if found == name:
        return True
    for word in found.split():
        first = next((ch for ch in word if ch.isalpha()), None)
        if first is not None and not first.isupper():
            return False
    return True


def matches_symbol(text: str, symbol: str) -> bool:
    symbol = symbol.upper()
    if any(p.search(text) for p in _ticker_patterns(symbol)):
        return True
    ambiguous = is_ambiguous_ticker(symbol)
    if any(_paren_ok(text, m, ambiguous) for m in _paren_pattern(symbol).finditer(text)):
        return True
    if any(_bare_ok(text, m, symbol) for m in _bare_pattern(symbol).finditer(text)):
        return True
    name = company_name(symbol)
    return bool(name and any(_proper_noun(m.group(), name) for m in _name_pattern(name).finditer(text)))
