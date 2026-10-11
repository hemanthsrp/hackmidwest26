"""Offline tests. The real TypeSafe SDK client runs against a mock HTTP transport."""

import json

import httpx2
import pytest
from typesafe_sdk import RetryPolicy, TypeSafeClient

from jev_tool import ARTICLE_QUESTION_SET_VERSION, JevTool

MODEL = "jev-1.13.0"


def _answer(question: dict) -> dict:
    kind = question["type"]
    if kind == "noul":
        return {"type": "noul", "noul": 0.9}
    if kind == "choice":
        names = list(question["criteria"])
        probabilities = {name: 0.0 for name in names}
        probabilities[names[0]] = 1.0
        return {"type": "choice", "choice": names[0], "confidence": 1.0, "probabilities": probabilities}
    levels = question["criteria"]
    probabilities = {str(i): 0.0 for i in range(len(levels))}
    probabilities[str(len(levels) - 1)] = 1.0
    return {
        "type": "score",
        "score": float(len(levels) - 1),
        "confidence": 1.0,
        "legend": {str(i): level for i, level in enumerate(levels)},
        "probabilities": probabilities,
    }


def make_tool(status: int = 200) -> tuple[JevTool, list[dict]]:
    requests: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        requests.append(body)
        if status != 200:
            return httpx2.Response(status, json={"error": "nope"})
        return httpx2.Response(
            200,
            headers={"x-typesafe-request-id": "req_test"},
            json={
                "model": MODEL,
                "answers": {name: _answer(q) for name, q in body["questions"].items()},
                "usage": {"input_tokens": 42, "output_tokens": 0},
            },
        )

    client = TypeSafeClient(
        api_key="test-key",
        model=MODEL,
        transport=httpx2.MockTransport(handler),
        retry=RetryPolicy(max_retries=0),
    )
    return JevTool(enabled=True, client=client), requests


def test_disabled_returns_unavailable_without_calling_anything():
    tool = JevTool(enabled=False)
    result = tool.check("some text", "Is this about billing?")
    assert result.engine == "unavailable"
    assert result.probability is None
    assert "disabled" in result.error
    assert tool._client is None


def test_check():
    tool, requests = make_tool()
    result = tool.check("I was charged twice.", "Is this about billing?", true_means="Mentions a charge.")
    assert (result.engine, result.model, result.request_id) == ("jev", MODEL, "req_test")
    assert result.probability == 0.9
    question = requests[0]["questions"]["q"]
    assert question["type"] == "noul"
    assert question["criteria"]["true"] == "Mentions a charge."
    assert requests[0]["model"] == MODEL
    assert requests[0]["state"] == {"text": "I was charged twice."}


def test_check_without_criteria_sends_none():
    tool, requests = make_tool()
    tool.check("text", "Is this about billing?")
    assert not requests[0]["questions"]["q"].get("criteria")


def test_classify():
    tool, requests = make_tool()
    result = tool.classify("text", "What is the tone?", {"calm": None, "angry": "Hostile wording."})
    assert result.choice == "calm"
    assert result.probabilities == {"calm": 1.0, "angry": 0.0}
    assert result.confidence == 1.0
    assert requests[0]["questions"]["q"]["criteria"] == {"calm": None, "angry": "Hostile wording."}


def test_score():
    tool, requests = make_tool()
    result = tool.score("text", "How urgent?", ["can wait", "this week", "today"])
    assert result.score == 2.0
    assert result.levels == ["can wait", "this week", "today"]
    assert result.probabilities == {"0": 0.0, "1": 0.0, "2": 1.0}
    assert requests[0]["questions"]["q"]["criteria"] == ["can wait", "this week", "today"]


def test_evaluate_accepts_raw_question_dicts():
    tool, _ = make_tool()
    result = tool.evaluate(
        {"message": "hello"},
        {
            "a": {"type": "noul", "instructions": "Is this a greeting?"},
            "b": {"type": "choice", "instructions": "Language?", "criteria": {"en": None, "fr": None}},
        },
    )
    assert result.engine == "jev"
    assert result.answers["a"] == {"type": "noul", "noul": 0.9}
    assert result.answers["b"]["choice"] == "en"
    assert result.input_tokens == 42


