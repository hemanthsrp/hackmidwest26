"""Background ingestion so data stays fresh without someone calling
POST /ingest/run (README section 4, scaled down for a hackathon).

Safety properties, because this writes to a shared database unattended:
- OFF by default (ENABLE_SCHEDULER=false). Nothing runs unless asked.
- Always strict: live=True, fallback=False. A scheduled run can never
  substitute and persist fixtures; a failed source is simply omitted and
  reported, and the next tick tries again.
- Single owner, as a token bound to one run. Every start() creates a _Run;
  process-wide ownership is that run object (not the Scheduler), and it is
  released compare-and-release: only if the releasing run is still the
  current owner. A stopping or draining run keeps ownership, so a restart
  racing stop() -- or any successor instance -- is refused with start_error
  until that run has fully released. Across processes: when DATABASE_URL is
  set, each run takes its OWN Postgres session-level advisory lock
  (SCHEDULER_ADVISORY_LOCK_KEY) on its own dedicated connection (the owner
  lock is a per-run factory), so an old run can only ever release its own
  connection, never a later run's. Another worker/replica that cannot get the
  lock refuses to start and reports start_error. With the in-memory store (no
  DATABASE_URL) there is nothing shared to protect. A process-wide guard held
  by the worker thread means no two scheduled ingests run concurrently here.
  Manual POST /ingest/run calls are not serialized against scheduled runs.
- Shutdown boundary (exactly this, no more): stop() sets the run's
  cancellation token (never cleared, so a restart cannot revive the run) and
  ingestion checks it right before every persist, so no NEW write starts
  after the stop flag. stop() then waits up to drain_timeout_seconds for the
  in-flight ingest. A write that had already passed its last stop check is
  not interrupted: if the drain times out it may complete AFTER stop()
  returns. Until that worker thread actually exits, status reports
  draining=true / late_writes_possible=true and ownership (in-process and the
  advisory lock) is kept; when it exits its real outcome is recorded
  (finished_after_stop, sanitized error or late counts).
- A late worker outcome is always retrieved by the worker wrapper itself: an
  abandoned call returns nothing to asyncio, so no exception (or secret in its
  message) can reach asyncio's "never retrieved" handler or stderr.
- One symbol failing never stops the others or kills the loop.
- Errors are passed through sanitize_error before they are stored or shown.
- Slower outside US market hours (README 4.3 cost guidance): the interval is
  multiplied by SCHEDULER_OFFHOURS_FACTOR on weekends and outside 08:00-18:00
  America/New_York. Interval and factor must be finite and > 0.
- Blocking ingestion (sync httpx/psycopg) runs in a worker thread so it never
  stalls the API's event loop.
"""

import asyncio
import functools
import logging
import math
import random
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .pipeline.ingest import (
    IngestCancelled,
    InvalidSymbolError,
    ingest_symbol,
    validate_symbol,
)
from .sources.base import sanitize_error

logger = logging.getLogger(__name__)

MARKET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR = 8, 18  # extended window, per README 4.1 (SEC polling 8 AM-6 PM EST)
MIN_INTERVAL_MINUTES = 5  # floor: polite to SEC/Senate/Yahoo and the Akamai embeddings quota
STAGGER_SECONDS = 2.0  # pause between symbols within a run
STARTUP_DELAY_SECONDS = 5.0
DRAIN_TIMEOUT_SECONDS = 30.0  # how long stop() waits for an in-flight ingest

# Fixed, project-specific key for pg_try_advisory_lock ("SCRAPER1" in ASCII).
SCHEDULER_ADVISORY_LOCK_KEY = 0x5343524150455231
OWNER_LOCK_CONNECT_TIMEOUT_SECONDS = 10

# Process-wide single-owner state (see module docstring): the owning _Run.
_OWNER_LOCK = threading.Lock()
_owner_run: "_Run | None" = None
# Held by the worker thread for the duration of one ingest, so it stays held
# even if the owning asyncio task was cancelled after a drain timeout.
_INGEST_GUARD = threading.Lock()


