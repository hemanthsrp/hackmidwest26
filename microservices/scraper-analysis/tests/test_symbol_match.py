from scraper_analysis.pipeline.symbol_match import matches_symbol


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
