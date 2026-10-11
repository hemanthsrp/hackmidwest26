import pytest

from scraper_analysis.pipeline import symbol_match as sm
from scraper_analysis.pipeline.symbol_match import matches_symbol
from scraper_analysis.sources import sec_tickers


def test_matches_literal_ticker():
    assert matches_symbol("AAPL moves on earnings", "AAPL") is True


def test_matches_cashtag():
    assert matches_symbol("Loading up on $NVDA calls", "NVDA") is True


def test_matches_company_name_hint():
    assert matches_symbol("Apple supplier flags constraints", "AAPL") is True


def test_no_match_for_unrelated_text():
    assert matches_symbol("Totally unrelated headline about oil prices", "AAPL") is False


def test_does_not_substring_match_inside_other_words():
    # "AAPL" should not match inside "AAPLE" or similar -- word boundary required
    assert matches_symbol("AAPLE is not a real ticker", "AAPL") is False


# --- short-ticker false matches (the original bug) ---------------------------

@pytest.mark.parametrize("text,symbol", [
    ("A big day for markets as stocks rally", "A"),
    ("Why it is time to buy the dip", "IT"),
    ("Markets close higher on Friday", "ON"),
    ("Oil prices: a look at crude", "C"),
    ("go all in on the rally", "ALL"),  # lowercase "all" is not the Allstate ticker
    ("Right now investors wait", "NOW"),
])
def test_ordinary_words_never_match_a_ticker(text, symbol):
    assert matches_symbol(text, symbol) is False


@pytest.mark.parametrize("text,symbol", [
    ("Traders pile into $F ahead of earnings", "F"),
    ("Agilent Technologies (A) beats estimates", "A"),
    ("Ford Motor (NYSE: F) recalls trucks", "F"),
    ("Gartner (NYSE:IT) raises outlook", "IT"),
    ("ServiceNow (NOW) climbs", "NOW"),
    ("Why ALL stock fell today", "ALL"),
    ("loading $nvda calls", "NVDA"),  # cashtags are case-insensitive
])
def test_explicit_ticker_forms_match(text, symbol):
    assert matches_symbol(text, symbol) is True


def test_bare_lowercase_ticker_does_not_match():
    assert matches_symbol("aapl to the moon", "AAPL") is False


def test_dotted_ticker_forms():
    assert matches_symbol("Berkshire (BRK-B) hits a record", "BRK.B") is True
    assert matches_symbol("Buying $BRK.B today", "BRK.B") is True


def test_ticker_is_not_matched_inside_longer_tokens():
    assert matches_symbol("AAPLE is not a ticker", "AAPL") is False


# --- company names -----------------------------------------------------------

@pytest.fixture
def sec_table(monkeypatch):
    table = {
        "ADBE": sec_tickers.TickerInfo(796343, "Adobe Inc."),
        "TGT": sec_tickers.TickerInfo(27419, "Target Corp"),
        "V": sec_tickers.TickerInfo(1403161, "Visa Inc."),
        "BRK.B": sec_tickers.TickerInfo(1067983, "Berkshire Hathaway Inc"),
        "X": sec_tickers.TickerInfo(1, "X"),
    }
    import time
    monkeypatch.setattr(sec_tickers, "_cache", (time.monotonic(), table))
    return table


@pytest.mark.parametrize("title,expected", [
    ("Apple Inc.", "Apple"),
    ("Microsoft Corp", "Microsoft"),
    ("Amazon.com, Inc.", "Amazon"),
    ("Berkshire Hathaway Inc.", "Berkshire Hathaway"),
    ("The Home Depot, Inc.", "Home Depot"),
    ("NVIDIA CORP", "NVIDIA"),
])
def test_distinctive_name_strips_legal_suffixes(title, expected):
    assert sm.distinctive_name(title) == expected


@pytest.mark.parametrize("title", ["Target Corp", "Visa Inc.", "Block, Inc.", "Gap Inc", "X", None, ""])
def test_ambiguous_or_tiny_names_are_not_used(title):
    assert sm.distinctive_name(title) is None


