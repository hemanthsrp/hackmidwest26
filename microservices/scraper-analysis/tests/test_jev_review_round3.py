"""Reviewer findings on PR #19 (review of e399124):

1. an unidentified Jev result could be assigned to the wrong record (positional fallback);
2. a malformed ``same_story_as`` list made the ranked /evidence view raise (500);
3. legacy non-finite strength / numbers stayed usable at read time (NaN in sort keys / JSON).

Offline: fake tools only, in-memory store, no network.
"""

import json
import math
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from scraper_analysis.api import app
from scraper_analysis.config import get_settings
from scraper_analysis.models.evidence import Credibility, Evidence
from scraper_analysis.pipeline import grade, jev_judge
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


def article(i: str, source=None) -> Evidence:
    return Evidence(id=i, symbol="AAPL", title=f"Apple story {i}", summary="s", source_name=source or f"outlet-{i}",
                    source_type="general_news", retrieved_at=NOW)


def result(evidence_id=None, **over):
    base = {"engine": "jev", "model": "m", "question_set_version": "v", "request_id": "r", "error": None,
            "relevant": 0.9, "direction": "positive", "direction_confidence": 0.8, "content_type": "news_report",
            "content_type_confidence": 0.9, "event_type": "other", "event_type_confidence": 0.5,
            "upcoming_event": 0.1, "sensational": 0.1, "usable_content": 0.9, "materiality": 1.0,
            "materiality_confidence": 0.7, "evidence_id": evidence_id}
    base.update(over)
    return SimpleNamespace(**base)


class Tool:
    def __init__(self, judgments, pairs=None):
        self.judgments, self.pairs = judgments, pairs or []

    def judge_evidence_items(self, items, companies):
        return self.judgments

    def same_story(self, items, pairs):
        return SimpleNamespace(engine="jev", pairs=self.pairs)


def status(e: Evidence):
    return e.details.get("jev", {}).get("status")


# --- 1. a result without a valid evidence_id is never attached to a record -------------------


def test_an_unidentified_result_in_a_mixed_batch_is_not_given_to_the_unanswered_record():
    # a and c answered by id; the id-less result (which was really about something else)
    # used to land on b purely because of its position.
    items = [article("a"), article("b"), article("c")]
    jev_judge.judge_evidence(items, tool=Tool([
        result("a"), result(None, direction="negative", relevant=0.01), result("c")]))
    assert [status(e) for e in items] == ["ok", "missing", "ok"]
    assert "direction" not in items[1].details["jev"]


def test_a_reordered_list_without_ids_is_not_matched_by_position():
    items = [article("a"), article("b")]
    jev_judge.judge_evidence(items, tool=Tool([result(None, direction="negative"), result(None)]))
    assert [status(e) for e in items] == ["missing", "missing"]
    assert all(e.details["jev"]["engine"] == "unavailable" for e in items)


def test_a_short_list_without_ids_marks_everything_missing():
    items = [article("a"), article("b"), article("c")]
    jev_judge.judge_evidence(items, tool=Tool([result(None)]))
    assert [status(e) for e in items] == ["missing", "missing", "missing"]


@pytest.mark.parametrize("bad_id", ["", 7, ["a"], {"id": "a"}, b"a"], ids=repr)
def test_a_result_with_an_invalid_evidence_id_is_dropped(bad_id):
    items = [article("a"), article("b")]
    jev_judge.judge_evidence(items, tool=Tool([result(bad_id, direction="negative"), result("b")]))
    assert [status(e) for e in items] == ["missing", "ok"]


def test_dropped_results_are_counted(caplog):
    items = [article("a"), article("b")]
    with caplog.at_level("WARNING"):
        jev_judge.judge_evidence(items, tool=Tool([result(None), result("zzz"), result("b")]))
    assert any("dropped 2" in r.getMessage() for r in caplog.records)


# --- 2. malformed same_story_as never reaches a reader unsanitised -----------------------------


