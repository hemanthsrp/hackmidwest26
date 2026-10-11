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


# --- PR #18 review (hbot): single-flight cold load, retry, sanitized errors --

import threading

import httpx


class RacingClient:
    """Counts downloads. Each get() waits (bounded) for all N threads to be
    inside get() at once, so an unlocked cache deterministically downloads N
    times while a single-flight cache downloads exactly once."""

    def __init__(self, n):
        self.n = n
        self.calls = 0
        self._lock = threading.Lock()
        self._all_in = threading.Event()

    def get(self, url):
        with self._lock:
            self.calls += 1
            if self.calls >= self.n:
                self._all_in.set()
        self._all_in.wait(timeout=0.5)
        return FakeClient().get(url)


def test_concurrent_cold_lookups_download_once():
    n = 8
    client = RacingClient(n)
    barrier = threading.Barrier(n)
    results, errors = [], []

    def worker():
        try:
            barrier.wait()
            results.append(sec_tickers.lookup("AAPL", client).cik)
        except Exception as exc:  # pragma: no cover - surfaced by the assert
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors
    assert results == [320193] * n
    assert client.calls == 1


class FlakyClient(FakeClient):
    def __init__(self, failures):
        super().__init__()
        self.failures = failures

    def get(self, url):
        if self.failures:
            self.failures -= 1
            self.calls += 1
            raise httpx.ConnectError("boom")
        return super().get(url)


def test_failed_download_does_not_poison_the_cache():
    c = FlakyClient(failures=1)
    with pytest.raises(httpx.ConnectError):
        sec_tickers.load(c)
    assert sec_tickers.cached_title("AAPL") is None
    assert sec_tickers.lookup("AAPL", c).cik == 320193  # next call retries
    assert c.calls == 2
    sec_tickers.lookup("MSFT", c)
    assert c.calls == 2


def test_malformed_table_raises_value_error_and_is_not_cached():
    class ListClient(FakeClient):
        def get(self, url):
            self.calls += 1

            class R:
                def raise_for_status(self):
                    pass

                def json(self):
                    return ["secret-ish body", {"cik_str": 1}]

            return R()

    c = ListClient()
    with pytest.raises(ValueError) as ei:
        sec_tickers.load(c)
    assert "secret-ish" not in str(ei.value)
    with pytest.raises(ValueError):
        sec_tickers.load(c)
    assert c.calls == 2


def test_sec_adapter_sanitizes_ticker_table_failures(monkeypatch):
    from scraper_analysis.sources import sec_edgar
    from scraper_analysis.sources.base import SourceUnavailableError

    def handler(request):
        return httpx.Response(200, json=["not", "a", "table"])

    real_client = httpx.Client
    monkeypatch.setattr(
        sec_edgar.httpx, "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(SourceUnavailableError) as ei:
        SecEdgarAdapter().fetch_live("AAPL")
    assert str(ei.value) == sec_tickers.MALFORMED_MESSAGE  # no response body echoed
    assert sec_tickers._cache is None


# --- PR #18 review (hbot): an empty table must not be cached for 24h ---------

def _json_client(*bodies):
    """A client whose successive downloads return the given JSON bodies."""
    queue = list(bodies)

    class SeqClient(FakeClient):
        def get(self, url):
            self.calls += 1
            raw = queue.pop(0) if len(queue) > 1 else queue[0]

            class R:
                def raise_for_status(self):
                    pass

                def json(self):
                    return raw

            return R()

    return SeqClient()


@pytest.mark.parametrize("raw", [
    {},
    {"0": {"ticker": "X"}},  # no cik_str
    {"0": "junk", "1": ["also junk"]},
    {"0": {"cik_str": "not-a-number", "ticker": "AAPL", "title": "Apple Inc."}},
])
def test_table_without_usable_entries_is_a_failed_load_and_not_cached(raw):
    c = _json_client(raw)
    with pytest.raises(ValueError) as ei:
        sec_tickers.load(c)
    assert str(ei.value) == sec_tickers.EMPTY_MESSAGE  # fixed text, no body echoed
    assert sec_tickers._cache is None
    assert sec_tickers.cached_title("AAPL") is None
    with pytest.raises(ValueError):
        sec_tickers.load(c)  # next call retries instead of serving a cached empty table
    assert c.calls == 2


def test_empty_table_then_good_table_recovers():
    c = _json_client({}, RAW)
    with pytest.raises(ValueError):
        sec_tickers.lookup("AAPL", c)
    assert sec_tickers.lookup("AAPL", c).cik == 320193
    assert sec_tickers.lookup("MSFT", c).cik == 789019
    assert c.calls == 2


def test_sec_adapter_sanitizes_empty_ticker_table(monkeypatch):
    from scraper_analysis.sources import sec_edgar
    from scraper_analysis.sources.base import SourceUnavailableError

    real_client = httpx.Client
    monkeypatch.setattr(
        sec_edgar.httpx, "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})), **kw),
    )
    with pytest.raises(SourceUnavailableError) as ei:
        SecEdgarAdapter().fetch_live("AAPL")
    assert str(ei.value) == sec_tickers.EMPTY_MESSAGE
    assert sec_tickers._cache is None