def test_names_come_from_the_sec_table_for_symbols_without_a_hint(sec_table):
    assert matches_symbol("Adobe unveils new creative tools", "ADBE") is True
    assert matches_symbol("Berkshire Hathaway posts record cash pile", "BRK.B") is True


def test_ambiguous_names_do_not_match_everyday_headlines(sec_table):
    assert matches_symbol("Analysts cut price target on chipmaker", "TGT") is False
    assert matches_symbol("New visa rules hit travel", "V") is False
    assert matches_symbol("Target (NYSE: TGT) lifts guidance", "TGT") is True


def test_curated_hint_wins_over_sec_title(sec_table):
    assert sm.company_name("AAPL") == "Apple"


def test_matching_never_downloads_anything(monkeypatch):
    monkeypatch.setattr(sec_tickers, "_cache", None)

    def boom(*a, **k):
        raise AssertionError("symbol matching must not hit the network")

    monkeypatch.setattr(sec_tickers.httpx.Client, "get", boom)
    assert matches_symbol("Adobe news", "ADBE") is False  # no cache, no hint: ticker forms only
    assert matches_symbol("Adobe (ADBE) news", "ADBE") is True


# --- PR #18 review (hbot): ordinary words must not match word tickers --------

WORD_TICKERS = [
    "ON", "IT", "ALL", "ARE", "CAN", "NOW", "BIG", "A", "F", "O", "T", "GO", "BE", "SO",
    "HAS", "OPEN", "LOW", "REAL", "KEY", "CAR", "CAT", "SEE", "FUN",
]
ORDINARY_SENTENCES = [
    "it is on now",
    "IT IS ON NOW",
    "Is NOW the time to buy?",
    "ALL EYES ON THE FED AS RATES HOLD",
    "BREAKING: CAN THE RALLY LAST?",
    "This is BIG news for savers",
    "Act NOW before it is too late",
    "We ARE open late; doors OPEN at 9",
    "Prices are at a LOW and it is REAL",
    "The KEY question: SEE you at the CAR show, it was FUN",
    "A CAT can GO where it wants, SO BE it, it HAS to",
    "Choose option (A) or (B)",
    "big lots of people go out on a real low budget",
    "Costs $A 50 in Sydney",
    "the $all variable and $on handler",
]


@pytest.mark.parametrize("symbol", WORD_TICKERS)
@pytest.mark.parametrize("text", ORDINARY_SENTENCES)
def test_ordinary_prose_never_matches_word_tickers(text, symbol):
    assert matches_symbol(text, symbol) is False


@pytest.mark.parametrize("text,symbol", [
    ("Traders pile into $ON after guidance", "ON"),
    ("onsemi rival? NASDAQ:ON jumps 8%", "ON"),
    ("ON Semiconductor beats estimates", "ON"),
    ("Ford Motor (NYSE: F) recalls trucks", "F"),
    ("Ford recalls 100,000 trucks", "F"),
    ("Why ALL stock fell today", "ALL"),
    ("Buying more shares of NOW after the dip", "NOW"),
    ("ServiceNow (NOW) climbs", "NOW"),
    ("Realty Income (NYSE: O) raises its dividend", "O"),
    ("AT&T (T) adds subscribers", "T"),
    ("$CAT hits record on infrastructure bill", "CAT"),
])
def test_real_headlines_for_word_tickers_still_match(text, symbol):
    assert matches_symbol(text, symbol) is True


def test_sec_names_require_proper_noun_capitalisation(monkeypatch):
    import time
    table = {"BIG": sec_tickers.TickerInfo(768835, "Big Lots Inc"),
             "AAPL": sec_tickers.TickerInfo(320193, "Apple Inc.")}
    monkeypatch.setattr(sec_tickers, "_cache", (time.monotonic(), table))
    assert matches_symbol("big lots of people showed up", "BIG") is False
    assert matches_symbol("Big Lots files for bankruptcy", "BIG") is True
    assert matches_symbol("BIG LOTS CLOSES STORES", "BIG") is True
    assert matches_symbol("an apple a day", "AAPL") is False


