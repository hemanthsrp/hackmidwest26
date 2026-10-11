"""PR #17 review: a ticker in a following asset/note line must not become a false House trade."""

from scraper_analysis.sources import house_clerk as h

T = "03/01/2026"
A = "$1,001 - $15,000"


def test_note_after_a_complete_row_does_not_donate_its_ticker():
    text = f"Private Fund LP [OT] P {T} {T} {A}\nsee also Tesla (TSLA) [ST]\nF S: New\n"
    assert h.parse_ptr_text(text) == []


def test_next_assets_name_line_is_not_adopted_by_a_tickerless_row():
    text = f"Private Fund LP [OT] P {T} {T} {A}\nApple Inc. (AAPL) [ST]\nS {T} {T} {A}\nF S: New\n"
    assert h.parse_ptr_text(text) == []


def test_legit_wrapped_ticker_and_type_still_parse():
    text = f"Fund (ETF) (VOO) P {T} {T} {A}\n[EF]\nF S: New\n"
    assert [r["ticker"] for r in h.parse_ptr_text(text)] == ["VOO"]
