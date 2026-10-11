from fastapi.testclient import TestClient
import pandas as pd
import pytest

from vol_surface_builder.api import app

client = TestClient(app)


def test_sample_surface_is_labeled_and_deterministic():
    first = client.post("/v0/volatility-surfaces", json={"symbol": "SPY", "mode": "sample"})
    second = client.post("/v0/volatility-surfaces", json={"symbol": "spy", "mode": "sample"})
    assert first.status_code == second.status_code == 200
    a, b = first.json(), second.json()
    assert a["symbol"] == "SPY"
    assert a["data_mode"] == "sample"
    assert a["surface"] == b["surface"]
    assert len(a["surface"]["iv_decimal"]) == 16
    assert len(a["surface"]["iv_decimal"][0]) == 24
    assert a["market_observed_at"] is None
    assert "not a stock-price forecast" in a["interpretation"]


def test_sample_mode_rejects_other_symbols_instead_of_relabeling_spy_data():
    response = client.post("/v0/volatility-surfaces", json={"symbol": "AAPL", "mode": "sample"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_sample_symbol"


def test_live_failure_does_not_fall_back_to_sample(monkeypatch):
    import vol_surface_builder.pipeline as pipeline

    def fail(**kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(pipeline, "get_option_data", fail)
    response = client.post("/v0/volatility-surfaces", json={"symbol": "AAPL", "mode": "live"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "options_provider_unavailable"
    assert "surface" not in response.json()


def test_invalid_symbol_is_rejected():
    response = client.post("/v0/volatility-surfaces", json={"symbol": "AAPL!"})
    assert response.status_code == 400


@pytest.mark.parametrize("spot", [1.0, 10_001.0])
def test_sample_spot_outside_safe_bounds_is_rejected(spot: float):
    response = TestClient(app, raise_server_exceptions=False).post(
        "/v0/volatility-surfaces",
        json={"symbol": "SPY", "mode": "sample", "spot": spot},
    )

    assert response.status_code == 422


def test_empty_live_chain_is_reported_as_unusable_data(monkeypatch):
    import vol_surface_builder.pipeline as pipeline

    monkeypatch.setattr(pipeline, "get_option_data", lambda **kwargs: (pd.DataFrame(), 100.0))
    response = client.post("/v0/volatility-surfaces", json={"symbol": "AAPL", "mode": "live"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_usable_option_data"
    assert response.json()["error"]["retryable"] is False


def test_live_snapshot_uses_data_source_dividend_yield(monkeypatch):
    import vol_surface_builder.pipeline as pipeline

    frame = pd.DataFrame(
        {
            "strike": [90.0, 100.0, 110.0, 90.0, 100.0, 110.0],
            "T": [0.25, 0.25, 0.25, 0.5, 0.5, 0.5],
            "iv": [0.3, 0.25, 0.22, 0.28, 0.24, 0.21],
            "moneyness": [0.9, 1.0, 1.1, 0.9, 1.0, 1.1],
        }
    )
    frame.attrs["dividend_yield_decimal"] = 0.021
    monkeypatch.setattr(pipeline, "get_option_data", lambda **kwargs: (frame, 100.0))

    response = client.post("/v0/volatility-surfaces", json={"symbol": "BRK.B", "mode": "live"})

    assert response.status_code == 200
    assert response.json()["pricing_assumptions"]["dividend_yield_decimal"] == 0.021


def test_live_provider_dividend_yield_has_a_neutral_fallback():
    from vol_surface_builder.data_feed import _provider_dividend_yield

    class ProviderTicker:
        info = {"dividendYield": 0.021}

    class MissingYieldTicker:
        info = {}

    assert _provider_dividend_yield(ProviderTicker()) == 0.021
    assert _provider_dividend_yield(MissingYieldTicker()) == 0.0
