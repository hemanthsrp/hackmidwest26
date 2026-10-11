"""Background ingestion so data stays fresh without someone calling
POST /ingest/run (README section 4, scaled down for a hackathon).

Safety properties, because this writes to a shared database unattended:
- OFF by default (ENABLE_SCHEDULER=false). Nothing runs unless asked.
- Always strict: live=True, fallback=False. A scheduled run can never
  substitute and persist fixtures; a failed source is simply omitted and
  reported, and the next tick tries again.
- No overlapping runs (one asyncio lock), and one symbol failing never stops
  the others or kills the loop.
- Errors are passed through sanitize_error before they are stored or shown.
- Slower outside US market hours (README 4.3 cost guidance): the interval is
  multiplied by SCHEDULER_OFFHOURS_FACTOR on weekends and outside 08:00-18:00
  America/New_York.
- Blocking ingestion (sync httpx/psycopg) runs in a worker thread so it never
  stalls the API's event loop.
"""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .pipeline.ingest import InvalidSymbolError, ingest_symbol, validate_symbol
from .sources.base import sanitize_error

logger = logging.getLogger(__name__)

MARKET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR = 8, 18  # extended window, per README 4.1 (SEC polling 8 AM-6 PM EST)
MIN_INTERVAL_MINUTES = 5  # floor: polite to SEC/Senate/Yahoo and the Akamai embeddings quota
STAGGER_SECONDS = 2.0  # pause between symbols within a run
STARTUP_DELAY_SECONDS = 5.0


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
    ) -> None:
        self.symbols: list[str] = []
        self.skipped: list[str] = []
        for raw in symbols:
            try:
                self.symbols.append(validate_symbol(raw))
            except InvalidSymbolError:
                self.skipped.append(raw)
        self.interval_minutes = max(float(interval_minutes), MIN_INTERVAL_MINUTES)
        self.offhours_factor = max(float(offhours_factor), 1.0)
        self.tag = tag
        self._ingest = ingest_fn
        self._now = now_fn
        self._sleep = sleep_fn
        self._stagger = stagger_seconds
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.statuses: dict[str, SymbolStatus] = {s: SymbolStatus() for s in self.symbols}
        self.runs_completed = 0
        self.next_run_at: str | None = None

    def current_interval_seconds(self) -> float:
        factor = 1.0 if is_market_hours(self._now()) else self.offhours_factor
        return self.interval_minutes * 60 * factor

    async def run_once(self) -> None:
        if self._lock.locked():
            return  # a previous run is still going: skip, never overlap
        async with self._lock:
            for i, symbol in enumerate(self.symbols):
                if i:
                    await self._sleep(self._stagger)
                await self._run_symbol(symbol)
            self.runs_completed += 1

    async def _run_symbol(self, symbol: str) -> None:
        status = self.statuses[symbol]
        status.last_run_at = self._now().isoformat()
        try:
            # Strict on purpose: never substitute (and so never persist) fixtures.
            result = await asyncio.to_thread(self._ingest, symbol, True, self.tag, False)
        except Exception as exc:  # isolate: one bad symbol must not stop the loop
            status.ok = False
            status.consecutive_failures += 1
            status.error = sanitize_error(f"{type(exc).__name__}: {exc}")
            logger.warning("scheduled ingest failed for %s: %s", symbol, status.error)
            return
        status.sources = [{"name": s.name, "status": s.status, "count": s.count} for s in result.sources]
        status.new_evidence, status.new_signals = len(result.evidence), len(result.signals)
        if result.any_live:
            status.ok, status.error, status.consecutive_failures = True, None, 0
        else:
            status.ok = False
            status.consecutive_failures += 1
            status.error = "no source was live"
        logger.info("scheduled ingest %s: +%d evidence, +%d signals", symbol, status.new_evidence, status.new_signals)

    async def run_forever(self) -> None:
        await self._sleep(STARTUP_DELAY_SECONDS)
        while True:
            await self.run_once()
            wait = self.current_interval_seconds()
            wait += random.uniform(0, min(60.0, wait * 0.05))  # jitter so restarts don't synchronize
            self.next_run_at = datetime.fromtimestamp(self._now().timestamp() + wait, tz=timezone.utc).isoformat()
            await self._sleep(wait)

    def start(self) -> None:
        if self._task is None and self.symbols:
            self._task = asyncio.create_task(self.run_forever(), name="scraper-analysis-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def status(self) -> dict:
        return {
            "enabled": True,
            "running": self._task is not None and not self._task.done(),
            "interval_minutes": self.interval_minutes,
            "offhours_factor": self.offhours_factor,
            "market_hours_now": is_market_hours(self._now()),
            "mode": "strict (live only, fixtures never substituted or persisted)",
            "runs_completed": self.runs_completed,
            "next_run_at": self.next_run_at,
            "skipped_invalid_symbols": self.skipped,
            "symbols": {s: st.__dict__ for s, st in self.statuses.items()},
        }