# --- PR #18 review (hbot): `$F` must not match `$F.X` / class shares ---------

@pytest.mark.parametrize("text,symbol", [
    ("$F.X rallies", "F"),
    ("Watching F.X closely", "F"),
    ("NYSE: F.X slides", "F"),
    ("(F.X) slides", "F"),
    ("Buying $BRK.B today", "BRK"),
    ("NYSE: BRK.B up", "BRK"),
    ("BRK.B hits a record", "BRK"),
    ("BRK-B hits a record", "BRK"),
])
def test_ticker_followed_by_dot_letter_is_a_different_symbol(text, symbol):
    assert matches_symbol(text, symbol) is False


@pytest.mark.parametrize("text,symbol", [
    ("I bought more shares of $F.", "F"),
    ("Ford Motor (NYSE: F). Shares rose.", "F"),
    ("Bought $BRK.B.", "BRK.B"),
    ("Long $AAPL.", "AAPL"),
    ("Long AAPL. Short MSFT.", "AAPL"),
])
def test_sentence_final_period_still_matches(text, symbol):
    assert matches_symbol(text, symbol) is True


# --- PR #18 review (hbot): unverified "(X)" must not match ambiguous tickers --

@pytest.mark.parametrize("text,symbol", [
    ("Plan (A)", "A"),
    ("See Plan (A) for details", "A"),
    ("Section (F) applies", "F"),
    ("Model (T) review", "T"),
    ("Exhibit (ON)", "ON"),
    ("Appendix (C) lists them", "C"),
    ("Vitamin (C) levels", "C"),
    ("Schedule (O) attached", "O"),
    ("Category (IT) budget", "IT"),
    ("Form (A) filed late", "A"),
    ("Henry (F) wrote", "F"),
    ("Tier (ALL) access", "ALL"),
    ("Mode (NOW) enabled", "NOW"),
    ("Microsoft (T) and Apple", "T"),  # a real company, but not this ticker's company
    ("Ford Motor (T) review", "T"),
])
def test_parenthesized_ambiguous_ticker_needs_the_company_name(text, symbol):
    assert matches_symbol(text, symbol) is False


@pytest.mark.parametrize("text,symbol", [
    ("Ford (F) recalls trucks", "F"),
    ("Ford Motor (F) recalls trucks", "F"),
    ("Ford Motor Co. (F) recalls trucks", "F"),
    ("Ford Motor Company (F) recalls trucks", "F"),
    ("AT&T (T) adds subscribers", "T"),
    ("AT&T Inc. (T) adds subscribers", "T"),
    ("ON Semiconductor (ON) beats", "ON"),
    ("ServiceNow (NOW) climbs", "NOW"),
    ("Agilent Technologies (A) beats estimates", "A"),
    ("Gartner (IT) raises outlook", "IT"),
    ("Realty Income (O) raises its dividend", "O"),
])
def test_parenthesized_ambiguous_ticker_after_its_company_name_matches(text, symbol):
    assert matches_symbol(text, symbol) is True


def test_parenthesized_ambiguous_ticker_verified_by_sec_title(monkeypatch):
    import time
    table = {"V": sec_tickers.TickerInfo(1403161, "Visa Inc."),
             "C": sec_tickers.TickerInfo(831001, "Citigroup Inc")}
    monkeypatch.setattr(sec_tickers, "_cache", (time.monotonic(), table))
    assert matches_symbol("Visa (V) beats", "V") is True  # generic name is fine right next to the ticker
    assert matches_symbol("Citigroup Inc. (C) beats", "C") is True
    assert matches_symbol("Vitamin (C) levels", "C") is False
    assert matches_symbol("New visa (V) rules", "V") is False  # lowercase: not the proper noun


