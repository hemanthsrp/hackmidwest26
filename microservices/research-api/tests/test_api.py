from fastapi.testclient import TestClient

from research_api.app import app


def test_health_reports_api_is_ready_for_local_demo() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "research-api"}


def test_sample_mode_returns_a_labeled_current_research_snapshot() -> None:
    response = TestClient(app).post(
        "/v0/research-assessments",
        json={"symbol": "ACME", "mode": "sample"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "ACME"
    assert body["data_mode"] == "sample"
    assert body["snapshot"]["kind"] == "current_research_snapshot"
    assert body["snapshot"]["as_of"].endswith("Z")
    assert body["assessment"]["label"] == "hold"
    assert "current research snapshot" in body["assessment"]["explanation"].lower()
    assert "not a prediction" in body["assessment"]["uncertainty"].lower()
    assert body["evidence"][0]["data_mode"] == "sample"
    assert body["signals"][0]["data_mode"] == "sample"


def test_live_mode_reports_unavailable_instead_of_substituting_a_fixture() -> None:
    response = TestClient(app).post(
        "/v0/research-assessments",
        json={"symbol": "ACME", "mode": "live"},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "provider_unavailable"
    assert body["error"]["retryable"] is True
    assert "fixture" not in body


def test_failure_mode_exposes_a_retryable_failure_envelope() -> None:
    response = TestClient(app).post(
        "/v0/research-assessments",
        json={"symbol": "ACME", "mode": "failure"},
    )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "simulated_provider_failure",
        "message": "A simulated provider failure occurred; no assessment was generated.",
        "retryable": True,
    }


def test_invalid_symbol_has_a_stable_client_error_envelope() -> None:
    response = TestClient(app).post(
        "/v0/research-assessments",
        json={"symbol": "ACME!", "mode": "sample"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "invalid_symbol",
        "message": "symbol must be an uppercase ticker containing 1 to 5 letters",
        "retryable": False,
    }
