import time

import pytest

from scraper_analysis.sources import sec_tickers
from scraper_analysis.sources.sec_edgar import SecEdgarAdapter

RAW = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "msft", "title": "Microsoft Corp"},
    "2": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
    "3": {"cik_str": 1652044, "ticker": "GOOG", "title": "Alphabet Inc."},
    "4": {"ticker": "BAD"},  # malformed entry is skipped, not fatal
}


class FakeClient:
    def __init__(self):
        self.calls = 0

    def get(self, url):
        self.calls += 1

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return RAW

        return R()


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setattr(sec_tickers, "_cache", None)


def test_parse_uppercases_tickers_and_skips_malformed():
    table = sec_tickers._parse(RAW)
    assert table["MSFT"].cik == 789019 and "BAD" not in table
    assert table["GOOG"].title == "Alphabet Inc."


def test_table_is_downloaded_once_not_per_lookup():
    c = FakeClient()
    assert sec_tickers.lookup("AAPL", c).cik == 320193
    assert sec_tickers.lookup("msft", c).cik == 789019
    assert sec_tickers.lookup("NOPE", c) is None
    assert c.calls == 1


def test_cache_expires_after_ttl(monkeypatch):
    c = FakeClient()
    sec_tickers.load(c)
    t = time.monotonic() + sec_tickers.TTL_SECONDS + 1
    monkeypatch.setattr(sec_tickers.time, "monotonic", lambda: t)
    sec_tickers.load(c)
    assert c.calls == 2


def test_cached_title_is_pure_and_empty_until_loaded():
    assert sec_tickers.cached_title("AAPL") is None  # nothing loaded: no network, no guess
    sec_tickers.load(FakeClient())
    assert sec_tickers.cached_title("aapl") == "Apple Inc."
    assert sec_tickers.cached_title("ZZZZ") is None


def test_sec_adapter_uses_the_shared_cache():
    c = FakeClient()
    assert SecEdgarAdapter._lookup_cik(c, "AAPL") == 320193
    assert SecEdgarAdapter._lookup_cik(c, "GOOG") == 1652044
    assert SecEdgarAdapter._lookup_cik(c, "NOPE") is None
    assert c.calls == 1
