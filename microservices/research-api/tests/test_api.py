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


def test_cors_allows_the_local_frontend_origin_only() -> None:
    from fastapi.testclient import TestClient

    from research_api.app import app

    client = TestClient(app)
    preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}

    allowed = client.options("/v0/research-assessments", headers={"Origin": "http://localhost:3000", **preflight})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-credentials" not in allowed.headers

    blocked = client.options("/v0/research-assessments", headers={"Origin": "https://evil.example", **preflight})
    assert "access-control-allow-origin" not in blocked.headers


def test_cors_origins_come_from_the_environment_and_never_allow_a_wildcard(monkeypatch) -> None:
    from research_api.app import cors_origins

    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://app.example/, *, http://localhost:3000")
    assert cors_origins() == ["https://app.example", "http://localhost:3000"]
