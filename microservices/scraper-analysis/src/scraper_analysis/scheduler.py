"""Background ingestion so data stays fresh without someone calling
POST /ingest/run (README section 4, scaled down for a hackathon).

Safety properties, because this writes to a shared database unattended:
- OFF by default (ENABLE_SCHEDULER=false). Nothing runs unless asked.
- Always strict: live=True, fallback=False. A scheduled run can never
  substitute and persist fixtures; a failed source is simply omitted and
  reported, and the next tick tries again.
- Single owner. In-process: a second Scheduler cannot start while one owns
  the process, and a process-wide guard (held by the worker thread for the
  whole ingest) means no two scheduled ingests ever run concurrently here.
  Across processes: when DATABASE_URL is set, start() also takes a Postgres
  session-level advisory lock (SCHEDULER_ADVISORY_LOCK_KEY) on a dedicated
  connection held for the scheduler's lifetime; another worker/replica that
  cannot get it refuses to start and reports start_error. With the in-memory
  store (no DATABASE_URL) there is nothing shared to protect, and the guard
  is single-process only. Manual POST /ingest/run calls are not serialized
  against scheduled runs.
- Shutdown boundary: every start() creates a fresh cancellation token for
  that run; stop() sets it (it is never cleared again, so a restart cannot
  revive a previous run) and ingestion checks it right before every persist.
  stop() then waits (bounded by drain_timeout_seconds) for the in-flight
  ingest. If the drain times out, ownership (in-process and the advisory
  lock) is kept until that worker thread actually exits, so neither a
  restart nor a successor -- in this or another process -- can start while
  it is still alive; they get start_error "... still draining ...". Once
  stop() returns, the only write that can still land is one that had
  already passed its last stop check before the token was set.
- One symbol failing never stops the others or kills the loop.
- Errors are passed through sanitize_error before they are stored or shown.
- Slower outside US market hours (README 4.3 cost guidance): the interval is
  multiplied by SCHEDULER_OFFHOURS_FACTOR on weekends and outside 08:00-18:00
  America/New_York. Interval and factor must be finite and > 0.
- Blocking ingestion (sync httpx/psycopg) runs in a worker thread so it never
  stalls the API's event loop.
"""

import asyncio
import logging
import math
import random
import threading
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

# Process-wide single-owner state (see module docstring).
_OWNER_LOCK = threading.Lock()
_owner: "Scheduler | None" = None
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


def build_owner_lock(settings) -> "PostgresAdvisoryLock | None":
    """Cross-process lock only when there is a shared database to protect."""
    url = getattr(settings, "database_url", None)
    return PostgresAdvisoryLock(url) if url else None


class _Run:
    """One start()..stop() cycle. Its cancel token is set by stop() and never
    cleared, so a worker thread from this run can never be revived by a
    later start()."""

    def __init__(self) -> None:
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.workers = 0
        self.release_on_exit = False  # stop() gave up draining: release when workers hit 0


