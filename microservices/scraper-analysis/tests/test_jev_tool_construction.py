"""Reviewer finding on PR #19 (hbot, 3e5f60f): judge_evidence() and review_briefing()
caught only ImportError while building the Jev tool. A constructor RuntimeError
carrying the API key and a tokened URL propagated raw out of both public functions,
and ingested records were left with no Jev failure status.

Now any failure building the tool is caught, logged as one sanitized line, and:
judge_evidence marks every target ``failed`` (fixed text, no exception text);
review_briefing falls back to None (briefing unreviewed). ImportError (JEV_ENABLED
set but jev-tool not installed) is treated the same way: records are marked
``failed`` so "Jev was asked for but could not run" never looks like "never judged".

Offline: a fake ``jev_tool`` module whose constructor raises; no network, in-memory store.
"""

import logging
import sys
import types
from datetime import UTC, datetime

import pytest

from scraper_analysis.agents import jev_guard
from scraper_analysis.config import get_settings
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.pipeline import ingest, jev_judge
from scraper_analysis.storage import store as store_module

from .test_jev_guard import EVIDENCE, briefing, point

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
TS_KEY = "ts-DUMMY-ctor-key-4b1e"
URL_TOKEN = "abc"
CTOR_MESSAGE = f"boom api_token={TS_KEY} https://x/?token={URL_TOKEN}"
SECRETS = (TS_KEY, f"token={URL_TOKEN}", f"?token={URL_TOKEN}")  # the host is not secret; the query is
FAILED = {"engine": "unavailable", "status": "failed", "error": "jev tool unavailable"}


@pytest.fixture(autouse=True)
def configured(monkeypatch, caplog):
    monkeypatch.setattr(store_module, "_store", store_module.InMemoryEvidenceStore())
    settings = get_settings()
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", TS_KEY)
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(jev_judge, "_tool", None)
    caplog.set_level(logging.DEBUG)
    yield
    monkeypatch.setattr(store_module, "_store", None)


@pytest.fixture
def exploding_ctor(monkeypatch):
    """A jev_tool module whose JevTool constructor raises with secret text."""
    module = types.ModuleType("jev_tool")

    class JevTool:
        def __init__(self, *args, **kwargs):
            raise RuntimeError(CTOR_MESSAGE)

    module.JevTool = JevTool
    monkeypatch.setitem(sys.modules, "jev_tool", module)


@pytest.fixture
def not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "jev_tool", None)  # `import jev_tool` -> ImportError


def assert_clean(caplog, capfd, expect: str):
    out, err = capfd.readouterr()
    logged = caplog.text
    for secret in SECRETS:
        assert secret not in logged, f"{secret!r} leaked into logs:\n{logged}"
        assert secret not in out and secret not in err, f"{secret!r} leaked to stdout/stderr"
    assert "Traceback" not in logged
    assert all(r.exc_info is None and r.exc_text is None for r in caplog.records)
    assert expect in logged


def article(i: str) -> Evidence:
    return Evidence(id=i, symbol="AAPL", title=f"Apple story {i}", summary="s", source_name=f"outlet-{i}",
                    source_type="general_news", retrieved_at=NOW)


def test_judge_evidence_constructor_failure_marks_failed_and_does_not_raise(exploding_ctor, caplog, capfd):
    items = [article("a"), article("b")]
    assert jev_judge.judge_evidence(items) is items
    for e in items:
        assert e.details["jev"] == FAILED
    assert_clean(caplog, capfd, "RuntimeError")


def test_judge_evidence_constructor_failure_stores_nothing_secret(exploding_ctor):
    items = [article("a")]
    jev_judge.judge_evidence(items)
    assert TS_KEY not in repr(items[0].details)
    assert "token" not in repr(items[0].details)


def test_judge_evidence_not_installed_marks_failed(not_installed, caplog, capfd):
    items = [article("a")]
    assert jev_judge.judge_evidence(items) is items
    assert items[0].details["jev"] == FAILED
    assert_clean(caplog, capfd, "not installed")


def test_judge_evidence_skips_non_judged_types_on_constructor_failure(exploding_ctor):
    filing = Evidence(id="f", symbol="AAPL", title="10-K", source_name="sec", source_type="official_filing",
                      retrieved_at=NOW)
    news = article("a")
    jev_judge.judge_evidence([filing, news])
    assert "jev" not in filing.details
    assert news.details["jev"] == FAILED


def test_review_briefing_constructor_failure_falls_back(exploding_ctor, caplog, capfd):
    assert jev_guard.review_briefing(briefing(point("Apple raised its forecast.", "e1")), EVIDENCE) is None
    assert_clean(caplog, capfd, "RuntimeError")


def test_review_briefing_not_installed_falls_back(not_installed, caplog, capfd):
    assert jev_guard.review_briefing(briefing(point("Apple raised its forecast.", "e1")), EVIDENCE) is None
    assert_clean(caplog, capfd, "not installed")


def test_ingest_end_to_end_constructor_failure_marks_records_failed(exploding_ctor, caplog, capfd):
    stored = ingest.run_ingestion("AAPL", allow_live=False, tag=False)
    news = [e for e in stored if e.source_type in jev_judge.JUDGED_SOURCE_TYPES]
    assert news
    assert all(e.details["jev"] == FAILED for e in news)
    assert len(store_module.get_store().query_evidence("AAPL")) == len(stored)
    assert_clean(caplog, capfd, "RuntimeError")
