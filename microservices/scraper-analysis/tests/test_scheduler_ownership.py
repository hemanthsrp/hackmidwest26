"""Regression tests for the second PR #16 review round (hbot on 476ead3):

1. "Restarting the scheduler after a stop timeout can let the prior worker
   write after stop() returned": start() used to clear the instance's shared
   stop flag, which the still-running worker thread of the previous run read
   as "keep going" and so persisted after stop() had returned.
2. "The stack also needs a single-owner deployment constraint": ownership must
   be enforced across processes (Postgres advisory lock when DATABASE_URL is
   set), not only documented.

Deterministic: worker threads are coordinated with threading.Event."""

import asyncio
import os
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from scraper_analysis import api as api_module
from scraper_analysis import scheduler as sched
from scraper_analysis.pipeline import ingest
from scraper_analysis.pipeline.ingest import IngestResult, SourceReport

MARKET_OPEN = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)


def result():
    return IngestResult([None] * 2, [None], [SourceReport("sec_edgar", "live", 3)])


async def instant_startup_then_park(seconds):
    if seconds == sched.STARTUP_DELAY_SECONDS or seconds < 60:
        await asyncio.sleep(0)
    else:
        await asyncio.sleep(3600)


class BlockingIngest:
    """First call blocks until released, then honors should_stop before its
    'persist'. Later calls (a restarted run) return immediately."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.done = threading.Event()
        self.writes: list[str] = []
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, symbol, allow_live, tag, fallback, should_stop=None):
        with self._lock:
            self.calls += 1
            first = self.calls == 1
        try:
            if first:
                self.entered.set()
                assert self.release.wait(5), "test never released the ingest"
            if should_stop is not None and should_stop():
                raise ingest.IngestCancelled("stopped before persisting")
            self.writes.append(symbol)
            return result()
        finally:
            if first:
                self.done.set()


class FakeOwnerLock:
    def __init__(self, acquire_result=True, error=None):
        self.acquire_result = acquire_result
        self.error = error
        self.held = False
        self.acquires = 0
        self.releases = 0

    def acquire(self) -> bool:
        self.acquires += 1
        if self.error is not None:
            raise self.error
        self.held = bool(self.acquire_result)
        return self.held

    def release(self) -> None:
        self.releases += 1
        self.held = False


def make(ingest_fn, **kw):
    return sched.Scheduler(["AAPL"], ingest_fn=ingest_fn, now_fn=lambda: MARKET_OPEN,
                           sleep_fn=instant_startup_then_park, stagger_seconds=0, **kw)


async def wait_thread_event(event: threading.Event):
    assert await asyncio.to_thread(event.wait, 5)


@pytest.fixture(autouse=True)
def _reset_owner():
    sched._reset_for_tests()
    yield
    sched._reset_for_tests()


# --- Finding 1: restart after a drain timeout -----------------------------------

async def test_restart_after_drain_timeout_never_lets_prior_worker_write():
    fake = BlockingIngest()
    s = make(fake, drain_timeout_seconds=0.05)
    assert s.start() is True
    await wait_thread_event(fake.entered)
    await s.stop()  # drain times out: the old worker thread is still blocked
    s.start()  # restart (refused or not, it must not revive the old run)
    fake.release.set()
    await wait_thread_event(fake.done)
    await asyncio.sleep(0.05)
    assert fake.writes == []  # the old run's worker saw its own, still-set token
    await s.stop()


async def test_restart_is_refused_while_the_previous_worker_is_draining():
    fake = BlockingIngest()
    s = make(fake, drain_timeout_seconds=0.05)
    s.start()
    await wait_thread_event(fake.entered)
    await s.stop()
    assert s.start() is False
    assert "draining" in s.status()["start_error"]
    assert s.status()["running"] is False
    fake.release.set()
    await wait_thread_event(fake.done)
    await asyncio.sleep(0.05)
    assert s.start() is True  # old worker exited: restart is allowed again
    await s.stop()
    assert fake.writes == []


async def test_successor_instance_is_refused_until_predecessor_worker_exits():
    fake = BlockingIngest()
    old = make(fake, drain_timeout_seconds=0.05)
    old.start()
    await wait_thread_event(fake.entered)
    await old.stop()
    successor = make(BlockingIngest())
    assert successor.start() is False
    assert "draining" in successor.status()["start_error"]
    fake.release.set()
    await wait_thread_event(fake.done)
    await asyncio.sleep(0.05)
    successor._ingest.release.set()
    assert successor.start() is True
    await successor.stop()
    assert fake.writes == []


async def test_restarted_run_uses_a_fresh_token_and_ingests_normally():
    calls = []

    def record(symbol, allow_live, tag, fallback, should_stop=None):
        calls.append(should_stop())
        return result()

    s = make(record)
    s.start()
    await asyncio.sleep(0.05)
    await s.stop()
    s.start()
    await asyncio.sleep(0.05)
    await s.stop()
    assert calls == [False, False]  # each run saw its own un-cancelled token
    assert s.runs_completed == 2


# --- Finding 2: cross-process single owner ---------------------------------------

async def test_start_refused_when_another_process_holds_the_owner_lock():
    lock = FakeOwnerLock(acquire_result=False)
    s = make(BlockingIngest(), owner_lock=lock)
    assert s.start() is False
    assert "another process" in s.status()["start_error"]
    assert s.status()["running"] is False
    # Refusal must not leave the in-process ownership claimed.
    other = make(BlockingIngest(), owner_lock=FakeOwnerLock())
    other._ingest.release.set()
    assert other.start() is True
    await other.stop()


async def test_owner_lock_error_refuses_start_with_sanitized_error():
    lock = FakeOwnerLock(error=RuntimeError("connect to https://db.example/?token=supersecret failed"))
    s = make(BlockingIngest(), owner_lock=lock)
    assert s.start() is False
    err = s.status()["start_error"]
    assert "supersecret" not in err and "owner lock" in err


async def test_owner_lock_held_while_running_and_released_on_stop():
    lock = FakeOwnerLock()
    fake = BlockingIngest()
    fake.release.set()
    s = make(fake, owner_lock=lock)
    assert s.start() is True
    assert lock.held is True and lock.acquires == 1
    await asyncio.sleep(0.05)
    await s.stop()
    assert lock.held is False and lock.releases == 1


async def test_owner_lock_kept_until_a_timed_out_worker_actually_exits():
    lock = FakeOwnerLock()
    fake = BlockingIngest()
    s = make(fake, owner_lock=lock, drain_timeout_seconds=0.05)
    s.start()
    await wait_thread_event(fake.entered)
    await s.stop()
    assert lock.held is True  # worker still alive: another process must not take over yet
    fake.release.set()
    await wait_thread_event(fake.done)
    for _ in range(50):
        if not lock.held:
            break
        await asyncio.sleep(0.01)
    assert lock.held is False and lock.releases == 1
    assert fake.writes == []


def test_owner_lock_is_postgres_advisory_only_when_database_url_is_set():
    assert sched.build_owner_lock(SimpleNamespace(database_url=None)) is None
    factory = sched.build_owner_lock(SimpleNamespace(database_url="postgresql://u:p@localhost:5432/d"))
    lock = factory()  # per-run factory: each start() gets its own lock/connection
    assert isinstance(lock, sched.PostgresAdvisoryLock)
    assert lock.key == sched.SCHEDULER_ADVISORY_LOCK_KEY


def test_lifespan_wires_the_owner_lock_from_settings(monkeypatch):
    lock = FakeOwnerLock(acquire_result=False)
    settings = SimpleNamespace(enable_scheduler=True, scheduler_symbols="AAPL",
                               scheduler_interval_minutes=30, scheduler_offhours_factor=4,
                               scheduler_tag=False, database_url="postgresql://u:p@localhost/d")
    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    monkeypatch.setattr(api_module, "build_owner_lock", lambda s: lock)
    with TestClient(api_module.app) as client:
        body = client.get("/scheduler/status").json()
    assert body["running"] is False and "another process" in body["start_error"]
    assert lock.acquires == 1


PG_URL = os.environ.get("SCHEDULER_PG_TEST_URL")


@pytest.mark.skipif(not PG_URL, reason="set SCHEDULER_PG_TEST_URL to a THROWAWAY local Postgres")
def test_postgres_advisory_lock_admits_exactly_one_holder():
    first = sched.PostgresAdvisoryLock(PG_URL)
    second = sched.PostgresAdvisoryLock(PG_URL)
    try:
        assert first.acquire() is True
        assert second.acquire() is False  # separate session: refused
        first.release()
        assert second.acquire() is True  # released on stop: next owner can take it
    finally:
        first.release()
        second.release()