def _reset_for_tests() -> None:
    global _owner
    with _OWNER_LOCK:
        _owner = None


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
        self._owner_lock = owner_lock  # cross-process: acquire() -> bool, release()
        self._run = _Run()  # replaced by each start(); read by worker threads via capture
        self._draining = False  # a timed-out worker of a stopped run is still alive
        self._stop_event = asyncio.Event()  # wakes the loop's sleeps
        self.statuses: dict[str, SymbolStatus] = {s: SymbolStatus() for s in self.symbols}
        self.runs_completed = 0
        self.runs_interrupted = 0
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

    def _ingest_in_thread(self, symbol: str, run: _Run):
        with run.lock:
            run.workers += 1
        try:
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
        finally:
            with run.lock:
                run.workers -= 1
                release = run.release_on_exit and run.workers == 0
                if release:
                    run.release_on_exit = False
            if release:
                self._release_ownership()

    async def _run_symbol(self, symbol: str, run: _Run | None = None) -> bool:
        """Returns False when shutdown stopped this symbol before it persisted."""
        status = self.statuses[symbol]
        status.last_run_at = self._now().isoformat()
        inflight = asyncio.ensure_future(asyncio.to_thread(self._ingest_in_thread, symbol, run or self._run))
        # If stop() gives up draining, nobody awaits this future: retrieve its
        # outcome so it is never logged as an unhandled exception.
        inflight.add_done_callback(lambda f: f.cancelled() or f.exception())
        try:
            # shield: stop() drains the thread first and cancels this task only
            # after its timeout; the thread keeps the ingest guard until it ends.
            result = await asyncio.shield(inflight)
        except asyncio.CancelledError:
            status.ok = False
            status.error = ("interrupted by shutdown: ingest still running after the drain timeout; "
                            "it will not persist after its next stop check")
            raise
        except IngestCancelled as exc:
            status.ok = False
            status.new_evidence, status.new_signals = exc.evidence_saved, exc.signals_saved
            status.error = sanitize_error(f"stopped by shutdown, nothing further persisted: {exc}")
            logger.info("scheduled ingest for %s stopped by shutdown: %s", symbol, status.error)
            return False
        except SchedulerBusy as exc:
            status.ok = False
            status.error = str(exc)
            logger.warning("scheduled ingest for %s %s", symbol, exc)
            return True
        except Exception as exc:  # isolate: one bad symbol must not stop the loop
            status.ok = False
            status.consecutive_failures += 1
            status.error = sanitize_error(f"{type(exc).__name__}: {exc}")
            logger.warning("scheduled ingest failed for %s: %s", symbol, status.error)
            return True
        status.sources = [{"name": s.name, "status": s.status, "count": s.count} for s in result.sources]
        status.new_evidence, status.new_signals = len(result.evidence), len(result.signals)
        if result.any_live:
            status.ok, status.error, status.consecutive_failures = True, None, 0
        else:
            status.ok = False
            status.consecutive_failures += 1
            status.error = "no source was live"
        logger.info("scheduled ingest %s: +%d evidence, +%d signals", symbol, status.new_evidence, status.new_signals)
        return True

    async def run_forever(self) -> None:
        run = self._run
        await self._wait(STARTUP_DELAY_SECONDS)
        while not run.cancel.is_set():
            try:
                await self.run_once()
            except Exception:  # defensive: never let one bad run end the loop
                logger.exception("scheduled run failed unexpectedly")
            if run.cancel.is_set():
                break
            wait = self.current_interval_seconds()
            wait += random.uniform(0, min(60.0, wait * 0.05))  # jitter so restarts don't synchronize
            self.next_run_at = datetime.fromtimestamp(self._now().timestamp() + wait, tz=timezone.utc).isoformat()
            await self._wait(wait)
        self.next_run_at = None

    def start(self) -> bool:
        """Start the loop. Returns False (and sets start_error) when there is
        nothing to do, another Scheduler owns this process, a previous run's
        worker is still draining, or another process holds the owner lock."""
        global _owner
        if self._task is not None:
            return True
        if not self.symbols:
            self.start_error = "no valid symbols configured"
            return False
        with _OWNER_LOCK:
            if _owner is not None and (_owner is not self or self._draining):
                if _owner._draining:
                    self.start_error = ("a previous scheduler run is still draining an in-flight ingest "
                                        "in this process; retry after it finishes")
                else:
                    self.start_error = "another scheduler is already running in this process; only one may own it"
                logger.warning("scheduler not started: %s", self.start_error)
                return False
            _owner = self
        if self._owner_lock is not None:
            try:
                acquired = self._owner_lock.acquire()
                error = None if acquired else (
                    "another process already owns the scheduler (Postgres advisory lock held); "
                    "only one worker/replica may run it")
            except Exception as exc:
                error = sanitize_error(f"could not take the scheduler owner lock: {type(exc).__name__}: {exc}")
            if error is not None:
                with _OWNER_LOCK:
                    if _owner is self:
                        _owner = None
                self.start_error = error
                logger.warning("scheduler not started: %s", error)
                return False
        self.start_error = None
        self._run = _Run()  # fresh token; the previous run's token stays set forever
        self._stop_event.clear()
        self._task = asyncio.create_task(self.run_forever(), name="scraper-analysis-scheduler")
        return True

    def _release_ownership(self) -> None:
        """Release the cross-process lock, then in-process ownership. Called
        from stop() or, after a drain timeout, from the last worker thread."""
        global _owner
        try:
            if self._owner_lock is not None:
                self._owner_lock.release()
        except Exception as exc:
            logger.warning("releasing scheduler owner lock failed: %s", sanitize_error(exc))
        finally:
            with _OWNER_LOCK:
                self._draining = False
                if _owner is self:
                    _owner = None

    async def stop(self) -> None:
        """Cancel this run's token, drain the in-flight ingest (bounded), release ownership.

        After this returns no new persist starts: ingestion checks the run's
        token before every write, and no later start() can clear it. A write
        already in progress is awaited for up to drain_timeout_seconds; past
        that the task is cancelled and the thread is left to finish -- it keeps
        the ingest guard, and ownership (including the cross-process advisory
        lock) is only released when it exits, so nothing can start meanwhile."""
        run = self._run
        run.cancel.set()
        self._stop_event.set()
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
                    self._draining = True
            if deferred:
                logger.warning("scheduler ownership kept until the in-flight ingest thread exits")
            else:
                self._release_ownership()

    def status(self) -> dict:
        return {
            "enabled": True,
            "running": self._task is not None and not self._task.done(),
            "draining": self._draining,
            "cross_process_lock": self._owner_lock is not None,
            "start_error": self.start_error,
            "interval_minutes": self.interval_minutes,
            "offhours_factor": self.offhours_factor,
            "market_hours_now": is_market_hours(self._now()),
            "mode": "strict (live only, fixtures never substituted or persisted)",
            "runs_completed": self.runs_completed,
            "runs_interrupted": self.runs_interrupted,
            "next_run_at": self.next_run_at,
            "skipped_invalid_symbols": self.skipped,
            "symbols": {s: st.__dict__ for s, st in self.statuses.items()},
        }
