"""Reviewer findings on PR #19 (adversarial review of 91170d9):

1. a malformed Jev result could stop later results from being attached;
2. records sent for judgment that got no result back went unmarked;
3. non-finite / out-of-range numbers reached grading and distorted ranking.

Offline: fake tools only, in-memory store, no network.
"""

import math
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from scraper_analysis.config import get_settings
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.pipeline import grade, ingest, jev_judge
from scraper_analysis.storage import store as store_module

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(store_module, "_store", store_module.InMemoryEvidenceStore())
    settings = get_settings()
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", "test-key")
    monkeypatch.setattr(settings, "jev_relevance_gate", 0.3)
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(jev_judge, "_tool", None)
    yield
    monkeypatch.setattr(store_module, "_store", None)


@pytest.fixture
def fill_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "jev_fill_sentiment", True)
    monkeypatch.setattr(get_settings(), "aws_access_key_id", None)


def article(i: str, source=None) -> Evidence:
    return Evidence(id=i, symbol="AAPL", title=f"Apple story {i}", summary="s", source_name=source or f"outlet-{i}",
                    source_type="general_news", retrieved_at=NOW)


def fields(**over) -> dict:
    base = {"engine": "jev", "model": "m", "question_set_version": "v", "request_id": "r", "error": None,
            "relevant": 0.9, "direction": "positive", "direction_confidence": 0.8, "content_type": "news_report",
            "content_type_confidence": 0.9, "event_type": "other", "event_type_confidence": 0.5,
            "upcoming_event": 0.1, "sensational": 0.1, "usable_content": 0.9, "materiality": 1.0,
            "materiality_confidence": 0.7}
    base.update(over)
    return base


def judgment(**over):
    return SimpleNamespace(**fields(**over))


def echo_ids(items, results):
    """Like jev_tool's judge_evidence_items, echo each payload id back as evidence_id
    (the real tool always does) unless the test set one explicitly."""
    for item, result in zip(items, results):
        if isinstance(result, SimpleNamespace) and getattr(result, "evidence_id", None) is None:
            result.evidence_id = item["id"]
        elif isinstance(result, dict) and result.get("evidence_id") is None:
            result["evidence_id"] = item["id"]
    return results


class Tool:
    def __init__(self, judgments, pairs=None):
        self.judgments, self.pairs = judgments, pairs or []

    def judge_evidence_items(self, items, companies):
        return echo_ids(items, self.judgments)

    def same_story(self, items, pairs):
        return SimpleNamespace(engine="jev", pairs=self.pairs)


def status(e: Evidence):
    return e.details.get("jev", {}).get("status")


# --- 1. one malformed result must not stop the others from being attached -------------


@pytest.mark.parametrize("bad", [None, 42, "oops", ["a", "list"], object()], ids=repr)
def test_a_non_judgment_result_does_not_stop_later_results(bad):
    items = [article("a"), article("b"), article("c")]
    jev_judge.judge_evidence(items, tool=Tool([bad, judgment(), judgment()]))
    # A non-result carries no evidence_id, so it can't be tied to any record (no positional
    # guessing since the round-3 review): its record is "missing", the others still attach.
    assert status(items[0]) == "missing" and items[0].details["jev"]["engine"] == "unavailable"
    assert [status(e) for e in items[1:]] == ["ok", "ok"]
    assert all(e.details["jev"]["engine"] == "jev" for e in items[1:])


def test_dict_shaped_results_are_accepted_and_unknown_fields_are_not_stored():
    items = [article("a"), article("b")]
    results = [{**fields(), "surprise": "x", "evidence_id": "a"}, {**fields(direction="negative"), "evidence_id": "b"}]
    jev_judge.judge_evidence(items, tool=Tool(results))
    assert [status(e) for e in items] == ["ok", "ok"]
    assert items[1].details["jev"]["direction"] == "negative"
    assert "surprise" not in items[0].details["jev"]


def test_results_are_matched_by_evidence_id_not_position():
    items = [article("a"), article("b"), article("c")]
    results = [judgment(evidence_id="c", direction="negative"), judgment(evidence_id="a", direction="positive"),
               judgment(evidence_id="b", direction="neutral")]
    jev_judge.judge_evidence(items, tool=Tool(results))
    assert [e.details["jev"]["direction"] for e in items] == ["positive", "neutral", "negative"]


def test_a_result_for_an_unknown_id_is_not_attached_to_someone_else():
    items = [article("a"), article("b")]
    jev_judge.judge_evidence(items, tool=Tool([judgment(evidence_id="zzz", direction="negative"),
                                               judgment(evidence_id="b")]))
    assert status(items[0]) == "missing" and "direction" not in items[0].details["jev"]
    assert status(items[1]) == "ok"