def test_judge_article():
    tool, requests = make_tool()
    judgment = tool.judge_article("ACME", "Acme Corp", "Acme recalls product", "Acme is recalling...")
    assert judgment.engine == "jev"
    assert judgment.question_set_version == ARTICLE_QUESTION_SET_VERSION
    assert judgment.relevant == 0.9
    assert judgment.direction == "negative"
    assert set(judgment.direction_probabilities) == {"negative", "neutral", "positive", "mixed"}
    assert judgment.content_type == "company_announcement"
    assert judgment.event_type == "earnings_or_guidance"
    assert judgment.upcoming_event == 0.9
    assert judgment.sensational == 0.9 and judgment.usable_content == 0.9
    assert judgment.input_tokens == 42
    assert judgment.materiality == 2.0
    body = requests[0]
    assert body["state"]["company"] == {"name": "Acme Corp", "ticker": "ACME"}
    assert {q["type"] for q in body["questions"].values()} == {"noul", "choice", "score"}
    assert len(requests) == 1


def test_judge_evidence_takes_contract_shape():
    tool, requests = make_tool()
    evidence = {
        "id": "sample-acme-news-001",
        "symbol": "ACME",
        "title": "Sample ACME earnings update",
        "summary": "Fixture-only summary for the demo.",
        "source_name": "Fixture News",
        "data_mode": "sample",
    }
    judgment = tool.judge_evidence(evidence, "Acme Corp")
    assert judgment.evidence_id == "sample-acme-news-001"
    assert judgment.engine == "jev"
    assert requests[0]["state"]["article"] == {
        "title": "Sample ACME earnings update",
        "summary": "Fixture-only summary for the demo.",
    }

    judgments = tool.judge_evidence_items([evidence, evidence], {"ACME": "Acme Corp"})
    assert [j.evidence_id for j in judgments] == ["sample-acme-news-001"] * 2


def test_judge_evidence_keeps_id_when_jev_is_off():
    judgment = JevTool(enabled=False).judge_evidence(
        {"id": "e1", "symbol": "ACME", "title": "t", "summary": "s"}, "Acme Corp"
    )
    assert (judgment.evidence_id, judgment.engine) == ("e1", "unavailable")


def test_load_env_does_not_override_existing(tmp_path, monkeypatch):
    from jev_tool import load_env

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\r\nJEV_TEST_NEW='from-file'\r\nJEV_TEST_SET=from-file\r\nJEV_TEST_EMPTY=\r\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JEV_TEST_SET", "from-shell")
    monkeypatch.delenv("JEV_TEST_NEW", raising=False)
    assert load_env(env_file) == env_file
    import os

    assert os.environ["JEV_TEST_NEW"] == "from-file"
    assert os.environ["JEV_TEST_SET"] == "from-shell"
    assert "JEV_TEST_EMPTY" not in os.environ
    monkeypatch.delenv("JEV_TEST_NEW")
    assert load_env(tmp_path / "missing.env") is None


def test_same_story_asks_one_question_per_pair():
    tool, requests = make_tool()
    items = [{"title": f"t{i}", "summary": "s", "id": i} for i in range(3)]
    result = tool.same_story(items, [(0, 1), (1, 2)])
    assert result.engine == "jev"
    assert [(p.a, p.b, p.same) for p in result.pairs] == [(0, 1, 0.9), (1, 2, 0.9)]
    body = requests[0]
    assert body["state"]["items"][0] == {"title": "t0", "summary": "s"}
    assert "items[1]" in body["questions"]["pair_1"]["instructions"]
    assert "items[2]" in body["questions"]["pair_1"]["instructions"]


def test_same_story_with_no_pairs_makes_no_call_and_caps_pairs():
    tool, requests = make_tool()
    assert tool.same_story([], []).pairs == [] and requests == []
    many = [(0, 1)] * 50
    result = tool.same_story([{"title": "a"}, {"title": "b"}], many)
    assert len(result.pairs) == 40 and result.pairs_truncated
    assert JevTool(enabled=False).same_story([{}, {}], [(0, 1)]).engine == "unavailable"


def test_judge_articles_keeps_order():
    tool, requests = make_tool()
    articles = [
        {"symbol": "ACME", "company": "Acme Corp", "title": f"t{i}", "summary": "s"} for i in range(5)
    ]
    judgments = tool.judge_articles(articles)
    assert len(judgments) == 5 and all(j.engine == "jev" for j in judgments)
    assert len(requests) == 5


@pytest.mark.parametrize("status", [401, 422, 429, 529])
def test_api_errors_become_unavailable(status):
    tool, _ = make_tool(status=status)
    result = tool.judge_article("ACME", "Acme Corp", "title", "summary")
    assert result.engine == "unavailable"
    assert result.direction is None
    assert str(status) in result.error
    assert "test-key" not in result.error


def test_api_key_can_be_passed_instead_of_read_from_the_environment(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    tool = JevTool(enabled=True, api_key="explicit-key")
    tool._get_client()  # raises TypeSafeError if no key were available
    tool.close()


def test_missing_api_key_becomes_unavailable(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = JevTool(enabled=True).check("text", "Is this about billing?")
    assert result.engine == "unavailable"
    assert result.error
