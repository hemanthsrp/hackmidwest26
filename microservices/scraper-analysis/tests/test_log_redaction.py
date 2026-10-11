"""Reviewer finding on PR #19: failed / malformed Jev calls sanitized the *stored*
error, but ``exc_info=True`` still wrote the raw exception text (and traceback) to
the logs -- including a configured API key and tokened URLs.

Every provider-failure log path (Jev judge, Jev briefing review, grading, Bedrock
tagging and briefing, Akamai embeddings) must log a sanitized one-line summary:
no secret, no URL query, no traceback. Offline: fake tools/agents only.
"""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from scraper_analysis.agents import jev_guard, tagging_agent
from scraper_analysis.agents import synthesis_agent as sa
from scraper_analysis.config import get_settings
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.pipeline import grade, jev_judge
from scraper_analysis.storage import embeddings
from scraper_analysis.storage import store as store_module

from .test_jev_guard import EVIDENCE, briefing, point

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
TS_KEY = "ts-DUMMY-typesafe-key-8f3a9c"
AWS_SECRET = "aws-DUMMY-secret-access-key-77"
AKAMAI_KEY = "akm-DUMMY-inference-key-55"
URL_TOKEN = "URLTOKEN-q9w8e7"
LEAKY = (
    f"provider rejected key {TS_KEY} / {AWS_SECRET} / {AKAMAI_KEY} "
    f"at https://user:pw@api.provider.example/v1/judge?token={URL_TOKEN}"
)
SECRETS = (TS_KEY, AWS_SECRET, AKAMAI_KEY, URL_TOKEN, "user:pw")


@pytest.fixture(autouse=True)
def configured(monkeypatch, caplog):
    settings = get_settings()
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", TS_KEY)
    monkeypatch.setattr(settings, "aws_access_key_id", "AKIA-DUMMY")
    monkeypatch.setattr(settings, "aws_secret_access_key", AWS_SECRET)
    monkeypatch.setattr(settings, "akamai_inference_base_url", "https://inference.example")
    monkeypatch.setattr(settings, "akamai_inference_api_key", AKAMAI_KEY)
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(jev_judge, "_tool", None)
    caplog.set_level(logging.DEBUG)
    yield


def assert_clean(caplog, capfd, expect_type: str):
    out, err = capfd.readouterr()
    logged = caplog.text
    for secret in SECRETS:
        assert secret not in logged, f"{secret!r} leaked into logs:\n{logged}"
        assert secret not in out and secret not in err, f"{secret!r} leaked to stdout/stderr"
    assert "Traceback" not in logged
    assert all(r.exc_info is None and r.exc_text is None for r in caplog.records)
    # still useful: the failure type is in the one-line summary
    assert expect_type in logged


def article(i: str) -> Evidence:
    return Evidence(id=i, symbol="AAPL", title=f"Apple buyback story {i}", summary="Apple buyback announced",
                    source_name=f"outlet-{i}", source_type="general_news", retrieved_at=NOW)


def good(evidence_id):
    return SimpleNamespace(
        engine="jev", model="m", question_set_version="v", request_id="r", error=None, relevant=0.9,
        direction="positive", direction_confidence=0.8, content_type="news_report", content_type_confidence=0.9,
        event_type="other", event_type_confidence=0.5, upcoming_event=0.1, sensational=0.1, usable_content=0.9,
        materiality=1.0, materiality_confidence=0.7, evidence_id=evidence_id)


class LeakyError(RuntimeError):
    pass


class Tool:
    def __init__(self, judgments=None, same=None):
        self.judgments, self.same = judgments, same

    def judge_evidence_items(self, items, companies):
        if self.judgments is None:
            raise LeakyError(LEAKY)
        return self.judgments

    def same_story(self, items, pairs):
        if self.same is None:
            raise LeakyError(LEAKY)
        return self.same


class LeakyMapping(Mapping):
    """A result whose fields raise with secret text, except the ones allowed."""

    def __init__(self, allowed):
        self.allowed = allowed

    def __getitem__(self, name):
        if name in self.allowed:
            return self.allowed[name]
        raise LeakyError(LEAKY)

    def get(self, name, default=None):
        return self[name]

    def __iter__(self):
        return iter(self.allowed)

    def __len__(self):
        return len(self.allowed)


def test_describe_exception_is_one_sanitized_line():
    from scraper_analysis.sources.base import describe_exception

    text = describe_exception(LeakyError(LEAKY + "\nsecond line"))
    assert text.startswith("LeakyError: ")
    assert "\n" not in text
    for secret in SECRETS:
        assert secret not in text


def test_jev_call_failure_logs_no_secret(caplog, capfd):
    items = [article("a")]
    jev_judge.judge_evidence(items, tool=Tool())
    assert items[0].details["jev"]["status"] == jev_judge.STATUS_FAILED
    assert_clean(caplog, capfd, "LeakyError")


def test_malformed_jev_result_logs_no_secret(caplog, capfd):
    items = [article("a")]
    jev_judge.judge_evidence(items, tool=Tool(judgments=[LeakyMapping({"evidence_id": "a"})]))
    assert items[0].details["jev"]["status"] == jev_judge.STATUS_MALFORMED
    assert_clean(caplog, capfd, "LeakyError")