BAD_SAME_STORY = [
    "b",                    # not a list
    None,
    42,
    {"b": 1},
    [None, 7, ["b"], {"x": 1}, "b"],   # mixed junk around one valid id
    [["nested"]],
    ["a", "a", "b", "b"],   # self-reference and duplicates
    ["unknown-id"],
    [math.nan, "b"],
]


@pytest.mark.parametrize("same", BAD_SAME_STORY, ids=repr)
def test_sanitised_same_story_ids_are_strings_without_self_or_duplicates(same):
    ids = jev_judge.same_story_ids({"same_story_as": same}, self_id="a")
    assert all(isinstance(i, str) and i and i != "a" for i in ids)
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("same", BAD_SAME_STORY, ids=repr)
def test_grading_and_tone_tolerate_malformed_same_story(same):
    jv = vars(result()).copy()
    jv.pop("evidence_id")
    items = [Evidence(id=i, symbol="AAPL", title=f"t {i}", summary="s", source_name="CNBC",
                      source_type="general_news", published_at=NOW, retrieved_at=NOW,
                      credibility=Credibility(overall_score=0.8),
                      details={"jev": {**jv, "status": "ok", "same_story_as": same if i == "a" else []}})
             for i in ("a", "b", "c")]
    for e in items:
        e.details["grade"] = grade.grade_record(e, 0.3)
    graded = items[0].details["grade"]
    assert graded["basis"] == "jev"  # a bad link list never discards a valid judgment
    assert graded["factors"]["same_story"] <= 1.0 + grade.SAME_STORY_BONUS_PER_OUTLET  # at most "b"
    tone = grade.news_tone(items, NOW)
    assert tone["records_judged"] == 3
    grade.rank(items, NOW)


@pytest.mark.parametrize("same", BAD_SAME_STORY, ids=repr)
def test_ranked_endpoint_does_not_500_on_malformed_stored_same_story(same):
    jv = vars(result()).copy()
    jv.pop("evidence_id")
    items = []
    for i in ("a", "b", "c"):
        e = Evidence(id=i, symbol="AAPL", title=f"t {i}", summary="s", source_name="CNBC",
                     source_type="general_news", published_at=NOW, retrieved_at=NOW,
                     credibility=Credibility(overall_score=0.8), details={"jev": {**jv, "status": "ok"}})
        e.details["grade"] = grade.grade_record(e, 0.3)
        items.append(e)
    # Written by older code (or hand-edited): the stored link list is junk.
    items[0].details["jev"]["same_story_as"] = same
    store_module.get_store().save_evidence(items)
    client = TestClient(app, raise_server_exceptions=False)
    for params in ({"ranked": True}, {"relevant_only": True}, {"ranked": True, "relevant_only": True}):
        response = client.get("/evidence", params={"symbol": "AAPL", **params})
        assert response.status_code == 200, response.text
        assert len(response.json()["evidence"]) == 3


def test_same_story_marking_does_not_store_duplicate_links():
    items = [article("a", "CNBC"), article("b", "Reuters")]
    for e in items:
        e.title = "Apple beats earnings estimates on strong iPhone sales"
    pair = SimpleNamespace(a=0, b=1, same=0.9)
    jev_judge.judge_evidence(items, tool=Tool([result("a"), result("b")], pairs=[pair, pair]))
    assert items[0].details["jev"]["same_story_as"] == ["b"]
    assert items[1].details["jev"]["same_story_as"] == ["a"]


# --- 3. legacy non-finite / out-of-range numbers are unknown at read time ----------------------


LEGACY_BAD = [math.nan, math.inf, -math.inf, "NaN", "0.9", None, True, 5.0, -0.5, [0.5], {"v": 1}]


def _graded(i, strength, published=NOW):
    return Evidence(id=i, symbol="AAPL", title=f"t {i}", summary="s", source_name="CNBC",
                    source_type="general_news", published_at=published, retrieved_at=NOW,
                    details={"grade": {"version": "grade-v1", "basis": "jev", "strength": strength, "gated": False,
                                       "gate_reasons": [], "factors": {}}})


