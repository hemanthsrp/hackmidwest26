import pytest
from fastapi.testclient import TestClient

from research_api import recommendations
from research_api.app import app
from research_api.universe import INDUSTRIES, STOCKS_PER_INDUSTRY

client = TestClient(app)


def test_every_industry_has_24_unique_valid_tickers() -> None:
    seen: list[str] = []
    for slug, (name, stocks) in INDUSTRIES.items():
        assert name and len(stocks) == STOCKS_PER_INDUSTRY == 24, slug
        for symbol, company in stocks:
            assert symbol.isalpha() and symbol.isupper() and 1 <= len(symbol) <= 5, symbol
            assert company
            seen.append(symbol)
    assert len(seen) == len(set(seen)), "a ticker appears in two industries"


def test_industries_lists_every_slug() -> None:
    body = client.get("/v0/industries").json()

    assert {i["slug"] for i in body["industries"]} == set(INDUSTRIES)
    assert all(i["stock_count"] == 24 for i in body["industries"])


def test_unknown_industry_is_a_404_in_the_error_envelope() -> None:
    response = client.get("/v0/industries/crypto/recommended-stocks")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_industry"
    assert response.json()["error"]["retryable"] is False


def test_without_a_store_all_24_are_listed_unscored_in_curated_order() -> None:
    response = client.get("/v0/industries/technology/recommended-stocks")

    body = response.json()
    assert response.status_code == 200
    assert [s["symbol"] for s in body["stocks"]] == [s for s, _ in INDUSTRIES["technology"][1]]
    assert [s["rank"] for s in body["stocks"]] == list(range(1, 25))
    assert all(s["score"] is None and s["assessment_status"] == "not_assessed" for s in body["stocks"])
    assert body["scoring"] == {"status": "unavailable", "scored": 0, "total": 24, "horizon": "30d", "risk_profile": "balanced"}
    assert [w["code"] for w in body["warnings"]] == ["scoring_unavailable"]


def fake_scorer(table: dict[str, tuple]):
    return lambda symbol: table.get(symbol, (None, None, "insufficient_data"))


def test_scored_stocks_come_first_best_score_first_then_the_rest_in_curated_order() -> None:
    table = {"MSFT": (71, "buy", "scored"), "NVDA": (40, "hold", "scored"), "AMD": (71, "buy", "scored")}

    body = recommendations.rank_industry("technology", fake_scorer(table))

    symbols = [s["symbol"] for s in body["stocks"]]
    assert symbols[:3] == ["MSFT", "AMD", "NVDA"]  # tie on 71 keeps curated order
    assert symbols[3:] == [s for s, _ in INDUSTRIES["technology"][1] if s not in {"MSFT", "AMD", "NVDA"}]
    assert len(symbols) == 24
    assert body["scoring"]["scored"] == 3 and body["scoring"]["status"] == "available"
    assert [w["code"] for w in body["warnings"]] == ["partially_scored"]


def test_an_outage_stops_calling_the_store_after_the_first_failure() -> None:
    calls: list[str] = []

    def down(symbol: str):
        calls.append(symbol)
        return None, None, "unavailable"

    body = recommendations.rank_industry("energy", down)

    assert len(calls) == 1
    assert body["scoring"]["status"] == "unavailable"
    assert [w["code"] for w in body["warnings"]] == ["scoring_unavailable"]
    assert len(body["stocks"]) == 24


def test_a_scoring_maker_scores_and_classifies_failures() -> None:
    from decision_maker import DecisionMaker, StaleDataError

    scorer = recommendations.make_scorer(DecisionMaker())  # no store configured: live decide is unavailable
    assert scorer("AAPL") == (None, None, "unavailable")

    class Stale:
        def decide(self, request, quant=None):
            raise StaleDataError("old")

    class Broken:
        def decide(self, request, quant=None):
            raise RuntimeError("boom")

    assert recommendations.make_scorer(Stale())("AAPL") == (None, None, "stale")
    assert recommendations.make_scorer(Broken())("AAPL") == (None, None, "error")


def test_results_are_cached_but_an_outage_is_not(monkeypatch) -> None:
    from research_api import assessment

    built = []

    class Maker:
        def decide(self, request, quant=None):
            built.append(request.symbol)
            from decision_maker import DecisionMaker, DecisionRequest

            return DecisionMaker().decide(DecisionRequest(symbol="AAPL", mode="sample"))

    monkeypatch.setattr(assessment, "get_scoring_maker", lambda: Maker())
    first = recommendations.recommended_stocks("utilities")
    again = recommendations.recommended_stocks("utilities")

    assert first is again and len(built) == 24
    assert first["scoring"]["status"] == "available"

    recommendations.reset()
    monkeypatch.setattr(assessment, "get_scoring_maker", lambda: None)
    recommendations.recommended_stocks("energy")
    monkeypatch.setattr(assessment, "get_scoring_maker", lambda: Maker())
    assert recommendations.recommended_stocks("energy")["scoring"]["status"] == "available"


def test_partial_store_outage_is_not_labeled_available_or_cached(monkeypatch) -> None:
    calls: list[str] = []

    def score_then_outage(symbol: str):
        calls.append(symbol)
        if len(calls) == 1:
            return 72, "buy", "scored"
        return None, None, "unavailable"

    monkeypatch.setattr(recommendations.assessment, "get_scoring_maker", lambda: object())
    monkeypatch.setattr(recommendations, "make_scorer", lambda maker: score_then_outage)

    first = recommendations.recommended_stocks("energy")
    calls_after_first = len(calls)
    second = recommendations.recommended_stocks("energy")

    assert first["scoring"]["status"] == "unavailable"
    assert first is not second
    assert len(calls) > calls_after_first


def test_a_scoring_maker_is_built_without_the_model_even_when_inference_is_configured() -> None:
    from research_api import assessment

    environ = {
        "DATABASE_URL": "postgresql://user:secret@localhost:5432/db",
        "OPENAI_BASE_URL": "https://example.invalid/v1",
        "OPENAI_API_KEY": "k",
        "CHAT_MODEL": "m",
        "EMBEDDING_MODEL": "e",
    }
    scoring = assessment.build_decision_maker(environ, scoring_only=True)
    full = assessment.build_decision_maker(environ)

    assert scoring is not None and full is not None
    assert scoring._agent_factory is None and full._agent_factory is not None