def test_duplicate_results_for_one_record_attach_neither():
    # Two results for one evidence_id are ambiguous: neither is attached (PR #19 re-review).
    items = [article("a"), article("b")]
    jev_judge.judge_evidence(items, tool=Tool([judgment(evidence_id="a", direction="positive"),
                                               judgment(evidence_id="a", direction="negative")]))
    assert status(items[0]) == "missing" and "direction" not in items[0].details["jev"]
    assert items[0].details["jev"]["reason"] == "duplicate_results"
    assert status(items[1]) == "missing"


@pytest.mark.parametrize("over", [
    {"direction": ["positive"]},          # unhashable: crashed the sentiment-fill lookup
    {"direction_confidence": "high"},     # str vs float comparison in the fill
    {"content_type": {"x": 1}},
    {"engine": None},
    {"engine": "something-else"},
], ids=repr)
def test_a_wrongly_typed_field_does_not_stop_later_results(fill_on, over):
    items = [article("a"), article("b"), article("c")]
    jev_judge.judge_evidence(items, tool=Tool([judgment(**over), judgment(), judgment()]))
    assert [status(e) for e in items[1:]] == ["ok", "ok"]
    assert items[2].sentiment.direction == "Bullish"  # the fill still ran for later records
    grade.grade_evidence(items)
    assert all(math.isfinite(e.details["grade"]["strength"]) for e in items)


def test_a_result_object_whose_attributes_raise_is_isolated():
    class Exploding:
        def __getattr__(self, name):
            raise RuntimeError("boom")

    items = [article("a"), article("b")]
    jev_judge.judge_evidence(items, tool=Tool([Exploding(), judgment()]))
    assert (status(items[0]), status(items[1])) == ("missing", "ok")  # its id is unreadable


@pytest.mark.parametrize("results", [None, 7, iter(())], ids=["none", "int", "empty-iter"])
def test_a_non_list_response_marks_everything_and_does_not_raise(results):
    items = [article("a"), article("b")]
    jev_judge.judge_evidence(items, tool=Tool(results))
    assert all(e.details["jev"]["engine"] == "unavailable" for e in items)
    assert {status(e) for e in items} <= {"missing", "failed"}


def test_one_bad_same_story_pair_does_not_drop_the_good_ones():
    a, b = article("a"), article("b")
    c, d = article("c"), article("d")
    for e in (a, b, c, d):
        e.title = "Apple beats earnings estimates on iPhone demand"
    pairs = [SimpleNamespace(a=0, b=1, same="very"), SimpleNamespace(a=0, b=99, same=0.9),
             SimpleNamespace(a=2, b=3, same=0.9)]
    jev_judge.judge_evidence([a, b, c, d], tool=Tool([judgment() for _ in range(4)], pairs=pairs))
    assert c.details["jev"]["same_story_as"] == ["d"] and d.details["jev"]["same_story_as"] == ["c"]
    assert "same_story_as" not in a.details["jev"]


def test_mixed_malformed_batch_through_a_real_ingest_attaches_every_valid_result(monkeypatch):
    class Mixed:
        def judge_evidence_items(self, items, companies):
            out = []
            for n, item in enumerate(items):
                out.append(None if n == 0 else judgment(evidence_id=item["id"], direction_confidence=float("nan"))
                           if n == 1 else judgment(evidence_id=item["id"]))
            return list(reversed(out))  # also out of order

        def same_story(self, items, pairs):
            return SimpleNamespace(engine="jev", pairs=[])

    jev_judge._tool = Mixed()
    stored = ingest.run_ingestion("AAPL", allow_live=False, tag=False)
    news = [e for e in stored if e.source_type in jev_judge.JUDGED_SOURCE_TYPES]
    assert len(news) >= 3
    statuses = [status(e) for e in news]
    assert all(s in {"ok", "missing", "malformed"} for s in statuses)
    assert statuses.count("ok") >= len(news) - 1
    assert len(store_module.get_store().query_evidence("AAPL")) == len(stored)


# --- 2. sent-but-unanswered records are marked, and treated as unknown -------------------


def test_short_result_list_marks_the_rest_missing():
    items = [article("a"), article("b"), article("c")]
    jev_judge.judge_evidence(items, tool=Tool([judgment()]))
    assert [status(e) for e in items] == ["ok", "missing", "missing"]
    assert items[1].details["jev"]["engine"] == "unavailable"


def test_every_judged_record_carries_a_status():
    items = [article("a"), article("b"), article("c")]
    jev_judge.judge_evidence(items, tool=Tool([
        judgment(), SimpleNamespace(engine="unavailable", error="timeout"), judgment(materiality=None)]))
    assert [status(e) for e in items] == ["ok", "unavailable", "malformed"]


