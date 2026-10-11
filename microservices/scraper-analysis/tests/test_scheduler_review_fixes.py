"""Regression tests for the PR #16 review findings on the background scheduler:
1. no persistence after stop() returns (drain + cancellation flag),
2. a single scheduler owner per process (no overlap with a second/successor instance),
3. non-finite / non-positive interval config is rejected,
4. duplicate normalized symbols are de-duplicated.

Deterministic: threads are coordinated with threading.Event, never timed sleeps
on the critical path (the only waits are short bounded timeouts)."""

import asyncio
import math
import threading
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from scraper_analysis import scheduler as sched
from scraper_analysis.config import Settings
from scraper_analysis.pipeline import ingest
from scraper_analysis.pipeline.ingest import IngestResult, SourceReport
from scraper_analysis.storage import store as store_module

MARKET_OPEN = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)


def result():
    return IngestResult([None] * 2, [None], [SourceReport("sec_edgar", "live", 3)])


async def instant_startup_then_park(seconds):
    """Startup delay and stagger are instant; the inter-run wait parks so only one run happens."""
    if seconds == sched.STARTUP_DELAY_SECONDS or seconds < 60:
        await asyncio.sleep(0)
    else:
        await asyncio.sleep(3600)


class BlockingIngest:
    """Simulates an ingest that is mid-fetch when shutdown starts: it blocks until
    released, then (optionally) honors the stop flag before 'persisting'."""

    def __init__(self, honor_stop=True):
        self.entered = threading.Event()
        self.done = threading.Event()
        self.release = threading.Event()
        self.writes: list[str] = []
        self.honor_stop = honor_stop
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def __call__(self, symbol, allow_live, tag, fallback, should_stop=None):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.entered.set()
            assert self.release.wait(5), "test never released the ingest"
            if self.honor_stop and should_stop is not None and should_stop():
                raise ingest.IngestCancelled("stopped before persisting")
            self.writes.append(symbol)  # the "persist" step
            return result()
        finally:
            with self._lock:
                self.active -= 1
            self.done.set()


def make(ingest_fn, symbols=("AAPL",), **kw):
    return sched.Scheduler(list(symbols), ingest_fn=ingest_fn, now_fn=lambda: MARKET_OPEN,
                           sleep_fn=instant_startup_then_park, stagger_seconds=0, **kw)


async def wait_thread_event(event: threading.Event):
    assert await asyncio.to_thread(event.wait, 5)


@pytest.fixture(autouse=True)
def _reset_owner():
    reset = getattr(sched, "_reset_for_tests", lambda: None)
    reset()
    yield
    reset()


# --- Finding 1: shutdown boundary ---------------------------------------------

async def test_no_write_after_stop_returns_when_ingest_honors_stop_flag():
    fake = BlockingIngest(honor_stop=True)
    s = make(fake)
    s.start()
    await wait_thread_event(fake.entered)
    stopping = asyncio.create_task(s.stop())
    await asyncio.sleep(0.05)  # stop() is now draining the in-flight ingest
    fake.release.set()
    await stopping
    snapshot = list(fake.writes)
    await asyncio.sleep(0.1)  # give any orphaned thread a chance to write
    assert fake.writes == snapshot == []  # cancelled before persisting
    assert s.runs_completed == 0
    st = s.statuses["AAPL"]
    assert st.ok is False and "shutdown" in st.error
    assert s.status()["running"] is False


async def test_stop_waits_for_an_in_flight_write_and_records_it():
    # An ingest already past its last stop check (e.g. mid-save) must finish
    # *before* stop() returns, and its outcome must show up in the status.
    fake = BlockingIngest(honor_stop=False)
    s = make(fake)
    s.start()
    await wait_thread_event(fake.entered)
    stopping = asyncio.create_task(s.stop())
    await asyncio.sleep(0.05)
    assert not stopping.done()  # still draining
    fake.release.set()
    await stopping
    assert fake.writes == ["AAPL"]  # happened before stop() returned
    st = s.statuses["AAPL"]
    assert st.ok is True and st.new_evidence == 2 and st.new_signals == 1
    assert s.runs_completed == 1  # the run's only symbol did complete


