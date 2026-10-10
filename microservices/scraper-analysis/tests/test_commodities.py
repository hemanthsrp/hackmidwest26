import pytest

from scraper_analysis.models.signal import Signal
from scraper_analysis.pipeline import ingest
from scraper_analysis.sources import commodities
from scraper_analysis.sources.base import SourceUnavailableError
from scraper_analysis.storage import store as store_module


def test_is_commodity():
    assert commodities.is_commodity("corn")
    assert commodities.is_commodity("SOYB")
    assert not commodities.is_commodity("AAPL")
    # LE collides with Lands' End's stock ticker, deliberately not mapped.
    assert not commodities.is_commodity("LE")


def test_fetch_sample_returns_all_three_corn_signals():
    signals = commodities.fetch_sample("CORN")
    units = {s.unit for s in signals}
    assert units == {"percent", "mm"}
    assert len(signals) == 3
    assert all(s.data_mode == "sample" for s in signals)


def test_fetch_sample_unknown_symbol_is_empty():
    assert commodities.fetch_sample("AAPL") == []


def test_fetch_falls_back_to_sample_when_live_disallowed():
    signals, mode = commodities.fetch("WEAT", allow_live=False)
    assert mode == "sample" and len(signals) == 1


def _stub_signal(name):
    from datetime import datetime, timezone
    return Signal(symbol="CORN", name=name, value=1.0, unit="percent", window="30d",
                  as_of=datetime(2026, 10, 1, tzinfo=timezone.utc), source="stub", data_mode="live")


class _Settings:
    noaa_cdo_token = "tok"


def test_one_failing_component_keeps_the_others(monkeypatch):
    monkeypatch.setattr(commodities, "get_settings", lambda: _Settings())
    monkeypatch.setattr(commodities, "_futures_signal", lambda s, c: _stub_signal("futures"))
    monkeypatch.setattr(commodities, "_drought_signal", lambda s, c: (_ for _ in ()).throw(SourceUnavailableError("down")))
    monkeypatch.setattr(commodities, "_precipitation_signal", lambda s, c, t: _stub_signal("precip"))
    names = [s.name for s in commodities.fetch_live("CORN")]
    assert names == ["futures", "precip"]


def test_all_components_failing_raises(monkeypatch):
    def boom(*a, **k):
        raise SourceUnavailableError("down")
    monkeypatch.setattr(commodities, "get_settings", lambda: _Settings())
    monkeypatch.setattr(commodities, "_futures_signal", boom)
    monkeypatch.setattr(commodities, "_drought_signal", boom)
    monkeypatch.setattr(commodities, "_precipitation_signal", boom)
    with pytest.raises(SourceUnavailableError):
        commodities.fetch_live("CORN")


def test_precipitation_skipped_without_token(monkeypatch):
    class NoToken:
        noaa_cdo_token = None
    monkeypatch.setattr(commodities, "get_settings", lambda: NoToken())
    monkeypatch.setattr(commodities, "_futures_signal", lambda s, c: _stub_signal("futures"))
    monkeypatch.setattr(commodities, "_drought_signal", lambda s, c: _stub_signal("drought"))
    monkeypatch.setattr(commodities, "_precipitation_signal", lambda *a: pytest.fail("should not be called"))
    assert [s.name for s in commodities.fetch_live("CORN")] == ["futures", "drought"]


@pytest.fixture
def memory_store(monkeypatch):
    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    yield s
    monkeypatch.setattr(store_module, "_store", None)


def test_signal_ingestion_includes_commodity_signals_and_is_idempotent(memory_store):
    first = ingest.run_signal_ingestion("CORN", allow_live=False)
    ingest.run_signal_ingestion("CORN", allow_live=False)
    assert len(first) >= 3  # ETF price signal (sample) + 3 commodity fixtures
    assert len(memory_store.query_signals("CORN")) == len(first)


def test_non_commodity_symbol_gets_no_commodity_signals(memory_store):
    signals = ingest.run_signal_ingestion("AAPL", allow_live=False)
    assert all("belt" not in s.name for s in signals)
