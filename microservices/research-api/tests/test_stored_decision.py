"""One engine for every page: feeds, lists and chat read assessment.decide_stored, which
runs the same decision maker, options math and live mode as the stock page, never
triggers ingestion, and forgets its cached answer once a live assessment refreshes."""

import pytest
from fastapi.testclient import TestClient

from research_api import assessment, v1
from research_api.app import app
from test_assessment import RecordingMaker
from test_v1 import database, headers  # noqa: F401  (auth helpers and DB fixture)

REAL_DECIDE_STORED = assessment.decide_stored


@pytest.fixture(autouse=True)
def real_engine(database, monkeypatch):  # noqa: F811
    """test_v1's database fixture stubs decide_stored for its route tests; these test the real one."""
    monkeypatch.setattr(assessment, "decide_stored", REAL_DECIDE_STORED)


def _no_ingestion(symbol):
    raise AssertionError(f"decide_stored must not trigger ingestion ({symbol})")


def test_decide_stored_runs_live_with_the_options_math_and_never_ingests(monkeypatch) -> None:
    maker, quant = RecordingMaker(), object()
    monkeypatch.setattr(assessment, "get_scoring_maker", lambda: maker)
    monkeypatch.setattr(assessment, "trigger_ingestion", _no_ingestion)
    assessment.set_quant_provider(lambda symbol, horizon: quant)

    assessment.decide_stored("AAPL")

    request, passed_quant = maker.calls[0]
    # Live mode is what lets the maker use Jev's article judgments and the options reading.
    assert (request.symbol, request.mode, request.preferences.horizon) == ("AAPL", "live", "30d")
    assert passed_quant is quant


def test_decide_stored_is_cached_until_a_live_assessment_refreshes_the_symbol(monkeypatch) -> None:
    maker = RecordingMaker()
    monkeypatch.setattr(assessment, "get_scoring_maker", lambda: maker)
    monkeypatch.setattr(assessment, "trigger_ingestion", lambda symbol: None)

    assessment.decide_stored("NVDA")
    assessment.decide_stored("NVDA")
    assert len(maker.calls) == 1

    assessment.assess(RecordingMaker(), symbol="NVDA", query=None, preferences={}, sample=False)  # ingests
    assessment.decide_stored("NVDA")
    assert len(maker.calls) == 2


def test_the_feed_shows_the_decision_makers_label(monkeypatch) -> None:
    monkeypatch.setattr(assessment, "get_scoring_maker", lambda: RecordingMaker())
    monkeypatch.setattr(assessment, "trigger_ingestion", _no_ingestion)
    monkeypatch.setattr(v1, "source_records", lambda symbol: ([], []))

    expected = REAL_DECIDE_STORED("MSFT").assessment
    body = TestClient(app).get("/v1/stocks/MSFT", headers=headers()).json()

    assert body["assessment"]["label"] == expected.label
    assert body["assessment"]["decision_engine"]["name"] == expected.decision_engine.name
