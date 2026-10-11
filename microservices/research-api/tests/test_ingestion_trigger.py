from fastapi.testclient import TestClient

from research_api import assessment
from research_api.app import app
from test_assessment import RecordingMaker


def test_live_assessment_triggers_strict_ingestion_before_decision(monkeypatch):
    calls = []
    monkeypatch.setattr(assessment, "trigger_ingestion", lambda symbol: calls.append(symbol))
    monkeypatch.setattr(assessment, "get_decision_maker", lambda: RecordingMaker())

    response = TestClient(app).post("/v0/research-assessments", json={"symbol": "aapl", "mode": "live"})

    assert response.status_code == 200
    assert calls == ["AAPL"]
