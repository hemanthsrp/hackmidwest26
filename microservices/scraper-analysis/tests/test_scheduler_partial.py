"""PR #16 review (hbot): /scheduler/status must not drop a source's
partial-coverage note or report a degraded run as a clean OK.

Convention (also used by the House adapter): a source with status "live" and
a non-empty ``error`` is live but only partially covered.
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from scraper_analysis import api as api_module
from scraper_analysis import scheduler as sched
from scraper_analysis.pipeline.ingest import IngestResult, SourceReport

MARKET_OPEN = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)


def make(reports, symbols=("AAPL",)):
    def ingest(symbol, allow_live, tag, fallback, should_stop=None):
        return IngestResult([None] * 2, [None], list(reports))

    async def fake_sleep(s):
        pass

    return sched.Scheduler(list(symbols), ingest_fn=ingest, now_fn=lambda: MARKET_OPEN, sleep_fn=fake_sleep)


PARTIAL = SourceReport("house_clerk", "live", 27, "partial: 3 of 30 filings skipped")


async def test_live_source_with_partial_note_is_kept_and_not_a_clean_ok():
    s = make([SourceReport("sec_edgar", "live", 3), PARTIAL])
    await s.run_once()
    st = s.status()["symbols"]["AAPL"]
    house = next(x for x in st["sources"] if x["name"] == "house_clerk")
    assert house["status"] == "live" and house["error"] == "partial: 3 of 30 filings skipped"
    assert st["ok"] is False and st["partial"] is True
    assert any("partial: 3 of 30 filings skipped" in n and "house_clerk" in n for n in st["notes"])
    # It is degraded coverage, not a failed run.
    assert st["consecutive_failures"] == 0
    assert st["new_evidence"] == 2 and st["new_signals"] == 1


async def test_unavailable_source_alongside_live_is_partial_with_its_error():
    s = make([SourceReport("sec_edgar", "live", 3),
              SourceReport("senate", "unavailable", 0, "ConnectError: timed out")])
    await s.run_once()
    st = s.status()["symbols"]["AAPL"]
    senate = next(x for x in st["sources"] if x["name"] == "senate")
    assert senate == {"name": "senate", "status": "unavailable", "count": 0, "error": "ConnectError: timed out"}
    assert st["ok"] is False and st["partial"] is True
    assert any("senate" in n and "timed out" in n for n in st["notes"])


async def test_all_sources_clean_live_is_still_ok():
    s = make([SourceReport("sec_edgar", "live", 3), SourceReport("yahoo", "live", 1)])
    await s.run_once()
    st = s.status()["symbols"]["AAPL"]
    assert st["ok"] is True and st["partial"] is False and st["notes"] == [] and st["error"] is None
    assert all(x["error"] is None for x in st["sources"])


async def test_source_notes_are_sanitized():
    leaky = SourceReport("news", "live", 1, "partial: 401 for url 'https://x.test/v1?api_token=SECRETVALUE123'")
    s = make([leaky])
    await s.run_once()
    st = s.status()["symbols"]["AAPL"]
    assert "SECRETVALUE123" not in str(st)
    assert st["partial"] is True and st["ok"] is False


async def test_partial_flag_clears_on_next_clean_run():
    reports = [SourceReport("sec_edgar", "live", 3), PARTIAL]
    s = make(reports)
    await s.run_once()
    assert s.statuses["AAPL"].partial is True
    reports[1] = SourceReport("house_clerk", "live", 30)
    await s.run_once()
    st = s.status()["symbols"]["AAPL"]
    assert st["ok"] is True and st["partial"] is False and st["notes"] == []


async def test_scheduler_status_endpoint_exposes_partial_note():
    s = make([SourceReport("sec_edgar", "live", 3), PARTIAL])
    await s.run_once()
    api_module.app.state.scheduler = s
    try:
        body = TestClient(api_module.app).get("/scheduler/status").json()
    finally:
        api_module.app.state.scheduler = None
    st = body["symbols"]["AAPL"]
    assert st["ok"] is False and st["partial"] is True
    assert "partial: 3 of 30 filings skipped" in str(st["notes"])
    assert {"name": "house_clerk", "status": "live", "count": 27,
            "error": "partial: 3 of 30 filings skipped"} in st["sources"]
