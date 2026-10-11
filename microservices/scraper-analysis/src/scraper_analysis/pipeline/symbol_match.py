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
- Parenthesized "(AAPL)" matches; for ambiguous tickers it is only trusted
  when it directly follows that company's own name, written as a proper noun
  (optionally with a legal suffix): "Ford Motor Co. (F)", "AT&T (T)",
  "ON Semiconductor (ON)" match; "Plan (A)", "Section (F)", "Model (T)",
  "Exhibit (ON)" and "Microsoft (T)" do not.
- Bare tickers must be UPPERCASE and 3+ letters ("AAPL moves" matches,
  "aapl" does not, 1-2 letter bare tokens never do). For WORD tickers a bare
  uppercase token additionally needs stock context, because uppercase words
  are routinely used for emphasis or in all-caps headlines ("Act NOW",
  "ALL EYES ON THE FED"): the text must contain lowercase letters, neither
  neighbouring word may itself be all-caps, and the token must be followed by
  a stock word ("ALL stock", "NOW shares") or preceded by "shares of/in".
  A sentence-initial auxiliary/question word in a question ("CAN stock be
  counted?", "ARE stock buybacks good?") is grammar, not a ticker; "CAN stock
  jumps" and "Is CAN stock a buy?" still match. Known residual ambiguity:
  sentence-initial non-question uses like "NOW stock futures rise" match NOW.
- Otherwise ambiguous tickers match only via the company name.
- Class shares are symmetric across separators: for BRK.B (the pipeline's
  form), BRK-B (SEC's form) or BRK/B, any of "BRK.B", "BRK-B", "BRK/B" in the
  text matches; none of them matches the base BRK, and BRK or BRK.A does not
  match BRK.B.

Company-name rules:
- Names come from a small curated override table (distinctive short forms
  such as "Alphabet", plus aliases like "Ford Motor") and, when the SEC
  ticker file is already cached by the SEC adapter, from its company titles.
  This module never triggers a download.
- An SEC title is reduced ONLY by dropping trailing legal suffixes ("Inc",
  "Corp", "Co", "Ltd", "plc", "Holdings", "Group", "Class B"), EDGAR state /
  "/NEW/" annotations ("/DE/", "/MN") and one leading "The". Nothing else is
  stripped from the front, so the remaining name is matched in full, words in
  order: "New York Times Co" needs "New York Times" (not "York Times"),
  "General Motors Co" needs "General Motors" (not "Motors").
- Names made only of ordinary English / generic business words ("Target",
  "Visa", "News", "Popular", "General", "First National") are NOT used as
  names: they would match unrelated headlines, so those stocks match by
  ticker form only.
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
    # ambiguous (1-2 letter) tickers: the name is what verifies "(X)"
    "A": "Agilent",
    "T": "AT&T",
    "IT": "Gartner",
    "O": "Realty Income",
    "NOW": "ServiceNow",
}

# Extra curated names (longer official forms) accepted alongside the hint.
SYMBOL_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "F": ("Ford Motor",),
    "A": ("Agilent Technologies",),
    "ON": ("onsemi",),
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

# Stripped from the END of an SEC title only (never from the front).
_LEGAL_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "cos", "companies", "ltd", "limited",
    "plc", "llc", "lp", "llp", "holdings", "holding", "group", "sa", "nv", "ag", "se", "com",
}
# Words that are generic on their own; a name made ONLY of these (or of the
# words below) is never used, e.g. "First National", "American Financial".
_GENERIC_NAME_WORDS = {
    "bank", "banc", "bancorp", "bancshares", "financial", "trust", "industries",
    "systems", "technologies", "technology", "solutions", "services", "resources", "partners", "brands",
    "foods", "entertainment", "media", "communications", "networks", "pharmaceuticals", "therapeutics",
    "sciences", "realty", "properties", "insurance", "mortgage", "investment", "investments", "investors",
    "equity", "income", "fund", "news", "popular", "progressive", "interactive", "new", "of", "and", "&",
    "america", "usa", "us", "north", "south", "east", "west", "mutual", "savings", "federal", "state",
    "standard", "general", "american", "united", "first", "national", "union", "royal", "great",
}
# One-word names that are everyday words; matching them as names is noise.
_AMBIGUOUS_NAMES = _GENERIC_NAME_WORDS | {
    "motor", "motors",
    "target", "visa", "block", "gap", "general", "american", "united", "first", "national", "southern",
    "western", "eastern", "global", "international", "digital", "energy", "financial", "health", "medical",
    "capital", "public", "community", "home", "central", "atlas", "cardinal", "genuine", "continental",
    "pacific", "northern", "universal", "premier", "select", "spirit", "frontier", "delta", "summit",
    "sun", "carrier", "ally", "key", "square", "snap", "match", "live", "wolf", "gold", "silver", "ross",
    "kohl", "best", "dollar", "wayfair", "paramount", "discovery", "hess", "mosaic", "waters", "rocket",
}
MIN_NAME_LENGTH = 4
_EXCHANGES = r"(?:NASDAQ|NYSE|NYSEARCA|NYSEAMERICAN|AMEX|OTC|TSX)"


def _title_tokens(title: str | None) -> list[str]:
    """SEC title -> name tokens with only legal suffixes, EDGAR annotations and
    a leading "The" removed. Nothing else is ever stripped from the front."""
    if not title:
        return []
    title = re.sub(r"/[A-Za-z]{1,4}/?", " ", title)  # "/DE/", "/NEW/", "Company/MN"
    tokens = re.findall(r"[A-Za-z0-9&'-]+", title)
    while tokens:
        last = tokens[-1].lower()
        if last in _LEGAL_SUFFIXES or last in {"&", "and"}:
            tokens.pop()
        elif len(tokens) >= 2 and tokens[-2].lower() == "class" and len(tokens[-1]) == 1:
            del tokens[-2:]  # "Class B"
        else:
            break
    if len(tokens) > 1 and tokens[0].lower() == "the":
        tokens.pop(0)
    return tokens


