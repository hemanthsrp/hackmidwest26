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


def answers(noul=0.9, choice="positive", confidence=0.8, score=2.0, content_type="news_report"):
    return {
        "content_type": {"type": "choice", "choice": content_type, "confidence": 0.9},
        "event_type": {"type": "choice", "choice": "earnings_or_guidance", "confidence": 0.9},
        "upcoming_event": {"type": "noul", "noul": 0.1},
        "sensational": {"type": "noul", "noul": 0.1},
        "usable_content": {"type": "noul", "noul": 0.9},
        "relevant": {"type": "noul", "noul": noul},
        "direction": {"type": "choice", "choice": choice, "confidence": confidence},
        "materiality": {"type": "score", "score": score},
    }


def test_bundled_quiz_is_valid_and_covers_every_label():
    quiz = evals.load_quiz()
    items = quiz["items"]
    assert len(items) >= 15
    assert all(set(item["evidence"]) == EVIDENCE_FIELDS for item in items)
    expected = [item["expected"] for item in items]
    accepted = lambda field: set().union(*(evals._accepted(e[field]) for e in expected))
    assert accepted("direction") == {*presets.DIRECTION_OPTIONS, None}
    assert accepted("materiality") == {0, 1, 2, None}
    assert accepted("content_type") == set(presets.CONTENT_TYPE_OPTIONS)
    assert accepted("event_type") >= set(presets.EVENT_TYPE_OPTIONS) - {"market_or_macro"}
    assert accepted("upcoming_event") == {True, False, None}
    assert accepted("sensational") == {True, False, None}
    assert accepted("usable_content") == {True, False}
    assert any(not item["expected"]["relevant"] for item in items)


def test_load_quiz_rejects_bad_label(tmp_path):
    quiz = evals.load_quiz()
    quiz["items"][0]["expected"]["direction"] = ["positive", "bullish"]
    path = tmp_path / "quiz.json"
    path.write_text(json.dumps(quiz), encoding="utf-8")
    with pytest.raises(ValueError, match="bad expected.direction"):
        evals.load_quiz(path)


def test_score_item_all_right():
    expected = {"relevant": True, "direction": "positive", "materiality": 2, "content_type": "news_report"}
    row = evals.score_item(expected, answers(), reversed_direction="positive")
    assert row["relevant_correct"] and row["direction_correct"] and row["content_type_correct"]
    assert row["materiality_exact"] and row["materiality_within_one"]
    assert row["direction_flipped"] is False


def test_score_item_wrong_and_flipped():
    expected = {"relevant": True, "direction": "negative", "materiality": 0, "content_type": "other"}
    row = evals.score_item(expected, answers(noul=0.2), reversed_direction="mixed")
    assert not row["relevant_correct"] and not row["direction_correct"]
    assert not row["content_type_correct"]
    assert not row["materiality_exact"] and not row["materiality_within_one"]
    assert row["direction_flipped"] is True


def test_score_item_off_topic_only_scores_relevance():
    expected = {"relevant": False, "direction": None, "materiality": None, "content_type": "news_report"}
    row = evals.score_item(expected, answers(noul=0.1))
    assert row["relevant_correct"] and row["content_type_correct"]
    assert row["direction_correct"] is None and row["materiality_exact"] is None
    assert row["direction_flipped"] is None


def test_score_item_event_type_and_upcoming_event():
    expected = {
        "relevant": True,
        "direction": "positive",
        "materiality": 2,
        "content_type": "news_report",
        "event_type": ["earnings_or_guidance", "other"],
        "upcoming_event": True,
    }
    row = evals.score_item(expected, answers())
    assert row["event_type_correct"] is True
    assert row["upcoming_event_correct"] is False
    unscored = evals.score_item({**expected, "event_type": None, "upcoming_event": None}, answers())
    assert unscored["event_type_correct"] is None and unscored["upcoming_event_correct"] is None
    flagged = evals.score_item({**expected, "sensational": True, "usable_content": True}, answers())
    assert flagged["sensational_correct"] is False and flagged["usable_content_correct"] is True
    assert row["sensational_correct"] is None


def test_summarize():
    right = {"relevant": True, "direction": ["neutral", "positive"], "materiality": [1, 2], "content_type": "news_report"}
    wrong = {"relevant": True, "direction": "negative", "materiality": 2, "content_type": "other"}
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
    assert summary["content_type_accuracy"] == 0.5
    assert summary["direction_confusion"] == {"neutral/positive -> positive": 1, "negative -> positive": 1}
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