async def test_drain_timeout_bounds_stop_and_flag_still_blocks_late_persist():
    fake = BlockingIngest(honor_stop=True)
    s = make(fake, drain_timeout_seconds=0.1)
    s.start()
    await wait_thread_event(fake.entered)
    await asyncio.wait_for(s.stop(), timeout=2)  # bounded even though ingest is stuck
    assert "shutdown" in s.statuses["AAPL"].error
    fake.release.set()
    await asyncio.sleep(0.1)
    assert fake.writes == []  # the late thread saw the stop flag and did not persist


async def test_pipeline_checks_stop_flag_before_persisting(monkeypatch):
    memory = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", memory)
    with pytest.raises(ingest.IngestCancelled):
        ingest.ingest_symbol("AAPL", allow_live=False, tag=False, fallback=True, should_stop=lambda: True)
    assert memory.query_evidence("AAPL") == []
    monkeypatch.setattr(store_module, "_store", None)


# --- Finding 2: single owner / no overlap ---------------------------------------

async def test_second_scheduler_cannot_start_while_one_owns_the_process():
    a = make(BlockingIngest())
    b = make(BlockingIngest())
    assert a.start() is True
    try:
        assert b.start() is False
        assert b.status()["running"] is False and "already" in b.status()["start_error"]
    finally:
        a._ingest.release.set()
        await a.stop()
    assert b.start() is True  # ownership is released by stop()
    b._ingest.release.set()
    await b.stop()


async def test_successor_never_overlaps_a_predecessor_still_in_flight():
    fake = BlockingIngest(honor_stop=False)  # stuck mid-persist past the drain timeout
    old = make(fake, drain_timeout_seconds=0.05)
    old.start()
    await wait_thread_event(fake.entered)
    await old.stop()  # returns after the bounded drain; old thread still running

    successor = make(fake)
    await successor.run_once()
    assert fake.max_active == 1  # successor did not ingest concurrently
    assert successor.statuses["AAPL"].ok is False
    assert "in flight" in successor.statuses["AAPL"].error
    fake.release.set()
    await wait_thread_event(fake.done)  # old thread has finished
    await successor.run_once()  # free again: runs normally
    assert successor.statuses["AAPL"].ok is True


async def test_two_schedulers_in_one_process_never_ingest_concurrently():
    # Even run_once() called directly on two instances (bypassing start()) must
    # not overlap: the guard is process-wide, not per instance.
    fake = BlockingIngest(honor_stop=False)
    a, b = make(fake), make(fake)
    ta = asyncio.create_task(a.run_once())
    await wait_thread_event(fake.entered)
    tb = asyncio.create_task(b.run_once())
    await asyncio.sleep(0.1)
    fake.release.set()
    await ta
    await tb
    assert fake.max_active == 1
    assert fake.writes == ["AAPL"]


# --- Finding 3: interval validation ----------------------------------------------

BAD_NUMBERS = [math.nan, math.inf, -math.inf, 0, -5]


@pytest.mark.parametrize("value", BAD_NUMBERS)
def test_scheduler_rejects_non_finite_or_non_positive_interval(value):
    with pytest.raises(ValueError):
        make(BlockingIngest(), interval_minutes=value)


@pytest.mark.parametrize("value", BAD_NUMBERS)
def test_scheduler_rejects_non_finite_or_non_positive_offhours_factor(value):
    with pytest.raises(ValueError):
        make(BlockingIngest(), offhours_factor=value)


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "0", "-1"])
def test_settings_reject_bad_interval_env(monkeypatch, raw):
    monkeypatch.setenv("SCHEDULER_INTERVAL_MINUTES", raw)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("raw", ["nan", "inf", "0", "-1"])
def test_settings_reject_bad_offhours_factor_env(monkeypatch, raw):
    monkeypatch.setenv("SCHEDULER_OFFHOURS_FACTOR", raw)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_small_positive_values_are_still_clamped_to_floors():
    s = make(BlockingIngest(), interval_minutes=0.5, offhours_factor=0.5)
    assert s.interval_minutes == sched.MIN_INTERVAL_MINUTES and s.offhours_factor == 1.0


# --- Finding 4: duplicate symbols -------------------------------------------------

async def test_duplicate_normalized_symbols_run_once_each():
    calls = []

    def record(symbol, allow_live, tag, fallback, should_stop=None):
        calls.append(symbol)
        return result()

    s = make(record, symbols=("aapl", " AAPL ", "Aapl", "bad!", "msft", "MSFT", "bad!"))
    assert s.symbols == ["AAPL", "MSFT"]
    assert s.skipped == ["bad!"]
    await s.run_once()
    assert calls == ["AAPL", "MSFT"]