@pytest.mark.parametrize("bad", LEGACY_BAD, ids=repr)
def test_legacy_bad_strength_is_unknown_at_read_time(bad):
    assert grade.current_strength(_graded("x", bad), NOW) is None


@pytest.mark.parametrize("bad", LEGACY_BAD, ids=repr)
def test_ranking_with_legacy_bad_strength_is_deterministic(bad):
    def batch():
        return [_graded("bad1", bad), _graded("hi", 0.9), _graded("bad2", bad), _graded("lo", 0.2),
                _graded("ungraded-ish", None)]

    first = [e.id for e in grade.rank(batch(), NOW)]
    # valid strengths first, strongest first; every unknown after them in original order
    assert first[:2] == ["hi", "lo"]
    assert first[2:] == ["bad1", "bad2", "ungraded-ish"]
    reordered = list(reversed(batch()))
    assert [e.id for e in grade.rank(reordered, NOW)][:2] == ["hi", "lo"]


def test_nan_strength_used_to_scramble_the_sort():
    # With NaN as a sort key, sorted() leaves valid items out of order.
    items = [_graded("lo", 0.1), _graded("nan", math.nan), _graded("hi", 0.9), _graded("mid", 0.5)]
    assert [e.id for e in grade.rank(items, NOW)] == ["hi", "mid", "lo", "nan"]


@pytest.mark.parametrize("bad", [math.nan, math.inf, "NaN", -1.0, 3.0], ids=repr)
def test_legacy_bad_judgment_numbers_are_not_used(bad):
    jv = {**vars(result()), "status": "ok"}
    jv.pop("evidence_id")
    for name in ("relevant", "materiality", "direction_confidence", "sensational", "usable_content"):
        e = Evidence(id="x", symbol="AAPL", title="t", summary="s", source_name="CNBC", source_type="general_news",
                     published_at=NOW, retrieved_at=NOW, details={"jev": {**jv, name: bad}})
        g = grade.grade_record(e, 0.3)
        assert g["basis"] == "source_only" and math.isfinite(g["strength"])


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, "NaN"], ids=repr)
def test_ranked_endpoint_with_legacy_nan_rows_returns_finite_json(bad):
    rows = [_graded("hi", 0.9), _graded("bad", bad), _graded("lo", 0.2, published=NOW - timedelta(hours=1))]
    rows[1].details["grade"]["factors"] = {"relevance": bad}
    rows[1].details["jev"] = {**{k: v for k, v in vars(result()).items() if k != "evidence_id"},
                              "status": "ok", "relevant": bad}
    rows[1].credibility = Credibility(overall_score=math.nan)
    store_module.get_store().save_evidence(rows)
    client = TestClient(app, raise_server_exceptions=False)
    for params in ({"ranked": True}, {"relevant_only": True}, {}):
        response = client.get("/evidence", params={"symbol": "AAPL", **params})
        assert response.status_code == 200, response.text
        body = response.text
        # strict JSON: no NaN / Infinity tokens anywhere
        json.loads(body, parse_constant=lambda c: pytest.fail(f"non-finite {c} in response"))
    ranked = client.get("/evidence", params={"symbol": "AAPL", "ranked": True}).json()
    assert [e["id"] for e in ranked["evidence"]][:2] == ["hi", "lo"]
    assert ranked["evidence"][2]["id"] == "bad" and ranked["evidence"][2]["strength_now"] is None


def test_agent_view_and_is_gated_tolerate_a_malformed_grade():
    for bad_grade in ("junk", None, 3, {"strength": math.nan}, {"gate_reasons": None, "strength": 0.5}):
        e = _graded("x", 0.5)
        e.details["grade"] = bad_grade
        view = grade.agent_view(e)
        assert all(not isinstance(v, float) or math.isfinite(v) for v in view.values())
        assert grade.is_gated(e) in (True, False)
