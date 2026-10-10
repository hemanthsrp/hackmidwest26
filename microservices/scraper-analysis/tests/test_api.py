import pytest
from fastapi.testclient import TestClient

from scraper_analysis.api import app
from scraper_analysis.storage import store as store_module


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    # Force the in-memory store regardless of what .env has configured --
    # unit tests must stay deterministic and offline, not depend on a real
    # Postgres instance being reachable.
    monkeypatch.setattr(store_module, "_store", store_module.InMemoryEvidenceStore())
    yield
    monkeypatch.setattr(store_module, "_store", None)


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ingest_run_with_sample_fallback_and_query_evidence(client):
    resp = client.post("/ingest/run", params={"symbol": "AAPL", "live": False, "tag": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "AAPL"
    assert body["count"] >= 1
    assert all(item["data_mode"] == "sample" for item in body["evidence"])

    resp = client.get("/evidence", params={"symbol": "AAPL"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert len(resp.json()["evidence"]) == body["count"]


def test_evidence_for_unseen_symbol_is_insufficient_data(client):
    resp = client.get("/evidence", params={"symbol": "ZZZZ"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "insufficient_data"
    assert resp.json()["evidence"] == []


def test_invalid_symbol_returns_400(client):
    resp = client.get("/evidence", params={"symbol": "not-a-symbol!"})
    assert resp.status_code == 400


def test_signals_insufficient_data_by_default(client):
    resp = client.get("/signals", params={"symbol": "AAPL"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "insufficient_data"