def test_unreadable_evidence_id_logs_no_secret(caplog, capfd):
    items = [article("a")]
    jev_judge.judge_evidence(items, tool=Tool(judgments=[LeakyMapping({})]))
    assert items[0].details["jev"]["status"] == jev_judge.STATUS_MISSING
    assert_clean(caplog, capfd, "LeakyError")


def test_sentiment_fill_failure_logs_no_secret(monkeypatch, caplog, capfd):
    def boom(_evidence):
        raise LeakyError(LEAKY)

    monkeypatch.setattr(jev_judge, "_fill_sentiment", boom)
    items = [article("a")]
    jev_judge.judge_evidence(items, tool=Tool(judgments=[good("a")], same=SimpleNamespace(engine="jev", pairs=[])))
    assert items[0].details["jev"]["engine"] == "jev"
    assert_clean(caplog, capfd, "LeakyError")


def test_same_story_call_failure_logs_no_secret(caplog, capfd):
    items = [article("a"), article("b")]
    jev_judge.judge_evidence(items, tool=Tool(judgments=[good("a"), good("b")]))
    assert all(e.details["jev"]["engine"] == "jev" for e in items)
    assert_clean(caplog, capfd, "LeakyError")


def test_unreadable_same_story_pair_logs_no_secret(caplog, capfd):
    items = [article("a"), article("b")]
    same = SimpleNamespace(engine="jev", pairs=[LeakyMapping({})])
    jev_judge.judge_evidence(items, tool=Tool(judgments=[good("a"), good("b")], same=same))
    assert_clean(caplog, capfd, "LeakyError")


def test_same_story_marking_failure_logs_no_secret(monkeypatch, caplog, capfd):
    def boom(_judged, _tool):
        raise LeakyError(LEAKY)

    monkeypatch.setattr(jev_judge, "_mark_same_story", boom)
    items = [article("a")]
    jev_judge.judge_evidence(items, tool=Tool(judgments=[good("a")]))
    assert_clean(caplog, capfd, "LeakyError")


def test_grade_failure_logs_no_secret(monkeypatch, caplog, capfd):
    def boom(*_a, **_k):
        raise LeakyError(LEAKY)

    monkeypatch.setattr(grade, "grade_record", boom)
    items = [article("a")]
    grade.grade_evidence(items)
    assert "grade" not in items[0].details
    assert_clean(caplog, capfd, "LeakyError")


def test_jev_briefing_review_failure_logs_no_secret(caplog, capfd):
    class Boom:
        def check_explanation(self, text, items):
            raise LeakyError(LEAKY)

    assert jev_guard.review_briefing(briefing(point("x.", "e1")), EVIDENCE, tool=Boom()) is None
    assert_clean(caplog, capfd, "LeakyError")


def test_tagging_failure_logs_no_secret(monkeypatch, caplog, capfd):
    def boom():
        raise LeakyError(LEAKY)

    monkeypatch.setattr(tagging_agent, "_get_agent", boom)
    ev = article("a")
    assert tagging_agent.tag_evidence(ev) is ev
    assert_clean(caplog, capfd, "LeakyError")


def test_embedding_failure_logs_no_secret(monkeypatch, caplog, capfd):
    def boom(*_a, **_k):
        raise httpx.ConnectError(LEAKY)

    monkeypatch.setattr(embeddings.httpx, "post", boom)
    assert embeddings.get_embedding("text") is None
    assert_clean(caplog, capfd, "ConnectError")


@pytest.fixture
def store(monkeypatch):
    s = store_module.InMemoryEvidenceStore()
    s.save_evidence(EVIDENCE)
    monkeypatch.setattr(store_module, "_store", s)
    yield s
    monkeypatch.setattr(store_module, "_store", None)


def test_briefing_agent_setup_failure_logs_no_secret(store, caplog, capfd):
    def factory(*_a, **_k):
        raise LeakyError(LEAKY)

    with pytest.raises(sa.BriefingUnavailableError) as info:
        sa.generate_briefing("AAPL", store=store, agent_factory=factory)
    for secret in SECRETS:
        assert secret not in str(info.value)
    assert_clean(caplog, capfd, "LeakyError")


def test_briefing_generation_failure_logs_no_secret(store, caplog, capfd):
    def agent(_prompt):
        raise LeakyError(LEAKY)

    with pytest.raises(sa.BriefingUnavailableError) as info:
        sa.generate_briefing("AAPL", store=store, agent_factory=lambda *_a, **_k: agent)
    for secret in SECRETS:
        assert secret not in str(info.value)
    assert_clean(caplog, capfd, "LeakyError")


def test_briefing_invalid_output_logs_no_secret(store, caplog, capfd):
    with pytest.raises(sa.BriefingUnavailableError) as info:
        sa.generate_briefing("AAPL", store=store, agent_factory=lambda *_a, **_k: (lambda _p: f"not json {LEAKY}"))
    for secret in SECRETS:
        assert secret not in str(info.value)
    # JSONDecodeError (a ValueError) text echoes the model output
    assert_clean(caplog, capfd, "briefing output invalid")