def distinctive_name(title: str | None) -> str | None:
    """'Apple Inc.' -> 'Apple'; 'Berkshire Hathaway Inc.' -> 'Berkshire Hathaway';
    'New York Times Co' -> 'New York Times'; ambiguous, generic or too-short
    names -> None."""
    tokens = _title_tokens(title)
    name = " ".join(tokens)
    if len(name) < MIN_NAME_LENGTH:
        return None
    if len(tokens) == 1 and name.lower() in _AMBIGUOUS_NAMES:
        return None
    if all(t.lower() in _GENERIC_NAME_WORDS or t.isdigit() for t in tokens):
        return None
    return name


def company_name(symbol: str) -> str | None:
    hint = SYMBOL_NAME_HINTS.get(symbol.upper())
    return hint or distinctive_name(sec_tickers.cached_title(symbol))


def company_names(symbol: str) -> tuple[str, ...]:
    """Every name that counts as a mention of the company: curated hint and
    aliases, plus the SEC-derived distinctive name when the table is cached."""
    symbol = symbol.upper()
    names = [SYMBOL_NAME_HINTS.get(symbol), *SYMBOL_NAME_ALIASES.get(symbol, ()),
             distinctive_name(sec_tickers.cached_title(symbol))]
    return tuple(dict.fromkeys(n for n in names if n))


def _verifying_names(symbol: str) -> tuple[str, ...]:
    """Names that may verify an adjacent "(X)". Right next to the ticker even
    a generic SEC name ("Visa (V)") is strong evidence, so it is allowed here."""
    sec_name = " ".join(_title_tokens(sec_tickers.cached_title(symbol)))
    return tuple(dict.fromkeys(n for n in (*company_names(symbol), sec_name) if len(n) >= 2))


def is_ambiguous_ticker(symbol: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", symbol)
    return len(letters) <= 2 or symbol.upper() in WORD_TICKERS


# A ticker ends at a non-alphanumeric that is not the start of a class-share
# or suffix ("F.X", "BRK.B", "BRK-B", "BRK/B"); a bare trailing "." still ends
# it. "/" only counts when followed by a 1-2 letter class ("AAPL/MSFT" is a pair).
_END = r"(?![A-Za-z0-9])(?![.-][A-Za-z0-9])(?!/[A-Za-z]{1,2}(?![A-Za-z0-9]))"
_START = r"(?<![A-Za-z0-9])(?<![A-Za-z0-9][.-])"


_CLASS_SHARE = re.compile(r"([A-Z0-9]+)[./-]([A-Z]{1,2})")


def normalize_symbol(symbol: str) -> str:
    """Upper-case; class shares in the pipeline's dotted form ("BRK-B",
    "brk/b" -> "BRK.B")."""
    symbol = symbol.strip().upper()
    m = _CLASS_SHARE.fullmatch(symbol)
    return f"{m.group(1)}.{m.group(2)}" if m else symbol


@lru_cache(maxsize=512)
def _forms(symbol: str) -> str:
    m = _CLASS_SHARE.fullmatch(symbol)
    if m:  # every way a class share is written
        forms = {f"{m.group(1)}{sep}{m.group(2)}" for sep in ".-/"}
    else:
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


_TRAILING_SUFFIX = re.compile(r"[\s,]*(?<![A-Za-z0-9])([A-Za-z]+)\.?$")


def _paren_ok(text: str, m: re.Match, symbol: str, ambiguous: bool) -> bool:
    if not ambiguous:
        return True
    # Ambiguous "(X)" is only trusted right after the company's own name:
    # "Ford Motor Co. (F)" yes, "Plan (A)" / "Model (T)" / "Exhibit (ON)" no.
    before = text[:m.start()].rstrip()
    while (suffix := _TRAILING_SUFFIX.search(before)) and suffix.group(1).lower() in _LEGAL_SUFFIXES:
        before = before[:suffix.start()].rstrip(" ,")
    for name in _verifying_names(symbol):
        found = re.search(rf"(?<![A-Za-z0-9&]){re.escape(name)}$", before, re.IGNORECASE)
        if found and _proper_noun(found.group(), name):
            return True
    return False


# Word tickers that open English questions ("CAN stock be counted?").
_QUESTION_WORDS = frozenset({"CAN", "ARE", "HAS", "HOW", "WHY", "WHO"})


def _starts_question(text: str, m: re.Match) -> bool:
    """The token opens a sentence (or follows "Label:") that ends in "?"."""
    if text[:m.start()].rstrip() and not text[:m.start()].rstrip().endswith((".", "!", "?", ":")):
        return False
    end = re.search(r"[.!?]", text[m.end():])
    return bool(end) and end.group() == "?"


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
        return not (symbol in _QUESTION_WORDS and _starts_question(text, m))
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
    symbol = normalize_symbol(symbol)
    if any(p.search(text) for p in _ticker_patterns(symbol)):
        return True
    ambiguous = is_ambiguous_ticker(symbol)
    if any(_paren_ok(text, m, symbol, ambiguous) for m in _paren_pattern(symbol).finditer(text)):
        return True
    if any(_bare_ok(text, m, symbol) for m in _bare_pattern(symbol).finditer(text)):
        return True
    return any(_proper_noun(m.group(), name)
               for name in company_names(symbol) for m in _name_pattern(name).finditer(text))