def test_parenthesized_non_ambiguous_ticker_unchanged():
    assert matches_symbol("Adobe (ADBE) news", "ADBE") is True
    assert matches_symbol("see (AAPL)", "AAPL") is True


# --- PR #18 review (hbot): names are not front-stripped to a partial name ----

@pytest.mark.parametrize("title,expected", [
    ("New York Times Co", "New York Times"),
    ("AG Mortgage Investment Trust, Inc.", "AG Mortgage Investment Trust"),
    ("New Jersey Resources Corp", "New Jersey Resources"),
    ("Group 1 Automotive Inc", "Group 1 Automotive"),
    ("De Beers Group", "De Beers"),
    ("JPMorgan Chase & Co", "JPMorgan Chase"),
    ("Charles Schwab Corp /DE/", "Charles Schwab"),
    ("Lennar Corp /New/", "Lennar"),
    ("Wells Fargo & Company/MN", "Wells Fargo"),
    ("The Walt Disney Company", "Walt Disney"),
    ("General Motors Co", "General Motors"),
    ("Goldman Sachs Group Inc", "Goldman Sachs"),
    ("Brown-Forman Corp Class B", "Brown-Forman"),
    ("The Home Depot, Inc.", "Home Depot"),
])
def test_distinctive_name_only_strips_legal_suffixes_and_leading_the(title, expected):
    assert sm.distinctive_name(title) == expected


@pytest.mark.parametrize("title", [
    "News Corp /New/",       # -> "News"
    "Popular, Inc.",         # -> "Popular"
    "Progressive Corp",
    "First Inc",
    "United Corp",
    "General Corp",
    "American Inc",
    "Bank Holdings",
    "Motors Co",
    "First National Corp",   # every word generic
    "American Financial Group Inc",
])
def test_generic_names_are_never_used(title):
    assert sm.distinctive_name(title) is None


@pytest.fixture
def partial_name_table(monkeypatch):
    import time
    table = {
        "NYT": sec_tickers.TickerInfo(71691, "New York Times Co"),
        "MITT": sec_tickers.TickerInfo(1514281, "AG Mortgage Investment Trust, Inc."),
        "NJR": sec_tickers.TickerInfo(356309, "New Jersey Resources Corp"),
        "GPI": sec_tickers.TickerInfo(1031203, "Group 1 Automotive Inc"),
        "NWSA": sec_tickers.TickerInfo(1564708, "News Corp /New/"),
        "GM": sec_tickers.TickerInfo(1467858, "General Motors Co"),
        "BPOP": sec_tickers.TickerInfo(763901, "Popular, Inc."),
        "JPMX": sec_tickers.TickerInfo(19617, "JPMorgan Chase & Co"),
    }
    monkeypatch.setattr(sec_tickers, "_cache", (time.monotonic(), table))
    return table


@pytest.mark.parametrize("text,symbol", [
    ("York Times readers wait", "NYT"),
    ("Mortgage Investment Trust yields climb", "MITT"),
    ("Jersey Resources update", "NJR"),
    ("Top 1 Automotive picks", "GPI"),
    ("Breaking News today", "NWSA"),
    ("General Electric beats", "GM"),
    ("Motors Liquidation update", "GM"),
    ("Popular Science magazine", "BPOP"),
])
def test_incomplete_or_generic_names_do_not_match(partial_name_table, text, symbol):
    assert matches_symbol(text, symbol) is False


@pytest.mark.parametrize("text,symbol", [
    ("New York Times beats subscriber estimates", "NYT"),
    ("New Jersey Resources raises dividend", "NJR"),
    ("Group 1 Automotive posts record quarter", "GPI"),
    ("General Motors recalls SUVs", "GM"),
    ("JPMorgan Chase earnings preview", "JPMX"),
])
def test_full_company_names_still_match(partial_name_table, text, symbol):
    assert matches_symbol(text, symbol) is True
