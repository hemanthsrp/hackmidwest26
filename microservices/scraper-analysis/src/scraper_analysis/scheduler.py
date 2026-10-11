"""Background ingestion so data stays fresh without someone calling
POST /ingest/run (README section 4, scaled down for a hackathon).

Safety properties, because this writes to a shared database unattended:
- OFF by default (ENABLE_SCHEDULER=false). Nothing runs unless asked.
- Always strict: live=True, fallback=False. A scheduled run can never
  substitute and persist fixtures; a failed source is simply omitted and
  reported, and the next tick tries again.
- One scheduler owner per process: a second Scheduler cannot start while one
  is running, and a process-wide guard (held by the worker thread for the
  whole ingest) means no two scheduled ingests run concurrently in this
  process -- including a successor started while a predecessor's ingest is
  still finishing. This is NOT enforced across processes: with several
  uvicorn workers or replicas, enable the scheduler on exactly one of them.
  Manual POST /ingest/run calls are not serialized against it either.
- Shutdown boundary: stop() raises a stop flag that ingestion checks right
  before every persist, then waits (bounded by drain_timeout_seconds) for the
  in-flight ingest to finish. Once stop() returns, the only write that can
  still land is one that had already started before the flag was raised and
  outlived the drain timeout.
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

# Process-wide single-owner state (see module docstring).
_OWNER_LOCK = threading.Lock()
_owner: "Scheduler | None" = None
# Held by the worker thread for the duration of one ingest, so it stays held
# even if the owning asyncio task was cancelled after a drain timeout.
_INGEST_GUARD = threading.Lock()


class SchedulerBusy(RuntimeError):
    """Another scheduled ingest is still running in this process."""


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
        self._stop_flag = threading.Event()  # read by the worker thread before persisting
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
        if self._lock.locked():
            return  # a previous run on this instance is still going: skip
        async with self._lock:
            completed = True
            try:
                for i, symbol in enumerate(self.symbols):
                    if i:
                        await self._wait(self._stagger)
                    if self._stop_flag.is_set():
                        completed = False
                        break
                    if not await self._run_symbol(symbol):
                        completed = False
            except asyncio.CancelledError:
                self.runs_interrupted += 1
                raise
            if completed:
                self.runs_completed += 1
            else:
                self.runs_interrupted += 1

    def _ingest_in_thread(self, symbol: str):
        if not _INGEST_GUARD.acquire(blocking=False):
            raise SchedulerBusy("skipped: another scheduled ingest is still in flight in this process")
        try:
            if self._stop_flag.is_set():
                raise IngestCancelled("cancelled by shutdown before starting")
            # Strict on purpose: never substitute (and so never persist) fixtures.
            return self._ingest(symbol, True, self.tag, False, should_stop=self._stop_flag.is_set)
        finally:
            _INGEST_GUARD.release()

    async def _run_symbol(self, symbol: str) -> bool:
        """Returns False when shutdown stopped this symbol before it persisted."""
        status = self.statuses[symbol]
        status.last_run_at = self._now().isoformat()
        inflight = asyncio.ensure_future(asyncio.to_thread(self._ingest_in_thread, symbol))
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
        await self._wait(STARTUP_DELAY_SECONDS)
        while not self._stop_flag.is_set():
            try:
                await self.run_once()
            except Exception:  # defensive: never let one bad run end the loop
                logger.exception("scheduled run failed unexpectedly")
            if self._stop_flag.is_set():
                break
            wait = self.current_interval_seconds()
            wait += random.uniform(0, min(60.0, wait * 0.05))  # jitter so restarts don't synchronize
            self.next_run_at = datetime.fromtimestamp(self._now().timestamp() + wait, tz=timezone.utc).isoformat()
            await self._wait(wait)
        self.next_run_at = None

    def start(self) -> bool:
        """Start the loop. Returns False (and sets start_error) when there is
        nothing to do or another Scheduler already owns this process."""
        global _owner
        if self._task is not None:
            return True
        if not self.symbols:
            self.start_error = "no valid symbols configured"
            return False
        with _OWNER_LOCK:
            if _owner is not None and _owner is not self:
                self.start_error = "another scheduler is already running in this process; only one may own it"
                logger.warning("scheduler not started: %s", self.start_error)
                return False
            _owner = self
        self.start_error = None
        self._stop_flag.clear()
        self._stop_event.clear()
        self._task = asyncio.create_task(self.run_forever(), name="scraper-analysis-scheduler")
        return True

    async def stop(self) -> None:
        """Raise the stop flag, drain the in-flight ingest (bounded), release ownership.

        After this returns no new persist starts: ingestion checks the stop flag
        before every write. A write already in progress when the flag was raised
        is awaited for up to drain_timeout_seconds; past that, the task is
        cancelled and the thread is left to finish (it keeps the process-wide
        ingest guard, so a successor cannot overlap it)."""
        global _owner
        self._stop_flag.set()
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
            with _OWNER_LOCK:
                if _owner is self:
                    _owner = None

    def status(self) -> dict:
        return {
            "enabled": True,
            "running": self._task is not None and not self._task.done(),
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
