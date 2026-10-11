import httpx
import pytest
from decision_maker import DecisionMaker, DecisionRequest, ProviderUnavailableError, QuantInput, StaleDataError
from fastapi.testclient import TestClient

from research_api import assessment
from research_api.app import app

LOCAL_DATABASE = "postgresql://user:secret@localhost:5432/db"


class RecordingMaker:
    """Stands in for the live decision maker; answers with the offline sample."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.calls = error, []

    def decide(self, request, quant=None):
        self.calls.append((request, quant))
        if self.error:
            raise self.error
        return DecisionMaker().decide(DecisionRequest(symbol=request.symbol, query=request.query, mode="sample"))


def post(**body):
    return TestClient(app).post("/v0/research-assessments", json=body)


def test_sample_decision_mode_runs_the_decision_maker_offline() -> None:
    response = post(symbol="nvda", mode="sample_decision", query="What about the regulator inquiry?")

    body = response.json()
    assert response.status_code == 200
    assert (body["symbol"], body["data_mode"], body["query"]) == ("NVDA", "sample", "What about the regulator inquiry?")
    assert body["assessment"]["label"] in {"buy", "hold", "sell", "insufficient_data"}
    assert body["assessment"]["decision_engine"]["name"] == "combiner-v1"
    assert {r["data_mode"] for r in body["evidence"] + body["signals"]} == {"sample"}
    assert 0 <= body["assessment"]["score"] <= 100


def test_live_mode_uses_the_decision_maker_when_one_is_configured(monkeypatch) -> None:
    maker = RecordingMaker()
    monkeypatch.setattr(assessment, "get_decision_maker", lambda: maker)

    response = post(symbol="aapl", mode="live", query="Why?", preferences={"horizon": "90d", "risk_profile": "growth"})

    request, quant = maker.calls[0]
    assert response.status_code == 200
    assert (request.symbol, request.mode, request.query) == ("AAPL", "live", "Why?")
    assert (request.preferences.horizon, request.preferences.risk_profile) == ("90d", "growth")
    assert quant is None


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ProviderUnavailableError("The evidence store is unavailable; no assessment was generated.", {"provider": "evidence_store"}), 503),
        (StaleDataError("Available evidence is older than the allowed freshness window.", {"stale_after_seconds": 86400}), 409),
    ],
)
def test_decision_errors_use_the_contract_envelope(monkeypatch, error, status) -> None:
    monkeypatch.setattr(assessment, "get_decision_maker", lambda: RecordingMaker(error))

    response = post(symbol="AAPL", mode="live")

    body = response.json()
    assert response.status_code == status
    assert body["error"] == {"code": error.code, "message": error.message, "retryable": True, "details": error.details}
    assert body["request_id"].startswith("req-")
    assert "evidence" not in body


def test_an_unexpected_failure_keeps_the_envelope_and_hides_the_cause(monkeypatch) -> None:
    monkeypatch.setattr(assessment, "get_decision_maker", lambda: RecordingMaker(RuntimeError("password=hunter2")))

    response = TestClient(app, raise_server_exceptions=False).post("/v0/research-assessments", json={"symbol": "AAPL", "mode": "live"})

    assert response.status_code == 500
    assert response.json()["error"] == {"code": "internal_error", "message": "The assessment could not be completed.", "retryable": False}
    assert "hunter2" not in response.text


def test_the_registered_math_is_handed_to_the_decision_maker(monkeypatch) -> None:
    maker = RecordingMaker()
    math = QuantInput()
    monkeypatch.setattr(assessment, "get_decision_maker", lambda: maker)
    assessment.set_quant_provider(lambda symbol, horizon: math if (symbol, horizon) == ("AAPL", "7d") else None)

    post(symbol="AAPL", mode="live", preferences={"horizon": "7d"})
    post(symbol="MSFT", mode="live")

    assert maker.calls[0][1] is math
    assert maker.calls[1][1] is None


def test_failing_math_is_reported_and_does_not_block_the_assessment(monkeypatch) -> None:
    def broken(symbol, horizon):
        raise RuntimeError("no option chain")

    monkeypatch.setattr(assessment, "get_decision_maker", lambda: RecordingMaker())
    assessment.set_quant_provider(broken)

    response = post(symbol="AAPL", mode="live")

    assert response.status_code == 200
    assert "quant_provider_failed" in [w["code"] for w in response.json()["warnings"]]


def test_request_fields_are_validated() -> None:
    assert post(symbol="AAPL", mode="live", holdings=["AAPL"]).status_code == 422
    assert post(symbol="AAPL", mode="live", preferences={"horizon": "1y"}).status_code == 422
    assert post(symbol="AAPL", mode="live", query="x" * 2001).status_code == 422
    assert post(symbol="AAPL!", mode="live").json()["error"]["code"] == "invalid_symbol"


def test_no_decision_maker_is_built_without_a_usable_store() -> None:
    assert assessment.build_decision_maker({}) is None
    assert assessment.build_decision_maker({"DATABASE_URL": "postgresql://u:p@db.example.com/db"}) is None


def test_a_store_alone_is_enough_and_missing_inference_only_removes_the_model() -> None:
    maker = assessment.build_decision_maker({"DATABASE_URL": LOCAL_DATABASE})

    assert isinstance(maker, DecisionMaker)
    assert maker._agent_factory is None
    assert (maker._use_agent_tools, maker._stale_after_seconds) == (False, 86400)


def test_scoring_only_maker_never_attaches_the_per_article_jev_judge(monkeypatch) -> None:
    monkeypatch.setattr(assessment, "_jev_tool", lambda: object())

    maker = assessment.build_decision_maker({"DATABASE_URL": LOCAL_DATABASE}, scoring_only=True)

    assert isinstance(maker, DecisionMaker)
    assert maker._article_judge is None
    assert maker._explanation_checker is None


def test_inference_settings_enable_the_model_and_tuning_is_read_from_the_environment() -> None:
    maker = assessment.build_decision_maker(
        {
            "DATABASE_URL": LOCAL_DATABASE,
            "OPENAI_BASE_URL": "https://inference.example.invalid/v1",
            "OPENAI_API_KEY": "test-key",
            "CHAT_MODEL": "hackathon-chat",
            "EMBEDDING_MODEL": "hackathon-embedding",
            "DECISION_AGENT_TOOLS": "true",
            "DECISION_STALE_AFTER_SECONDS": "259200",
        }
    )

    assert maker._agent_factory is not None
    assert (maker._agent_model, maker._use_agent_tools, maker._stale_after_seconds) == ("hackathon-chat", True, 259200)


def test_transport_reports_connection_failures_as_oserror_without_the_url(monkeypatch) -> None:
    def refuse(url, **kwargs):
        raise httpx.ConnectError("could not reach https://inference.example.invalid/v1?key=secret")

    monkeypatch.setattr(httpx, "post", refuse)

    with pytest.raises(OSError) as raised:
        assessment.httpx_transport("https://inference.example.invalid/v1/embeddings", {}, {}, 1.0)

    assert str(raised.value) == "ConnectError"


def test_transport_returns_status_and_json_body(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Response(429, json={"error": "slow down"}))

    response = assessment.httpx_transport("https://inference.example.invalid/v1/embeddings", {}, {}, 1.0)

    assert (response.status_code, response.body) == (429, {"error": "slow down"})


AKAMAI = {
    "OPENAI_BASE_URL": "https://example.invalid/v1",
    "OPENAI_API_KEY": "k",
    "CHAT_MODEL": "hackathon-chat",
    "EMBEDDING_MODEL": "hackathon-embedding",
}
AWS = {"AWS_ACCESS_KEY_ID": "a", "AWS_SECRET_ACCESS_KEY": "b", "AWS_SESSION_TOKEN": "c"}


def _explanation(env):
    from research_api.assessment import _explanation_agent
    from research_api.inference import InferenceConfigurationError, InferenceSettings

    try:
        settings = InferenceSettings.from_environ(env)
    except InferenceConfigurationError:
        settings = None
    return _explanation_agent(env, settings)


def test_explanation_uses_claude_on_bedrock_by_default_when_aws_credentials_exist() -> None:
    factory, model = _explanation({**AKAMAI, **AWS})

    assert factory is not None and model == "us.anthropic.claude-sonnet-5"


def test_explanation_model_can_be_overridden() -> None:
    _, model = _explanation({**AWS, "EXPLANATION_MODEL_ID": "us.anthropic.claude-opus-5"})

    assert model == "us.anthropic.claude-opus-5"


def test_explanation_can_be_pinned_to_akamai() -> None:
    factory, model = _explanation({**AKAMAI, **AWS, "EXPLANATION_PROVIDER": "akamai"})

    assert factory is not None and model == "hackathon-chat"


def test_explanation_falls_back_to_akamai_without_aws_credentials() -> None:
    factory, model = _explanation(AKAMAI)

    assert factory is not None and model == "hackathon-chat"


def test_explanation_is_a_template_when_neither_provider_is_configured() -> None:
    assert _explanation({}) == (None, None)


def test_unknown_explanation_provider_is_treated_as_bedrock() -> None:
    _, model = _explanation({**AWS, "EXPLANATION_PROVIDER": "nonsense"})

    assert model == "us.anthropic.claude-sonnet-5"


def test_the_decision_maker_reports_the_explanation_model_it_was_built_with(monkeypatch) -> None:
    env = {"DATABASE_URL": "postgresql://user:secret@localhost:5432/db", **AKAMAI, **AWS}

    maker = assessment.build_decision_maker(env)

    assert maker._agent_model == "us.anthropic.claude-sonnet-5" and maker._agent_factory is not None