class SchedulerBusy(RuntimeError):
    """Another scheduled ingest is still running in this process."""


class PostgresAdvisoryLock:
    """Cross-process scheduler ownership: a session-level advisory lock held on
    a dedicated connection for the scheduler's lifetime. If the process dies
    the connection drops and Postgres releases the lock automatically."""

    def __init__(self, database_url: str, key: int = SCHEDULER_ADVISORY_LOCK_KEY) -> None:
        self._url = database_url  # TLS is enforced in the URL by Settings validation
        self.key = key
        self._conn = None

    def acquire(self) -> bool:
        import psycopg

        if self._conn is not None:
            return True
        conn = psycopg.connect(self._url, autocommit=True, connect_timeout=OWNER_LOCK_CONNECT_TIMEOUT_SECONDS)
        try:
            got = conn.execute("SELECT pg_try_advisory_lock(%s)", (self.key,)).fetchone()[0]
        except BaseException:
            conn.close()
            raise
        if not got:
            conn.close()
            return False
        self._conn = conn
        return True

    def release(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            conn.execute("SELECT pg_advisory_unlock(%s)", (self.key,))
        except Exception as exc:  # closing the session releases it anyway
            logger.warning("advisory unlock failed, closing session: %s", sanitize_error(exc))
        finally:
            conn.close()


def build_owner_lock(settings) -> "Callable[[], PostgresAdvisoryLock] | None":
    """Cross-process lock only when there is a shared database to protect.
    Returns a per-run factory: each start() gets its own lock object and so
    its own connection, which only that run can ever release."""
    url = getattr(settings, "database_url", None)
    return functools.partial(PostgresAdvisoryLock, url) if url else None


def _lock_factory(owner_lock):
    """Accept a per-run factory (preferred) or, for tests/back-compat, a single
    lock object. A single object is safe only because ownership is a run
    token: a new run cannot acquire it until the previous run released it."""
    if owner_lock is None:
        return None
    if hasattr(owner_lock, "acquire"):
        return lambda: owner_lock
    if callable(owner_lock):
        return owner_lock
    raise TypeError("owner_lock must be a factory or an object with acquire()/release()")


class _Call:
    """One worker-thread ingest of one symbol, shared by the thread and the
    awaiting coroutine (both touch it only under the run's lock)."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.finished = False
        self.abandoned = False  # the awaiting coroutine gave up (drain timeout)
        self.result = None
        self.error: BaseException | None = None


class _Run:
    """One start()..stop() cycle and the process-wide ownership token. Its
    cancel token is set by stop() and never cleared, so a worker thread from
    this run can never be revived by a later start()."""

    def __init__(self, scheduler: "Scheduler | None" = None) -> None:
        self.scheduler = scheduler
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.workers = 0
        self.stopping = False  # stop() has been called for this run
        self.release_on_exit = False  # stop() gave up draining: release when workers hit 0
        self.released = False
        self.owner_lock = None  # this run's own cross-process lock, once acquired


def _reset_for_tests() -> None:
    global _owner_run
    with _OWNER_LOCK:
        _owner_run = None


def positive_finite(name: str, value: float) -> float:
    """Reject nan/inf/<=0, which would otherwise end the loop (nan/inf sleep
    and timestamp math) or make it spin (zero/negative)."""
    v = float(value)
    if not math.isfinite(v) or v <= 0:
        raise ValueError(f"{name} must be a finite number greater than 0 (got {value!r})")
    return v


def normalize_symbols(raw_symbols) -> tuple[list[str], list[str]]:
    """Validate + normalize, de-duplicating both lists while preserving order."""
    symbols: list[str] = []
    skipped: list[str] = []
    for raw in raw_symbols:
        try:
            symbol = validate_symbol(str(raw))
        except InvalidSymbolError:
            shown = str(raw).strip()
            if shown not in skipped:
                skipped.append(shown)
            continue
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols, skipped


@dataclass
class SymbolStatus:
    last_run_at: str | None = None
    ok: bool | None = None
    new_evidence: int = 0
    new_signals: int = 0
    sources: list[dict] = field(default_factory=list)
    error: str | None = None
    consecutive_failures: int = 0
    # Set when this symbol's ingest was abandoned by a timed-out drain: first
    # "still running", then what actually happened once the worker exited.
    after_stop: str | None = None
    finished_after_stop: bool = False


def is_market_hours(now: datetime) -> bool:
    local = now.astimezone(MARKET_TZ)
    return local.weekday() < 5 and MARKET_OPEN_HOUR <= local.hour < MARKET_CLOSE_HOUR


class Scheduler:
    def __init__(
        self,
        symbols: list[str],
        interval_minutes: float = 30,
        offhours_factor: float = 4,
        tag: bool = True,
        ingest_fn=ingest_symbol,
        now_fn=lambda: datetime.now(timezone.utc),
        sleep_fn=asyncio.sleep,
        stagger_seconds: float = STAGGER_SECONDS,
        drain_timeout_seconds: float = DRAIN_TIMEOUT_SECONDS,
        owner_lock=None,
    ) -> None:
        self.symbols, self.skipped = normalize_symbols(symbols)
        self.interval_minutes = max(positive_finite("interval_minutes", interval_minutes), MIN_INTERVAL_MINUTES)
        self.offhours_factor = max(positive_finite("offhours_factor", offhours_factor), 1.0)
        self.tag = tag
        self._ingest = ingest_fn
        self._now = now_fn
        self._sleep = sleep_fn
        self._stagger = stagger_seconds
        self._drain_timeout = drain_timeout_seconds
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        # cross-process: factory() -> object with acquire() -> bool, release()
        self._owner_lock_factory = _lock_factory(owner_lock)
        self._run = _Run(None)  # replaced by each start(); placeholder never owns anything
        self._stop_future: asyncio.Future | None = None
        self._stop_event = asyncio.Event()  # wakes the loop's sleeps
        self._status_lock = threading.Lock()  # statuses are also written by late worker threads
        self.statuses: dict[str, SymbolStatus] = {s: SymbolStatus() for s in self.symbols}
        self.runs_completed = 0
        self.runs_interrupted = 0
        self.finished_after_stop = 0
        self.next_run_at: str | None = None
        self.start_error: str | None = None

    def current_interval_seconds(self) -> float:
        factor = 1.0 if is_market_hours(self._now()) else self.offhours_factor
        return self.interval_minutes * 60 * factor

    async def _wait(self, seconds: float) -> None:
        """Sleep via the injected sleep_fn, but wake early when stop() is called."""
        if self._stop_event.is_set():
            return
        sleeper = asyncio.ensure_future(self._sleep(seconds))
        stopper = asyncio.ensure_future(self._stop_event.wait())
        try:
            done, _ = await asyncio.wait({sleeper, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if sleeper in done:
                sleeper.result()  # propagate errors/cancellation raised by sleep_fn
        finally:
            for t in (sleeper, stopper):
                if not t.done():
                    t.cancel()

    async def run_once(self) -> None:
        run = self._run
        if self._lock.locked():
            return  # a previous run on this instance is still going: skip
        async with self._lock:
            completed = True
            try:
                for i, symbol in enumerate(self.symbols):
                    if i:
                        await self._wait(self._stagger)
                    if run.cancel.is_set():
                        completed = False
                        break
                    if not await self._run_symbol(symbol, run):
                        completed = False
            except asyncio.CancelledError:
                self.runs_interrupted += 1
                raise
            if completed:
                self.runs_completed += 1
            else:
                self.runs_interrupted += 1

    def _guarded_ingest(self, symbol: str, run: _Run):
        if not _INGEST_GUARD.acquire(blocking=False):
            raise SchedulerBusy("skipped: another scheduled ingest is still in flight in this process")
        try:
            if run.cancel.is_set():
                raise IngestCancelled("cancelled by shutdown before starting")
            # Strict on purpose: never substitute (and so never persist) fixtures.
            # should_stop is bound to THIS run's token, never to a later run's.
            return self._ingest(symbol, True, self.tag, False, should_stop=run.cancel.is_set)
        finally:
            _INGEST_GUARD.release()

    def _ingest_in_thread(self, symbol: str, run: _Run, call: _Call | None = None):
        call = call or _Call(symbol)
        with run.lock:
            run.workers += 1
        res, err = None, None
        try:
            res = self._guarded_ingest(symbol, run)
        except BaseException as exc:  # noqa: BLE001 -- handed back below, or recorded if abandoned
            err = exc
        with run.lock:
            run.workers -= 1
            call.finished, call.result, call.error = True, res, err
            late = call.abandoned
            release = run.release_on_exit and run.workers == 0
            if release:
                run.release_on_exit = False
        try:
            if late:
                # Nobody awaits this call any more: record the real outcome
                # (sanitized) here and return nothing, so no exception object
                # ever reaches asyncio's "never retrieved" handler or stderr.
                self._record_outcome(symbol, res, err, late=True)
                return None
        finally:
            if release:
                self._release_run(run)
        if err is not None:
            try:
                raise err
            finally:
                del err
        return res

    def _record_outcome(self, symbol: str, result, exc: BaseException | None, late: bool = False) -> bool:
        """Apply one ingest outcome to status. Returns False when shutdown
        stopped the symbol before it persisted everything."""
        status = self.statuses[symbol]
        when = "after stop() returned (drain timed out)" if late else None
        with self._status_lock:
            if late:
                status.finished_after_stop = True
                self.finished_after_stop += 1
            if isinstance(exc, IngestCancelled):
                status.ok = False
                status.new_evidence, status.new_signals = exc.evidence_saved, exc.signals_saved
                if late:
                    status.error = sanitize_error(
                        f"stopped by shutdown at its stop check {when}; "
                        f"{exc.evidence_saved} evidence / {exc.signals_saved} signals had been saved: {exc}")
                    status.after_stop = status.error
                else:
                    status.error = sanitize_error(f"stopped by shutdown before its next write: {exc}")
                logger.info("scheduled ingest for %s stopped by shutdown: %s", symbol, status.error)
                return False
            if isinstance(exc, SchedulerBusy):
                status.ok = False
                status.error = str(exc)
                logger.warning("scheduled ingest for %s %s", symbol, exc)
                return not late
            if exc is not None:
                if not isinstance(exc, Exception):  # BaseException (e.g. SystemExit) in the thread
                    status.ok = False
                    status.error = sanitize_error(f"worker aborted: {type(exc).__name__}")
                    if late:
                        status.after_stop = status.error
                        return False
                    raise exc
                status.ok = False
                status.consecutive_failures += 1
                prefix = f"failed {when}: " if late else ""
                status.error = sanitize_error(f"{prefix}{type(exc).__name__}: {exc}")
                if late:
                    status.after_stop = status.error
                logger.warning("scheduled ingest failed for %s: %s", symbol, status.error)
                return not late
            status.sources = [{"name": s.name, "status": s.status, "count": s.count} for s in result.sources]
            status.new_evidence, status.new_signals = len(result.evidence), len(result.signals)
            if result.any_live:
                status.ok, status.error, status.consecutive_failures = True, None, 0
            else:
                status.ok = False
                status.consecutive_failures += 1
                status.error = "no source was live"
            if late:
                status.after_stop = (f"finished {when}; its writes landed late: "
                                     f"+{status.new_evidence} evidence, +{status.new_signals} signals")
            logger.info("scheduled ingest %s: +%d evidence, +%d signals%s", symbol, status.new_evidence,
                        status.new_signals, " (after stop)" if late else "")
            return not late

    async def _run_symbol(self, symbol: str, run: _Run | None = None) -> bool:
        """Returns False when shutdown stopped this symbol before it persisted."""
        run = run or self._run
        status = self.statuses[symbol]
        with self._status_lock:
            status.last_run_at = self._now().isoformat()
            status.after_stop, status.finished_after_stop = None, False
        call = _Call(symbol)
        inflight = asyncio.ensure_future(asyncio.to_thread(self._ingest_in_thread, symbol, run, call))
        # Belt and braces: whatever happens to the awaiting task, retrieve the
        # future's outcome so asyncio never reports it as never-retrieved.
        inflight.add_done_callback(_consume_future)
        try:
            # shield: stop() drains the thread first and cancels this task only
            # after its timeout; the thread keeps the ingest guard until it ends.
            res = await asyncio.shield(inflight)
        except asyncio.CancelledError:
            with run.lock:
                finished = call.finished
                if not finished:
                    call.abandoned = True  # the worker records its own outcome on exit
            if finished:
                self._record_outcome(symbol, call.result, call.error)
            else:
                with self._status_lock:
                    status.ok = False
                    status.error = ("interrupted by shutdown: still running when the drain timed out. No new "
                                    "write starts after the stop signal, but a write already in progress may "
                                    "still complete after stop() returns; see after_stop once the worker exits")
                    status.after_stop = "still running"
            raise
        except BaseException as exc:  # noqa: BLE001 -- classified (and re-raised if fatal) below
            return self._record_outcome(symbol, None, exc)
        return self._record_outcome(symbol, res, None)

    async def run_forever(self) -> None:
        run = self._run
        await self._wait(STARTUP_DELAY_SECONDS)
        while not run.cancel.is_set():
            try:
                await self.run_once()
            except Exception as exc:  # defensive: never let one bad run end the loop
                logger.error("scheduled run failed unexpectedly: %s", sanitize_error(f"{type(exc).__name__}: {exc}"))
            if run.cancel.is_set():
                break
            wait = self.current_interval_seconds()
            wait += random.uniform(0, min(60.0, wait * 0.05))  # jitter so restarts don't synchronize
            self.next_run_at = datetime.fromtimestamp(self._now().timestamp() + wait, tz=timezone.utc).isoformat()
            await self._wait(wait)
        self.next_run_at = None

    def start(self) -> bool:
        """Start the loop. Returns False (and sets start_error) when there is
        nothing to do, another scheduler run owns this process (including this
        instance's previous run while it is still stopping or draining), or
        another process holds the owner lock."""
        global _owner_run
        if self._task is not None:
            return True
        if not self.symbols:
            self.start_error = "no valid symbols configured"
            return False
        run = _Run(self)
        with _OWNER_LOCK:
            current = _owner_run
            if current is not None:
                if current.stopping:
                    self.start_error = ("a previous scheduler run is still stopping/draining an in-flight "
                                        "ingest in this process; retry after it finishes")
                else:
                    self.start_error = "another scheduler is already running in this process; only one may own it"
                logger.warning("scheduler not started: %s", self.start_error)
                return False
            _owner_run = run  # ownership token = this run object
        if self._owner_lock_factory is not None:
            lock = None
            try:
                lock = self._owner_lock_factory()
                acquired = lock.acquire()
                error = None if acquired else (
                    "another process already owns the scheduler (Postgres advisory lock held); "
                    "only one worker/replica may run it")
            except Exception as exc:
                error = sanitize_error(f"could not take the scheduler owner lock: {type(exc).__name__}: {exc}")
            if error is not None:
                self._release_run(run)  # compare-and-release: frees only this run's claim
                self.start_error = error
                logger.warning("scheduler not started: %s", error)
                return False
            run.owner_lock = lock  # this run's own lock (own connection); only it releases it
        self.start_error = None
        self._run = run  # fresh token; the previous run's token stays set forever
        self._stop_future = None
        self._stop_event.clear()
        self._task = asyncio.create_task(self.run_forever(), name="scraper-analysis-scheduler")
        return True

    def _release_run(self, run: _Run) -> None:
        """Compare-and-release: release ``run``'s own cross-process lock, then
        the in-process ownership only if ``run`` is still the owner. A stale
        run (e.g. a late worker of an old run) can never free a newer run's
        ownership or lock. Idempotent per run."""
        global _owner_run
        with run.lock:
            if run.released:
                return
            run.released = True
            lock, run.owner_lock = run.owner_lock, None
        try:
            if lock is not None:
                lock.release()
        except Exception as exc:
            logger.warning("releasing scheduler owner lock failed: %s", sanitize_error(exc))
        finally:
            with _OWNER_LOCK:
                if _owner_run is run:
                    _owner_run = None

    async def stop(self) -> None:
        """Cancel this run's token, drain the in-flight ingest (bounded), release ownership.

        After the token is set no NEW persist starts: ingestion checks it
        before every write, and no later start() can clear it. A write that
        already passed its last check is awaited for up to
        drain_timeout_seconds; past that the task is cancelled and the thread
        is left to finish, so that write MAY complete after this returns. The
        run keeps ownership (in-process and its advisory lock) until that
        thread exits -- status shows draining / late_writes_possible -- and the
        thread then records what it actually did (finished_after_stop)."""
        if self._stop_future is not None:  # a concurrent stop(): wait for the same drain
            await asyncio.shield(self._stop_future)
            return
        run = self._run
        with run.lock:
            run.stopping = True  # from here start() is refused until this run releases
        run.cancel.set()
        self._stop_event.set()
        self._stop_future = asyncio.get_running_loop().create_future()
        task, self._task = self._task, None
        try:
            if task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(task), self._drain_timeout)
                except TimeoutError:
                    logger.warning("scheduler drain exceeded %.1fs; cancelling", self._drain_timeout)
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                except asyncio.CancelledError:
                    task.cancel()
                    raise
        finally:
            with run.lock:  # same lock the worker takes on exit: no lost release
                deferred = run.workers > 0
                run.release_on_exit = deferred
            if deferred:
                logger.warning("scheduler ownership kept until the in-flight ingest thread exits; "
                               "a write already in progress may still complete")
            else:
                self._release_run(run)
            if not self._stop_future.done():
                self._stop_future.set_result(None)

    def _draining(self) -> bool:
        run = self._run
        with run.lock:
            return run.stopping and not run.released

    def status(self) -> dict:
        draining = self._draining()
        with self._status_lock:
            symbols = {s: dict(st.__dict__) for s, st in self.statuses.items()}
        return {
            "enabled": True,
            "running": self._task is not None and not self._task.done(),
            # A stopped run's worker is still alive: it may still finish a
            # write that had passed its last stop check before stop().
            "draining": draining,
            "late_writes_possible": draining,
            "finished_after_stop": self.finished_after_stop,
            "cross_process_lock": self._owner_lock_factory is not None,
            "start_error": self.start_error,
            "interval_minutes": self.interval_minutes,
            "offhours_factor": self.offhours_factor,
            "market_hours_now": is_market_hours(self._now()),
            "mode": "strict (live only, fixtures never substituted or persisted)",
            "runs_completed": self.runs_completed,
            "runs_interrupted": self.runs_interrupted,
            "next_run_at": self.next_run_at,
            "skipped_invalid_symbols": self.skipped,
            "symbols": symbols,
        }


def _consume_future(fut: asyncio.Future) -> None:
    """Done-callback: mark the outcome retrieved. Never logs or re-raises it;
    the scheduler records a sanitized summary itself."""
    if not fut.cancelled():
        fut.exception()
