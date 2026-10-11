"""Regression tests for the third PR #16 review round (hbot on 9b45987 / 476ead3):

1. "A concurrent restart during stop() can let the old run release the new
   run's owner lock": start() raced stop()'s drain, then the old run's release
   path freed the in-process ownership and the (shared) owner lock that now
   belonged to the new run.
2. "stop() leaves an unobserved shielded to_thread future after the drain times
   out": a late worker outcome (exception / IngestCancelled) must be retrieved,
   sanitized and recorded -- never reach asyncio's handler or stderr raw.
3. "A DB write already entered before the stop check can finish after stop()
   returns": status and docs must say so, and status must report it.

Deterministic: worker threads are coordinated with threading.Event; the only
sleeps are short bounded polls."""

import asyncio
import gc
import inspect
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scraper_analysis import scheduler as sched
from scraper_analysis.pipeline import ingest
from scraper_analysis.pipeline.ingest import IngestResult, SourceReport

MARKET_OPEN = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)
SECRET = "SECRET123XYZ"


def result():
    return IngestResult([None] * 2, [None], [SourceReport("sec_edgar", "live", 3)])


async def instant_startup_then_park(seconds):
    if seconds == sched.STARTUP_DELAY_SECONDS or seconds < 60:
        await asyncio.sleep(0)
    else:
        await asyncio.sleep(3600)


class FakeOwnerLock:
    def __init__(self):
        self.held = False
        self.acquires = 0
        self.releases = 0

    def acquire(self) -> bool:
        self.acquires += 1
        self.held = True
        return True

    def release(self) -> None:
        self.releases += 1
        self.held = False


class LockFactory:
    """Per-run owner-lock factory that records every lock it hands out."""

    def __init__(self):
        self.created: list[FakeOwnerLock] = []

    def __call__(self) -> FakeOwnerLock:
        lock = FakeOwnerLock()
        self.created.append(lock)
        return lock


class FirstCallBlocks:
    """First call blocks *before* its stop check until released; later calls
    return at once. ``raise_exc`` makes the first call raise instead."""

    def __init__(self, raise_exc=None):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.done = threading.Event()
        self.raise_exc = raise_exc
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
                if self.raise_exc is not None:
                    raise self.raise_exc
            if should_stop is not None and should_stop():
                raise ingest.IngestCancelled("stopped before persisting")
            self.writes.append(symbol)
            return result()
        finally:
            if first:
                self.done.set()


class WriteInProgress:
    """Passes its stop check (not stopped yet), then blocks *inside* the write."""

    def __init__(self):
        self.in_write = threading.Event()
        self.release = threading.Event()
        self.done = threading.Event()
        self.writes: list[str] = []

    def __call__(self, symbol, allow_live, tag, fallback, should_stop=None):
        try:
            assert should_stop is not None and not should_stop()  # last stop check passed
            self.in_write.set()
            assert self.release.wait(5), "test never released the write"
            self.writes.append(symbol)  # the write lands -- possibly after stop() returned
            return result()
        finally:
            self.done.set()


def make(ingest_fn, **kw):
    return sched.Scheduler(["AAPL"], ingest_fn=ingest_fn, now_fn=lambda: MARKET_OPEN,
                           sleep_fn=instant_startup_then_park, stagger_seconds=0, **kw)


async def wait_thread_event(event: threading.Event):
    assert await asyncio.to_thread(event.wait, 5)


