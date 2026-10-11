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
