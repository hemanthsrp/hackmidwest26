"""PR #19 re-review (hbot): more than one Jev result for the same evidence_id is
ambiguous. None is attached; the record is marked missing with a reason, and the
other records in the batch are unaffected."""

import logging

import pytest

from scraper_analysis.pipeline import jev_judge
from tests.test_jev_review_round3 import Tool, article, isolated, result, status  # noqa: F401


@pytest.mark.parametrize("second", [
    {"direction": "negative"},                 # conflicting
    {},                                        # identical
    {"direction": "negative", "relevant": 0.1},
])
def test_duplicate_results_mark_the_record_missing(second):
    items = [article("a"), article("b")]
    jev_judge.judge_evidence(items, tool=Tool([result("a"), result("a", **second), result("b")]))
    jev = items[0].details["jev"]
    assert status(items[0]) == "missing"
    assert jev["engine"] == "unavailable" and jev["reason"] == "duplicate_results"
    assert "direction" not in jev
    assert status(items[1]) == "ok"  # the rest of the batch is still attached


def test_three_results_for_one_record_are_still_ambiguous():
    items = [article("a")]
    jev_judge.judge_evidence(items, tool=Tool([result("a"), result("a"), result("a")]))
    assert status(items[0]) == "missing" and items[0].details["jev"]["reason"] == "duplicate_results"


def test_duplicate_records_are_counted_in_the_warning(caplog):
    items = [article("a"), article("b")]
    with caplog.at_level(logging.WARNING):
        jev_judge.judge_evidence(items, tool=Tool([result("a"), result("a"), result("b")]))
    assert any("more than one jev result" in r.getMessage() and "1 record" in r.getMessage()
               for r in caplog.records)


def test_a_duplicated_record_gets_no_sentiment_fill():
    items = [article("a")]
    jev_judge.judge_evidence(items, tool=Tool([result("a"), result("a", direction="negative")]))
    assert items[0].sentiment.direction is None


def test_malformed_first_then_valid_duplicate_is_still_ambiguous():
    # hbot: a malformed first result followed by a valid one left the record 'malformed'.
    items = [article("a"), article("b")]
    jev_judge.judge_evidence(items, tool=Tool([result("a", relevant=7.0), result("a"), result("b")]))
    assert status(items[0]) == "missing" and items[0].details["jev"]["reason"] == "duplicate_results"
    assert status(items[1]) == "ok"


# --- same-story scores must be finite and inside [0, 1] -------------------------------------

from types import SimpleNamespace  # noqa: E402


def _same_story_batch(same):
    # Two outlets, near-identical titles, so the pair is a same-story candidate.
    a, b = article("a", source="outlet-1"), article("b", source="outlet-2")
    tool = Tool([result("a"), result("b")], pairs=[SimpleNamespace(a=0, b=1, same=same)])
    jev_judge.judge_evidence([a, b], tool=tool)
    return a, b


@pytest.mark.parametrize("same", [9.0, 1.0001, -0.5, float("nan"), float("inf"), True, "0.9", None])
def test_out_of_range_or_invalid_same_story_score_creates_no_link(same):
    a, b = _same_story_batch(same)
    assert status(a) == "ok" and status(b) == "ok"
    assert not a.details["jev"].get("same_story_as")
    assert not b.details["jev"].get("same_story_as")


@pytest.mark.parametrize("same", [1.0, 0.9, jev_judge.SAME_STORY_THRESHOLD])
def test_in_range_same_story_score_still_links(same):
    a, b = _same_story_batch(same)
    assert a.details["jev"]["same_story_as"] == ["b"]
    assert b.details["jev"]["same_story_as"] == ["a"]
