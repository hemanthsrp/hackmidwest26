import httpx
from decision_maker import ProviderUnavailableError
from fastapi.testclient import TestClient

from research_api import assessment
from research_api.app import app
from test_assessment import RecordingMaker


def test_trigger_ingestion_uses_explicit_strict_parameters(monkeypatch) -> None:
    observed = {}

    class Response:
        status_code = 200

    def post(url, **kwargs):
        observed.update({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(httpx, "post", post)

    assessment.trigger_ingestion(
        "AAPL",
        {"SCRAPER_ANALYSIS_URL": "http://scraper.internal/", "INGEST_TIMEOUT_SECONDS": "12"},
    )

    assert observed == {
        "url": "http://scraper.internal/ingest/run",
        "params": {"symbol": "AAPL", "live": "true", "fallback": "false", "tag": "true", "judge": "true"},
        "timeout": 12.0,
    }


def test_trigger_ingestion_network_failure_blocks_the_decision(monkeypatch) -> None:
    maker = RecordingMaker()
    monkeypatch.setattr(assessment, "get_decision_maker", lambda: maker)
    monkeypatch.setattr(
        assessment,
        "trigger_ingestion",
        lambda symbol: (_ for _ in ()).throw(ProviderUnavailableError("Evidence ingestion was unavailable; no assessment was generated.", {"provider": "scraper_analysis"})),
    )

    response = TestClient(app).post("/v0/research-assessments", json={"symbol": "AAPL", "mode": "live"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert maker.calls == []


def test_live_assessment_triggers_strict_ingestion_before_decision(monkeypatch):
    calls = []
    monkeypatch.setattr(assessment, "trigger_ingestion", lambda symbol: calls.append(symbol))
    monkeypatch.setattr(assessment, "get_decision_maker", lambda: RecordingMaker())

    response = TestClient(app).post("/v0/research-assessments", json={"symbol": "aapl", "mode": "live"})

    assert response.status_code == 200
    assert calls == ["AAPL"]