async def until(predicate, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


@pytest.fixture(autouse=True)
def _reset_owner():
    sched._reset_for_tests()
    yield
    sched._reset_for_tests()


# --- Finding 1: restart racing stop() ---------------------------------------------

async def test_restart_while_stop_is_still_draining_is_refused():
    fake = FirstCallBlocks()
    s = make(fake, owner_lock=FakeOwnerLock(), drain_timeout_seconds=5)
    assert s.start() is True
    await wait_thread_event(fake.entered)
    stopping = asyncio.ensure_future(s.stop())
    await asyncio.sleep(0.02)  # stop() is now awaiting the drain
    assert s.start() is False
    assert "stopping" in s.status()["start_error"] or "draining" in s.status()["start_error"]
    fake.release.set()
    await stopping
    assert fake.writes == []


@pytest.mark.parametrize("drain_timeout", [0.05, 5.0])
async def test_concurrent_restart_never_loses_the_new_runs_ownership(drain_timeout):
    """Whatever start() returns while stop() drains, a scheduler that is running
    afterwards must still hold its owner lock and the in-process ownership."""
    fake = FirstCallBlocks()
    lock = FakeOwnerLock()
    s = make(fake, owner_lock=lock, drain_timeout_seconds=drain_timeout)
    s.start()
    await wait_thread_event(fake.entered)
    stopping = asyncio.ensure_future(s.stop())
    await asyncio.sleep(0.02)
    s.start()  # races the drain
    if drain_timeout > 1:
        fake.release.set()  # drain completes inside stop()
    await stopping
    fake.release.set()  # (timed-out case) the old worker exits only now
    await wait_thread_event(fake.done)
    await until(lambda: not s.status()["draining"])
    await asyncio.sleep(0.05)
    if s.status()["running"]:
        assert lock.held is True, "old run released the new run's owner lock"
    other = make(FirstCallBlocks(), owner_lock=FakeOwnerLock())
    other._ingest.release.set()
    if s.status()["running"]:
        assert other.start() is False, "old run released the new run's in-process ownership"
    await other.stop()
    await s.stop()
    assert fake.writes == []


async def test_each_run_gets_its_own_owner_lock_and_old_release_cannot_touch_the_new_one():
    factory = LockFactory()
    fake = FirstCallBlocks()
    fake.release.set()
    s = make(fake, owner_lock=factory)
    assert s.start() is True
    old_run = s._run
    await asyncio.sleep(0.05)
    await s.stop()
    assert s.start() is True
    assert len(factory.created) == 2 and factory.created[0] is not factory.created[1]
    first, second = factory.created
    assert first.held is False and first.releases == 1
    assert second.held is True
    # A stale release from the old run (e.g. its late worker exit) is a no-op.
    s._release_run(old_run)
    assert second.held is True and second.releases == 0
    assert make(FirstCallBlocks()).start() is False  # still owned by the new run
    await s.stop()
    assert second.held is False and second.releases == 1


async def test_release_is_compare_and_release_on_the_run_token():
    s = make(FirstCallBlocks(), owner_lock=LockFactory())
    s._ingest.release.set()
    assert s.start() is True
    stale = sched._Run(s)  # a run that never owned anything
    s._release_run(stale)
    assert make(FirstCallBlocks()).start() is False
    await s.stop()
    assert make(FirstCallBlocks()).start() is True


def test_build_owner_lock_returns_a_per_run_factory():
    assert sched.build_owner_lock(SimpleNamespace(database_url=None)) is None
    factory = sched.build_owner_lock(SimpleNamespace(database_url="postgresql://u:***@localhost:5432/d"))
    a, b = factory(), factory()
    assert isinstance(a, sched.PostgresAdvisoryLock) and isinstance(b, sched.PostgresAdvisoryLock)
    assert a is not b  # separate connection per run
    assert a.key == b.key == sched.SCHEDULER_ADVISORY_LOCK_KEY


# --- Finding 2: late worker outcome after a drain timeout -------------------------

def _no_secret(text: str):
    assert SECRET not in text


@pytest.mark.parametrize("exc", [
    RuntimeError(f"upstream failed api_token={SECRET} at https://x.example/p?key={SECRET}"),
    ingest.IngestCancelled(f"cancelled api_token={SECRET}", evidence_saved=2),
])
async def test_late_worker_outcome_is_retrieved_sanitized_and_recorded(exc, capsys, caplog):
    loop = asyncio.get_running_loop()
    handled = []
    loop.set_exception_handler(lambda _loop, ctx: handled.append(ctx))
    fake = FirstCallBlocks(raise_exc=exc)
    s = make(fake, drain_timeout_seconds=0.05)
    s.start()
    await wait_thread_event(fake.entered)
    await s.stop()  # drain times out; the worker is still alive
    assert s.status()["draining"] is True
    fake.release.set()
    await wait_thread_event(fake.done)
    assert await until(lambda: not s.status()["draining"])
    del exc
    gc.collect()
    await asyncio.sleep(0.05)
    gc.collect()
    st = s.status()["symbols"]["AAPL"]
    assert st["finished_after_stop"] is True
    assert st["ok"] is False
    assert "after stop() returned" in st["error"]
    if isinstance(fake.raise_exc, ingest.IngestCancelled):
        assert "<redacted>" in st["error"] and st["new_evidence"] == 2
    else:
        assert "RuntimeError" in st["error"] and "<redacted>" in st["error"]
        assert st["consecutive_failures"] == 1
    out = capsys.readouterr()
    for text in (out.out, out.err, caplog.text, repr(st), repr(handled)):
        _no_secret(text)
    assert handled == []  # nothing reached asyncio's exception handler


def test_late_worker_exception_after_the_event_loop_closed_is_recorded_not_printed(capfd):
    fake = FirstCallBlocks(raise_exc=RuntimeError(f"boom password={SECRET}"))
    holder = {}

    async def main():
        s = make(fake, drain_timeout_seconds=0.05)
        holder["s"] = s
        s.start()
        await wait_thread_event(fake.entered)
        await s.stop()
        # The worker raises only once main() returned and asyncio.run() is
        # tearing the loop down (cancelling leftover tasks, joining executor).
        threading.Timer(0.2, fake.release.set).start()

    asyncio.run(main())
    assert fake.done.wait(5)
    s = holder["s"]
    for _ in range(200):
        if not s.status()["draining"]:
            break
        threading.Event().wait(0.01)
    gc.collect()
    st = s.status()["symbols"]["AAPL"]
    assert st["finished_after_stop"] is True and "<redacted>" in st["error"]
    out, err = capfd.readouterr()
    _no_secret(out)
    _no_secret(err)
    assert "never retrieved" not in err and "Traceback" not in err


# --- Finding 3: a write already in progress may finish after stop() returns --------

async def test_write_in_progress_during_timed_out_drain_finishes_late_and_is_reported():
    fake = WriteInProgress()
    s = make(fake, drain_timeout_seconds=0.05)
    s.start()
    await wait_thread_event(fake.in_write)
    await s.stop()  # drain times out mid-write
    body = s.status()
    assert body["draining"] is True and body["late_writes_possible"] is True
    err = body["symbols"]["AAPL"]["error"]
    assert "will not persist" not in err and "nothing further" not in err
    assert "may still complete" in err
    assert fake.writes == []
    fake.release.set()  # ...and the write lands after stop() returned
    await wait_thread_event(fake.done)
    assert await until(lambda: not s.status()["draining"])
    body = s.status()
    assert fake.writes == ["AAPL"]
    st = body["symbols"]["AAPL"]
    assert st["finished_after_stop"] is True
    assert st["new_evidence"] == 2 and st["new_signals"] == 1
    assert "after stop() returned" in (st["after_stop"] or "")
    assert body["finished_after_stop"] == 1
    assert body["late_writes_possible"] is False


def test_docs_and_comments_do_not_overclaim_the_stop_boundary():
    src = inspect.getsource(ingest)
    assert "must not persist" not in src
    assert "may complete after" in src
    assert "will not persist after its next stop check" not in inspect.getsource(sched)
