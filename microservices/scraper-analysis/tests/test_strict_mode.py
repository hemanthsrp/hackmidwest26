import pytest
from fastapi.testclient import TestClient

from scraper_analysis.api import app
from scraper_analysis.pipeline import ingest
from scraper_analysis.sources import market_signals
from scraper_analysis.sources.base import RawRecord, SourceAdapter, SourceUnavailableError, resolve
from scraper_analysis.storage import store as store_module


# --- resolve(): the single place fallback behavior is decided ---------------

def _ok():
    return ["live-item"]


def _boom():
    raise SourceUnavailableError("upstream 503")


def _sample():
    return ["fixture-item"]


def test_resolve_live_success():
    r = resolve(_ok, _sample, allow_live=True, fallback=True)
    assert (r.status, r.data_mode, r.items, r.error) == ("live", "live", ["live-item"], None)


def test_resolve_requested_fixtures_are_not_a_fallback():
    r = resolve(_ok, _sample, allow_live=False, fallback=False)
    assert (r.status, r.data_mode, r.items) == ("sample", "sample", ["fixture-item"])


def test_resolve_failure_with_fallback_is_visible():
    r = resolve(_boom, _sample, allow_live=True, fallback=True)
    assert (r.status, r.data_mode, r.items) == ("fallback", "sample", ["fixture-item"])
    assert r.error == "upstream 503"


def test_resolve_failure_without_fallback_returns_nothing():
    r = resolve(_boom, _sample, allow_live=True, fallback=False)
    assert (r.status, r.items) == ("unavailable", [])
    assert r.error == "upstream 503"


# --- ingestion + API ---------------------------------------------------------

class StubAdapter(SourceAdapter):
    source_type = "general_news"
    fixture_file = "news_sample.json"

    def __init__(self, name, works):
        self.name, self.works = name, works

    def fetch_live(self, symbol):
        if not self.works:
            raise SourceUnavailableError(f"{self.name} is down")
        return [RawRecord(source_name=self.name, source_type="general_news", symbol=symbol,
                          payload={"title": f"{self.name} live headline"}, url=f"https://x/{self.name}")]


@pytest.fixture
def env(monkeypatch):
    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    monkeypatch.setattr(market_signals, "fetch_live", lambda sym: (_ for _ in ()).throw(SourceUnavailableError("yf down")))
    yield monkeypatch
    monkeypatch.setattr(store_module, "_store", None)


def use_adapters(monkeypatch, *adapters):
    monkeypatch.setattr(ingest, "build_adapters", lambda: list(adapters))


client = TestClient(app)


def test_fallback_default_substitutes_and_says_so(env):
    use_adapters(env, StubAdapter("alpha", works=False))
    body = client.post("/ingest/run", params={"symbol": "AAPL", "tag": False}).json()
    statuses = {s["name"]: s["status"] for s in body["sources"]}
    assert statuses["alpha"] == "fallback"
    assert all(e["data_mode"] == "sample" for e in body["evidence"])
    assert any("alpha" in w and "fixtures substituted" in w for w in body["warnings"])


def test_strict_mode_with_nothing_live_is_503_provider_unavailable(env):
    use_adapters(env, StubAdapter("alpha", works=False), StubAdapter("beta", works=False))
    r = client.post("/ingest/run", params={"symbol": "AAPL", "tag": False, "fallback": False})
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["code"] == "provider_unavailable" and err["retryable"] is True
    assert {s["status"] for s in err["details"]["sources"]} >= {"unavailable"}
    assert store_module.get_store().query_evidence("AAPL") == []  # nothing stored


def test_strict_mode_partial_outage_keeps_live_data_only(env):
    use_adapters(env, StubAdapter("alpha", works=True), StubAdapter("beta", works=False))
    r = client.post("/ingest/run", params={"symbol": "AAPL", "tag": False, "fallback": False})
    assert r.status_code == 200
    body = r.json()
    assert {s["name"]: s["status"] for s in body["sources"]}["beta"] == "unavailable"
    assert body["count"] == 1 and body["evidence"][0]["data_mode"] == "live"
    assert any("beta" in w and "omitted" in w for w in body["warnings"])


def test_live_false_is_requested_fixtures_not_a_fallback(env):
    use_adapters(env, StubAdapter("alpha", works=False))
    r = client.post("/ingest/run", params={"symbol": "AAPL", "tag": False, "live": False, "fallback": False})
    assert r.status_code == 200  # strict + live=false must not 503
    body = r.json()
    assert {s["status"] for s in body["sources"]} == {"sample"}
    assert body["warnings"] == []


def test_signal_sources_are_reported_too(env):
    use_adapters(env, StubAdapter("alpha", works=True))
    body = client.post("/ingest/run", params={"symbol": "AAPL", "tag": False}).json()
    sig = next(s for s in body["sources"] if s["name"] == "market_signals")
    assert sig["status"] == "fallback" and "yf down" in sig["error"]
