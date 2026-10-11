"""Offline tests for the same-story wording-check harness."""

import json

import pytest

from jev_tool import JevTool, evals_pairs
from test_core import make_tool


def test_bundled_quiz_is_valid():
    quiz = evals_pairs.load_quiz()
    assert len(quiz["pairs"]) >= 10
    assert {pair["same"] for pair in quiz["pairs"]} == {True, False, None}


def test_load_quiz_rejects_unknown_item(tmp_path):
    quiz = evals_pairs.load_quiz()
    quiz["pairs"][0]["a"] = "missing"
    path = tmp_path / "quiz.json"
    path.write_text(json.dumps(quiz), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown item"):
        evals_pairs.load_quiz(path)


def test_run_quiz_scores_against_the_mock():
    tool, requests = make_tool()
    report = evals_pairs.run_quiz(tool, evals_pairs.load_quiz())
    summary = report["summary"]
    assert report["engine"] == "jev" and len(requests) == 1
    # The mock answers 0.9 to everything: same-story pairs are found, different ones are not kept apart.
    assert summary["same_story_found"] == 1.0
    assert summary["different_story_kept_apart"] == 0.0
    assert "Not an accuracy claim" in evals_pairs.format_report(report)


def test_run_quiz_reports_unavailable_when_jev_is_off():
    assert evals_pairs.run_quiz(JevTool(enabled=False), evals_pairs.load_quiz())["engine"] == "unavailable"
