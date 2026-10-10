"""Offline tests for check_explanation and its wording-check harness."""

import json

import pytest

from jev_tool import JevTool, evals_explanation, presets
from test_core import make_tool

EVIDENCE = [{"id": "e1", "title": "Acme raises forecast", "summary": "Acme raised its forecast.", "extra": 1}]


def test_split_sentences():
    assert presets.split_sentences(" Assessment: hold. Acme raised its forecast!  Is that enough? ") == [
        "Assessment: hold.",
        "Acme raised its forecast!",
        "Is that enough?",
    ]
    assert presets.split_sentences("") == []


def test_check_explanation_asks_one_question_per_sentence():
    tool, requests = make_tool()
    check = tool.check_explanation("Acme raised its forecast. Buy it now.", EVIDENCE)
    assert check.engine == "jev"
    assert check.question_set_version == presets.EXPLANATION_QUESTION_SET_VERSION
    assert [c.text for c in check.claims] == ["Acme raised its forecast.", "Buy it now."]
    assert all(c.supported == 0.9 for c in check.claims)
    assert check.personal_advice == 0.9 and check.promises_outcome == 0.9
    assert check.input_tokens == 42 and not check.claims_truncated

    body = requests[0]
    assert set(body["questions"]) == {"claim_0", "claim_1", "personal_advice", "promises_outcome"}
    assert "claims[1]" in body["questions"]["claim_1"]["instructions"]
    assert body["state"]["claims"] == ["Acme raised its forecast.", "Buy it now."]
    # Only id, title and summary of each evidence item are sent.
    assert body["state"]["evidence"] == [
        {"id": "e1", "title": "Acme raises forecast", "summary": "Acme raised its forecast."}
    ]


def test_check_explanation_caps_the_number_of_claims():
    tool, requests = make_tool()
    check = tool.check_explanation(" ".join(f"Claim {i}." for i in range(20)), EVIDENCE)
    assert len(check.claims) == presets.MAX_CLAIMS and check.claims_truncated
    assert len(requests[0]["questions"]) == presets.MAX_CLAIMS + 2


def test_check_explanation_when_jev_is_off():
    check = JevTool(enabled=False).check_explanation("Acme raised its forecast.", EVIDENCE)
    assert check.engine == "unavailable"
    assert check.claims == [] and check.personal_advice is None


def test_bundled_quiz_is_valid():
    quiz = evals_explanation.load_quiz()
    expected = [case["expected"] for case in quiz["cases"]]
    assert len(expected) >= 10
    assert {value for e in expected for value in e["claims"]} == {True, False, None}
    assert {e["personal_advice"] for e in expected} >= {True, False}
    assert {e["promises_outcome"] for e in expected} >= {True, False}


def test_load_quiz_rejects_wrong_claim_count(tmp_path):
    quiz = evals_explanation.load_quiz()
    quiz["cases"][0]["expected"]["claims"].append(True)
    path = tmp_path / "quiz.json"
    path.write_text(json.dumps(quiz), encoding="utf-8")
    with pytest.raises(ValueError, match="sentences but"):
        evals_explanation.load_quiz(path)


def test_run_quiz_scores_against_the_mock():
    tool, requests = make_tool()
    quiz = evals_explanation.load_quiz()
    report = evals_explanation.run_quiz(tool, quiz)
    summary = report["summary"]
    assert report["engine"] == "jev" and summary["cases"] == len(quiz["cases"]) == len(requests)
    # The mock answers 0.9 to everything: supported claims pass, unsupported ones are missed.
    assert summary["supported_claims_passed"] == 1.0
    assert summary["unsupported_claims_caught"] == 0.0
    assert 0 < summary["personal_advice_accuracy"] < 1
    assert "Not an accuracy claim" in evals_explanation.format_report(report)


def test_run_quiz_reports_unavailable_when_jev_is_off():
    report = evals_explanation.run_quiz(JevTool(enabled=False), evals_explanation.load_quiz())
    assert report["engine"] == "unavailable"
