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
