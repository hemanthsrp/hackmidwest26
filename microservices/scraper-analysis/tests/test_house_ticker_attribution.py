"""PR #17 review (hbot): "Wrong ticker attribution -- a positioned row
`Fund (ETF) (VOO) [EF] P ...` is parsed as ticker ETF." The ticker is the
parenthesized token adjacent to the asset-type code [XX], not the first
parenthesized uppercase word; with several candidates and no adjacency the
row is skipped rather than guessed."""

from datetime import datetime, timedelta, timezone

import pytest

from scraper_analysis.sources import house_clerk as h

from .test_house_clerk import HEADER, parse_layout, row_at, text_at

NOW = datetime.now(timezone.utc)
TX = (NOW - timedelta(days=12)).strftime("%m/%d/%Y")
AMT = "$1,001 - $15,000"


def _text_row(asset, trailing=""):
    return f"{asset} P {TX} {TX} {AMT}{(' ' + trailing) if trailing else ''}\nF S: New\n"


# (asset text before the type, text after the amount, expected ticker)
CASES = [
    ("Fund (ETF) (VOO) [EF]", "", "VOO"),
    ("Vanguard S&P 500 ETF (VOO) [EF]", "", "VOO"),
    ("Apple Inc. (AAPL) [ST]", "", "AAPL"),
    # ticker-after-amount layout
    ("Fund (ETF)", "(VOO) [EF]", "VOO"),
    ("Vanguard S&P 500 ETF", "(VOO) [EF]", "VOO"),
    ("Apple Inc.", "(AAPL) [ST]", "AAPL"),
]


@pytest.mark.parametrize("asset,trailing,ticker", CASES)
def test_plain_text_ticker_is_the_token_next_to_the_asset_type(asset, trailing, ticker):
    rows = h.parse_ptr_text(_text_row(asset, trailing))
    assert [r["ticker"] for r in rows] == [ticker]


@pytest.mark.parametrize("asset,trailing,ticker", CASES)
def test_positioned_ticker_is_the_token_next_to_the_asset_type(asset, trailing, ticker):
    rows = parse_layout(HEADER + [row_at(asset, "P", TX, TX, AMT, trailing=trailing or None),
                                  text_at(104, "F S: New")])
    assert [r["ticker"] for r in rows] == [ticker]


def test_ticker_and_type_wrapped_to_the_next_line():
    rows = parse_layout(HEADER + [row_at("Fund (ETF) (VOO)", "P", TX, TX, AMT), text_at(104, "[EF]"),
                                  text_at(104, "F S: New")])
    assert [r["ticker"] for r in rows] == ["VOO"]
    assert "ETF" in rows[0]["asset_name"]  # the non-ticker parenthetical stays in the name


def test_several_parenthesized_tokens_without_type_adjacency_are_skipped():
    for asset in ("Fund (ETF) (VOO) Class A [EF]", "Fund (ETF) (VOO)"):
        assert h.parse_ptr_text(_text_row(asset)) == []
        assert parse_layout(HEADER + [row_at(asset, "P", TX, TX, AMT), text_at(104, "F S: New")]) == []


def test_fetch_result_attributes_the_trade_to_voo_not_etf(monkeypatch):
    h._pdf_cache.clear()
    filing = h.HouseFiling("888", NOW.year, NOW - timedelta(days=10), "Jane Example")
    monkeypatch.setattr(h, "_load_index", lambda client, year: [filing])
    rows = parse_layout(HEADER + [row_at("Fund (ETF) (VOO) [EF]", "P", TX, TX, AMT), text_at(104, "F S: New")])
    monkeypatch.setattr(h, "_load_transactions", lambda client, f: [dict(r) for r in rows])
    adapter = h.HouseClerkAdapter()
    voo = adapter.fetch_result("VOO", fallback=False)
    assert voo.status == "live" and len(voo.items) == 1
    assert voo.items[0].payload["ticker"] == "VOO"
    etf = adapter.fetch_result("ETF", fallback=False)
    assert etf.status == "live" and etf.items == []
