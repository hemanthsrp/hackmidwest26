from scraper_analysis.sources import market_signals


def test_fetch_sample_returns_fixture_signal_for_known_symbol():
    signals = market_signals.fetch_sample("AAPL")
    assert len(signals) == 1
    signal = signals[0]
    assert signal.symbol == "AAPL"
    assert signal.name == "30-day price change"
    assert signal.unit == "percent"
    assert signal.data_mode == "sample"


def test_fetch_sample_filters_by_symbol():
    assert market_signals.fetch_sample("ZZZZ") == []


def test_fetch_falls_back_to_sample_when_live_disallowed():
    signals, data_mode = market_signals.fetch("AAPL", allow_live=False)
    assert data_mode == "sample"
    assert len(signals) == 1
