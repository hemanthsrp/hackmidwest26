"""Offline tests for the wording-check harness."""

import json

import pytest

from jev_tool import JevTool, evals, presets
from test_core import make_tool

EVIDENCE_FIELDS = {
    "id",
    "symbol",
    "title",
    "summary",
    "source_name",
    "source_url",
    "published_at",
    "observed_at",
    "retrieved_at",
    "data_mode",
}


def answers(noul=0.9, choice="positive", confidence=0.8, score=2.0):
    return {
        "relevant": {"type": "noul", "noul": noul},
        "direction": {"type": "choice", "choice": choice, "confidence": confidence},
        "materiality": {"type": "score", "score": score},
    }


def test_bundled_quiz_is_valid_and_covers_every_label():
    quiz = evals.load_quiz()
    items = quiz["items"]
    assert len(items) >= 15
    assert all(set(item["evidence"]) == EVIDENCE_FIELDS for item in items)
    assert {item["expected"]["direction"] for item in items} == {*presets.DIRECTION_OPTIONS, None}
    assert {item["expected"]["materiality"] for item in items} == {0, 1, 2, None}
    assert any(not item["expected"]["relevant"] for item in items)


def test_load_quiz_rejects_bad_label(tmp_path):
    quiz = evals.load_quiz()
    quiz["items"][0]["expected"]["direction"] = "bullish"
    path = tmp_path / "quiz.json"
    path.write_text(json.dumps(quiz), encoding="utf-8")
    with pytest.raises(ValueError, match="bad expected.direction"):
        evals.load_quiz(path)


def test_score_item_all_right():
    expected = {"relevant": True, "direction": "positive", "materiality": 2}
    row = evals.score_item(expected, answers(), reversed_direction="positive")
    assert row["relevant_correct"] and row["direction_correct"]
    assert row["materiality_exact"] and row["materiality_within_one"]
    assert row["direction_flipped"] is False


def test_score_item_wrong_and_flipped():
    expected = {"relevant": True, "direction": "negative", "materiality": 0}
    row = evals.score_item(expected, answers(noul=0.2), reversed_direction="mixed")
    assert not row["relevant_correct"] and not row["direction_correct"]
    assert not row["materiality_exact"] and not row["materiality_within_one"]
    assert row["direction_flipped"] is True


def test_score_item_off_topic_only_scores_relevance():
    expected = {"relevant": False, "direction": None, "materiality": None}
    row = evals.score_item(expected, answers(noul=0.1))
    assert row["relevant_correct"]
    assert row["direction_correct"] is None and row["materiality_exact"] is None
    assert row["direction_flipped"] is None


def test_summarize():
    right = {"relevant": True, "direction": "positive", "materiality": 2}
    wrong = {"relevant": True, "direction": "negative", "materiality": 2}
    rows = [
        {"expected": right, **evals.score_item(right, answers(confidence=0.9), "positive")},
        {"expected": wrong, **evals.score_item(wrong, answers(confidence=0.3), "mixed")},
    ]
    summary = evals.summarize(rows)
    assert summary["direction_accuracy"] == 0.5
    assert summary["materiality_exact"] == 1.0
    assert summary["direction_confidence_when_right"] == 0.9
    assert summary["direction_confidence_when_wrong"] == 0.3
    assert summary["direction_flip_rate_when_options_reversed"] == 0.5
    assert summary["direction_confusion"] == {"positive -> positive": 1, "negative -> positive": 1}
    assert summary["mean_input_tokens"] is None


def test_run_quiz_end_to_end_against_mock_api():
    tool, requests = make_tool()
    quiz = evals.load_quiz()
    report = evals.run_quiz(tool, quiz)
    n = len(quiz["items"])
    assert report["engine"] == "jev"
    assert report["summary"]["items"] == n
    assert len(requests) == 2 * n
    # The mock always picks the first listed option, so reversing the order flips every answer.
    assert report["summary"]["direction_flip_rate_when_options_reversed"] == 1.0
    assert report["summary"]["mean_input_tokens"] == 42
    assert list(requests[1]["questions"]["direction"]["criteria"]) == list(
        reversed(presets.DIRECTION_OPTIONS)
    )
    assert "Not an accuracy claim" in evals.format_report(report)


def test_run_quiz_reports_unavailable_when_jev_is_off():
    report = evals.run_quiz(JevTool(enabled=False), evals.load_quiz())
    assert report["engine"] == "unavailable"
    assert "disabled" in report["error"]