def test_a_crashing_tool_marks_the_records_as_failed():
    class Boom:
        def judge_evidence_items(self, items, companies):
            raise RuntimeError("boom api_key=SECRET")

    items = [article("a"), article("b")]
    jev_judge.judge_evidence(items, tool=Boom())
    assert all(e.details["jev"] == {"engine": "unavailable", "status": "failed", "error": "jev call failed"}
               for e in items)


def test_missing_is_graded_as_unknown_not_as_a_judgment():
    items = [article("a"), article("b"), article("c"), article("d")]
    jev_judge.judge_evidence(items, tool=Tool([judgment(evidence_id="a"), judgment(evidence_id="b"),
                                               judgment(evidence_id="c")]))
    grade.grade_evidence(items)
    missing = items[3].details["grade"]
    assert missing["basis"] == "source_only" and missing["jev_status"] == "missing"
    assert missing["gated"] is False
    assert items[0].details["grade"]["jev_status"] == "ok"
    tone = grade.news_tone(items)
    assert "d" not in tone["evidence_ids"] and tone["records_judged"] == 3


def test_unjudged_filings_say_so_in_their_grade():
    filing = Evidence(id="f", symbol="AAPL", title="10-K", source_name="SEC", source_type="sec_filing",
                      retrieved_at=NOW)
    grade.grade_evidence([filing])
    assert filing.details["grade"]["jev_status"] == "not_sent"


# --- 3. non-finite / out-of-range numbers never reach grading as numbers ----------------

INVALID = [float("nan"), float("inf"), float("-inf"), "0.9", 1.5, -0.2, True]


@pytest.mark.parametrize("bad", INVALID, ids=repr)
@pytest.mark.parametrize("field", ["direction_confidence", "content_type_confidence", "event_type_confidence",
                                   "materiality_confidence", "upcoming_event"])
def test_invalid_optional_numbers_are_stored_as_missing_and_marked(field, bad):
    item = article("a")
    jev_judge.judge_evidence([item], tool=Tool([judgment(**{field: bad})]))
    stored = item.details["jev"]
    assert stored["status"] == "ok" and stored[field] is None
    assert stored["invalid_fields"] == [field]


@pytest.mark.parametrize("bad", INVALID, ids=repr)
def test_invalid_direction_confidence_does_not_inflate_strength(bad):
    clean, odd, unknown = article("clean"), article("odd"), article("unknown")
    jev_judge.judge_evidence([clean, odd, unknown], tool=Tool([
        judgment(direction_confidence=0.8), judgment(direction_confidence=bad), judgment(direction_confidence=None)]))
    grade.grade_evidence([clean, odd, unknown])
    s = {e.id: e.details["grade"]["strength"] for e in (clean, odd, unknown)}
    assert all(math.isfinite(v) for v in s.values())
    assert s["odd"] == s["unknown"] < s["clean"]
    assert grade.rank([odd, clean])[0].id == "clean"


@pytest.mark.parametrize("field,bad", [
    ("relevant", 1.5), ("relevant", -0.1), ("sensational", 2.0), ("usable_content", -1.0),
    ("materiality", 3.0), ("materiality", -0.5), ("relevant", float("-inf")), ("materiality", "2"),
])
def test_out_of_range_required_numbers_make_the_judgment_malformed(field, bad):
    items = [article("a"), article("b")]
    jev_judge.judge_evidence(items, tool=Tool([judgment(**{field: bad}), judgment()]))
    assert status(items[0]) == "malformed" and field in items[0].details["jev"]["error"]
    assert status(items[1]) == "ok"
    grade.grade_evidence(items)
    assert items[0].details["grade"]["basis"] == "source_only"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 7.0, "0.9"], ids=repr)
def test_stored_judgment_with_bad_numbers_is_graded_as_unknown(bad):
    """Judgments written by older code (or edited in the store) are re-checked at grading."""
    stale = article("stale")
    stale.details["jev"] = {**fields(direction_confidence=bad), "evidence_id": "stale"}
    record = grade.grade_record(stale, 0.3)
    assert math.isfinite(record["strength"]) and record["strength"] <= 1.0
    assert record["basis"] == "source_only" and record["jev_status"] == "malformed"
    stale.details["grade"] = record
    assert "relevance_to_symbol" not in grade.agent_view(stale)


def test_non_finite_credibility_falls_back_to_the_default():
    item = article("a")
    item.credibility.overall_score = float("nan")
    record = grade.grade_record(item, 0.3)
    assert record["strength"] == grade.DEFAULT_CREDIBILITY
