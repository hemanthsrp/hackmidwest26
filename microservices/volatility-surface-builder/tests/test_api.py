from fastapi.testclient import TestClient

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
