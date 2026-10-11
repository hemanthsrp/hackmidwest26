import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from scraper_analysis import api as api_module
from scraper_analysis import scheduler as sched
from scraper_analysis.pipeline.ingest import IngestResult, SourceReport

# 2026-10-12 is a Monday. EDT is UTC-4.
MARKET_OPEN = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)  # Mon 10:00 NY
LATE_NIGHT = datetime(2026, 10, 12, 3, 0, tzinfo=timezone.utc)  # Sun 23:00 NY
SATURDAY = datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc)


def result(live=True, ev=2, sig=1):
    status = "live" if live else "unavailable"
    return IngestResult([None] * ev, [None] * sig, [SourceReport("sec_edgar", status, 3)])


def make(symbols=("AAPL",), ingest=None, now=MARKET_OPEN, **kw):
    calls, sleeps = [], []

    def default_ingest(symbol, allow_live, tag, fallback):
        calls.append((symbol, allow_live, tag, fallback))
        return result()

    async def fake_sleep(s):
        sleeps.append(s)

    s = sched.Scheduler(list(symbols), ingest_fn=ingest or default_ingest, now_fn=lambda: now,
                        sleep_fn=fake_sleep, **kw)
    return s, calls, sleeps


def test_invalid_symbols_are_skipped_and_interval_has_a_floor():
    s, _, _ = make(("AAPL", "bad!", "msft"), interval_minutes=1)
    assert s.symbols == ["AAPL", "MSFT"] and s.skipped == ["bad!"]
    assert s.interval_minutes == sched.MIN_INTERVAL_MINUTES


@pytest.mark.parametrize("now,expected", [(MARKET_OPEN, True), (LATE_NIGHT, False), (SATURDAY, False)])
def test_market_hours(now, expected):
    assert sched.is_market_hours(now) is expected


def test_offhours_interval_is_slower():
    on, _, _ = make(now=MARKET_OPEN, interval_minutes=30, offhours_factor=4)
    off, _, _ = make(now=LATE_NIGHT, interval_minutes=30, offhours_factor=4)
    assert on.current_interval_seconds() == 30 * 60
    assert off.current_interval_seconds() == 30 * 60 * 4


async def test_runs_are_always_strict_live_only():
    s, calls, _ = make(("AAPL",), tag=False)
    await s.run_once()
    assert calls == [("AAPL", True, False, False)]  # live=True, fallback=False
    st = s.statuses["AAPL"]
    assert st.ok is True and st.new_evidence == 2 and st.new_signals == 1
    assert st.sources == [{"name": "sec_edgar", "status": "live", "count": 3}]


async def test_one_symbol_failing_does_not_stop_the_others():
    def flaky(symbol, *a):
        if symbol == "AAPL":
            raise RuntimeError("boom")
        return result()

    s, _, _ = make(("AAPL", "MSFT"), ingest=flaky)
    await s.run_once()
    assert s.statuses["AAPL"].ok is False and s.statuses["AAPL"].consecutive_failures == 1
    assert s.statuses["MSFT"].ok is True
    assert s.runs_completed == 1


async def test_errors_are_sanitized_before_being_stored():
    def leaky(symbol, *a):
        raise RuntimeError("401 for url 'https://api.marketaux.com/v1/news?api_token=SECRETVALUE123'")

    s, _, _ = make(ingest=leaky)
    await s.run_once()
    err = s.statuses["AAPL"].error
    assert "SECRETVALUE123" not in err and "redacted" in err


async def test_no_live_source_counts_as_a_failure_and_recovers():
    outcomes = iter([result(live=False), result(live=False), result(live=True)])
    s, _, _ = make(ingest=lambda *a: next(outcomes))
    await s.run_once()
    await s.run_once()
    assert s.statuses["AAPL"].consecutive_failures == 2 and s.statuses["AAPL"].ok is False
    await s.run_once()
    st = s.statuses["AAPL"]
    assert st.ok is True and st.consecutive_failures == 0 and st.error is None


async def test_runs_never_overlap():
    count = []
    s, _, _ = make()

    def slow_ingest(*a):
        count.append(1)
        return result()

    s._ingest = slow_ingest
    await s._lock.acquire()  # simulate a run in progress
    await s.run_once()  # must return immediately without running
    assert count == []
    s._lock.release()
    await s.run_once()
    assert count == [1]


async def test_symbols_are_staggered():
    s, _, sleeps = make(("AAPL", "MSFT", "NVDA"), stagger_seconds=2.0)
    await s.run_once()
    assert sleeps == [2.0, 2.0]  # between symbols, not before the first


async def test_run_forever_schedules_next_run_with_jitter_and_can_be_cancelled():
    s, calls, sleeps = make(("AAPL",), interval_minutes=30)
    original = s._sleep

    async def stop_after_first_wait(seconds):
        await original(seconds)
        if len(sleeps) >= 2:  # startup delay, then the inter-run wait
            raise asyncio.CancelledError

    s._sleep = stop_after_first_wait
    with pytest.raises(asyncio.CancelledError):
        await s.run_forever()
    assert sleeps[0] == sched.STARTUP_DELAY_SECONDS
    assert 30 * 60 <= sleeps[1] <= 30 * 60 + 60  # interval plus bounded jitter
    assert len(calls) == 1 and s.next_run_at is not None


def test_status_describes_strict_mode():
    s, _, _ = make()
    st = s.status()
    assert st["enabled"] is True and "never substituted" in st["mode"]
    assert st["symbols"]["AAPL"]["last_run_at"] is None


# --- API wiring --------------------------------------------------------------

def test_scheduler_is_off_by_default():
    with TestClient(api_module.app) as client:
        assert client.get("/scheduler/status").json() == {"enabled": False}


def test_enabled_scheduler_starts_with_app_and_stops_cleanly(monkeypatch):
    settings = SimpleNamespace(enable_scheduler=True, scheduler_symbols="AAPL, bad!, MSFT",
                               scheduler_interval_minutes=30, scheduler_offhours_factor=4, scheduler_tag=False)
    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    with TestClient(api_module.app) as client:
        body = client.get("/scheduler/status").json()
        assert body["enabled"] is True and body["running"] is True
        assert set(body["symbols"]) == {"AAPL", "MSFT"} and body["skipped_invalid_symbols"] == ["bad!"]
        scheduler = api_module.app.state.scheduler
    assert scheduler._task is None  # cancelled on shutdown
