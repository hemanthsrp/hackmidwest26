import importlib

from fastapi.testclient import TestClient

from research_api import assessment
from test_assessment import RecordingMaker

app_module = importlib.import_module("research_api.app")


def test_live_assessment_reuses_a_bounded_cached_snapshot(monkeypatch) -> None:
    maker = RecordingMaker()
    monkeypatch.setenv("ASSESSMENT_CACHE_SECONDS", "300")
    monkeypatch.setattr(assessment, "get_decision_maker", lambda: maker)
    app_module.clear_assessment_cache()
    client = TestClient(app_module.app)
    request = {
        "symbol": "AAPL",
        "mode": "live",
        "preferences": {"horizon": "30d", "risk_profile": "balanced"},
    }

    first = client.post("/v0/research-assessments", json=request)
    second = client.post("/v0/research-assessments", json=request)

    assert first.status_code == second.status_code == 200
    assert len(maker.calls) == 1
    assert first.json()["data_mode"] == "sample"
    assert second.json()["data_mode"] == "cached"
    assert second.json()["assessment"]["data_mode"] == "cached"
    assert "live_assessment_cache" in [warning["code"] for warning in second.json()["warnings"]]
