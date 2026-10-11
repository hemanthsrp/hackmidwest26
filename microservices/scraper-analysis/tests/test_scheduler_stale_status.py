"""PR #16 review (hbot): a failed or interrupted attempt must never show the
previous run's ``sources`` / ``new_evidence`` / ``new_signals`` / ``partial``
/ ``notes`` in /scheduler/status as if they were current. Top-level per-symbol
fields describe the latest attempt only; the last successful run is kept in an
explicit ``last_success`` sub-object with its own timestamp.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from scraper_analysis import api as api_module
from scraper_analysis import scheduler as sched
from scraper_analysis.pipeline.ingest import IngestCancelled, IngestResult, SourceReport

T0 = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _reset_owner():
    sched._reset_for_tests()
    yield
    sched._reset_for_tests()


def make(outcomes):
    """Scheduler whose ingest returns/raises the next item of ``outcomes``."""
    clock = {"now": T0}
    queue = list(outcomes)

    def ingest(symbol, allow_live, tag, fallback, should_stop=None):
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def fake_sleep(s):
        pass

    s = sched.Scheduler(["AAPL"], ingest_fn=ingest, now_fn=lambda: clock["now"], sleep_fn=fake_sleep)
    return s, clock


CLEAN = IngestResult([None], [None], [SourceReport("sec_edgar", "live", 1)])
PARTIAL = IngestResult([None, None], [None], [SourceReport("sec_edgar", "live", 3),
                                             SourceReport("senate", "unavailable", 0, "ConnectError: timed out")])


def endpoint_status(s):
    api_module.app.state.scheduler = s
    try:
        return TestClient(api_module.app).get("/scheduler/status").json()["symbols"]["AAPL"]
    finally:
        api_module.app.state.scheduler = None


def assert_no_stale_run_fields(st):
    assert st["sources"] == []
    assert st["new_evidence"] == 0 and st["new_signals"] == 0
    assert st["partial"] is False and st["notes"] == []
    assert "sec_edgar" not in str({k: v for k, v in st.items() if k != "last_success"})


async def run_twice(s, clock):
    await s.run_once()
    clock["now"] = T0 + timedelta(minutes=30)
    await s.run_once()


async def test_runtime_error_after_clean_run_clears_previous_run_fields():
    s, clock = make([CLEAN, RuntimeError("upstream down")])
    await run_twice(s, clock)
    st = endpoint_status(s)
    assert st["ok"] is False and "upstream down" in st["error"]
    assert st["last_run_at"] == (T0 + timedelta(minutes=30)).isoformat()
    assert_no_stale_run_fields(st)
    # History kept explicitly, labelled with its own timestamp.
    ls = st["last_success"]
    assert ls["at"] == T0.isoformat()
    assert ls["new_evidence"] == 1 and ls["new_signals"] == 1
    assert ls["sources"][0]["name"] == "sec_edgar"


async def test_runtime_error_after_partial_run_clears_partial_and_notes():
    s, clock = make([PARTIAL, RuntimeError("upstream down")])
    await run_twice(s, clock)
    st = endpoint_status(s)
    assert st["ok"] is False
    assert_no_stale_run_fields(st)
    assert st["last_success"]["partial"] is True


async def test_ingest_cancelled_after_clean_run_shows_only_this_attempt():
    s, clock = make([CLEAN, IngestCancelled("stopping", evidence_saved=0, signals_saved=0)])
    await run_twice(s, clock)
    st = endpoint_status(s)
    assert st["ok"] is False and "shutdown" in st["error"]
    assert_no_stale_run_fields(st)
    assert st["last_success"]["at"] == T0.isoformat()


async def test_ingest_cancelled_reports_its_own_saved_counts_not_previous_sources():
    s, clock = make([CLEAN, IngestCancelled("stopping", evidence_saved=2, signals_saved=0)])
    await run_twice(s, clock)
    st = endpoint_status(s)
    assert st["sources"] == [] and st["notes"] == [] and st["partial"] is False
    assert st["new_evidence"] == 2 and st["new_signals"] == 0


async def test_no_live_source_after_clean_run_does_not_update_last_success():
    s, clock = make([CLEAN, IngestResult([], [], [SourceReport("sec_edgar", "unavailable", 0, "down")])])
    await run_twice(s, clock)
    st = endpoint_status(s)
    assert st["ok"] is False and st["error"] == "no source was live"
    assert st["sources"][0]["status"] == "unavailable"  # this attempt's own rows
    assert st["last_success"]["at"] == T0.isoformat()


async def test_last_success_is_none_before_any_success():
    s, clock = make([RuntimeError("upstream down")])
    await s.run_once()
    st = endpoint_status(s)
    assert st["last_success"] is None
    assert_no_stale_run_fields(st)
