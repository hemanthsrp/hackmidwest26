import httpx
import pytest
from decision_maker.quant import read_vol_surface
from fastapi.testclient import TestClient

from research_api import assessment
from research_api.app import app
from research_api.quant import VolSurfaceUnavailable, to_quant_input, vol_surface_provider
from test_assessment import RecordingMaker


def surface_response(**overrides) -> dict:
    """Shaped like volatility-surface-builder's POST /v0/volatility-surfaces reply
    (pipeline.build_snapshot there)."""
    body = {
        "symbol": "AAPL",
        "data_mode": "live",
        "source": "Yahoo Finance option chain",
        "retrieved_at": "2026-10-10T22:00:00Z",
        "market_observed_at": None,
        "spot": 100.0,
        "pricing_assumptions": {"risk_free_rate_decimal": 0.043, "dividend_yield_decimal": 0.013},
        "statistics": {
            "n_points": 420,
            "n_expiries": 8,
            "strike_range": [75.0, 125.0],
            "maturity_range_years": [0.02, 1.0],
            "iv_range_decimal": [0.18, 0.62],
            "atm_iv_decimal": 0.31,
            "skew_25d_proxy_decimal": 0.045,
        },
        "surface": {
            "strike": [80.0, 90.0, 101.0, 110.0, 120.0],
            "maturity_years": [0.02, 0.25, 1.0],
            "iv_decimal": [[0.5, 0.42, 0.38, 0.36, 0.37], [0.4, 0.34, 0.31, 0.3, 0.31], [0.36, 0.31, 0.29, 0.28, 0.29]],
        },
        "interpretation": "Option-implied volatility diagnostic; not a stock-price forecast or investment assessment.",
    }
    return {**body, **overrides}


def test_the_services_reply_maps_onto_the_decision_makers_input() -> None:
    snapshot = to_quant_input(surface_response()).vol_surface

    assert (snapshot.spot, snapshot.source, snapshot.data_mode) == (100.0, "Yahoo Finance option chain", "live")
    assert (snapshot.atm_iv_mean, snapshot.skew_25d_proxy, snapshot.n_points, snapshot.n_expiries) == (0.31, 0.045, 420, 8)
    assert (snapshot.T_range, snapshot.iv_range, snapshot.strike_range) == ((0.02, 1.0), (0.18, 0.62), (75.0, 125.0))
    assert snapshot.as_of.isoformat() == "2026-10-10T22:00:00+00:00"  # retrieval time: the service gives no quote time


def test_the_term_structure_is_read_from_the_grid_at_the_strike_nearest_spot() -> None:
    snapshot = to_quant_input(surface_response()).vol_surface
    reading, _ = read_vol_surface("AAPL", snapshot, "30d")

    assert [(p.T, p.iv) for p in snapshot.atm_iv_by_expiry] == [(0.02, 0.38), (0.25, 0.31), (1.0, 0.29)]
    assert (reading.status, reading.term_structure, reading.priced_volatility) == ("used", "inverted", "moderate")


def test_missing_statistics_and_an_off_grid_spot_are_left_missing() -> None:
    reply = surface_response(spot=300.0)
    reply["statistics"] = {**reply["statistics"], "atm_iv_decimal": None, "skew_25d_proxy_decimal": None}
    reply["surface"]["iv_decimal"][0][2] = float("nan")

    snapshot = to_quant_input(reply).vol_surface

    assert (snapshot.atm_iv_mean, snapshot.skew_25d_proxy, snapshot.atm_iv_by_expiry) == (None, None, [])
    assert [p.T for p in to_quant_input({**reply, "spot": 100.0}).vol_surface.atm_iv_by_expiry] == [0.25, 1.0]


def test_the_provider_asks_the_service_for_a_live_surface() -> None:
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return httpx.Response(200, json=surface_response())

    quant = vol_surface_provider("http://127.0.0.1:8002/", post=post)("AAPL", "30d")

    assert calls == [("http://127.0.0.1:8002/v0/volatility-surfaces", {"symbol": "AAPL", "mode": "live"})]
    assert quant.vol_surface.atm_iv_mean == 0.31


@pytest.mark.parametrize("failure", [httpx.Response(503, json={"error": {"code": "options_provider_unavailable"}}), httpx.ConnectError("refused")])
def test_a_surface_that_cannot_be_had_is_raised_not_replaced(failure) -> None:
    def post(url, **kwargs):
        if isinstance(failure, Exception):
            raise failure
        return failure

    with pytest.raises(VolSurfaceUnavailable):
        vol_surface_provider("http://127.0.0.1:8002", post=post)("AAPL", "30d")


def test_the_route_uses_the_volatility_service_when_its_url_is_set(monkeypatch) -> None:
    maker = RecordingMaker()
    monkeypatch.setenv("VOL_SURFACE_URL", "http://127.0.0.1:8002")
    monkeypatch.setattr(assessment, "build_decision_maker", lambda: maker)
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Response(200, json=surface_response()))

    response = TestClient(app).post("/v0/research-assessments", json={"symbol": "AAPL", "mode": "live"})

    assert response.status_code == 200
    assert maker.calls[0][1].vol_surface.atm_iv_mean == 0.31


def test_a_failing_volatility_service_is_reported_and_the_assessment_still_returns(monkeypatch) -> None:
    monkeypatch.setenv("VOL_SURFACE_URL", "http://127.0.0.1:8002")
    monkeypatch.setattr(assessment, "build_decision_maker", lambda: RecordingMaker())
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Response(503, json={}))

    response = TestClient(app).post("/v0/research-assessments", json={"symbol": "AAPL", "mode": "live"})

    assert response.status_code == 200
    assert "quant_provider_failed" in [w["code"] for w in response.json()["warnings"]]


def test_a_provider_registered_by_hand_is_not_replaced_by_the_environment(monkeypatch) -> None:
    by_hand = lambda symbol, horizon: None  # noqa: E731
    assessment.set_quant_provider(by_hand)

    assessment.configure_quant({"VOL_SURFACE_URL": "http://127.0.0.1:8002"})

    assert assessment._quant_provider is by_hand
