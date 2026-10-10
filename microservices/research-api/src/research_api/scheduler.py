"""Configuration seam for an external scheduler or process manager."""

import time
from collections.abc import Callable, Mapping

_MIN_INTERVAL_SECONDS = 15 * 60
_MAX_INTERVAL_SECONDS = 60 * 60


class SchedulerConfigurationError(ValueError):
    """Raised when the refresh interval is unsafe for the demo scheduler."""


def scheduler_interval_seconds(environ: Mapping[str, str]) -> int:
    """Read a 15–60 minute refresh cadence without starting a background worker."""
    raw_interval = environ.get("RESEARCH_REFRESH_INTERVAL_SECONDS", str(_MIN_INTERVAL_SECONDS))
    try:
        interval = int(raw_interval)
    except ValueError as error:
        raise SchedulerConfigurationError(
            "RESEARCH_REFRESH_INTERVAL_SECONDS must be an integer from 900 to 3600"
        ) from error

    if not _MIN_INTERVAL_SECONDS <= interval <= _MAX_INTERVAL_SECONDS:
        raise SchedulerConfigurationError(
            "RESEARCH_REFRESH_INTERVAL_SECONDS must be from 900 to 3600"
        )
    return interval


def run_scheduler(
    refresh: Callable[[], None],
    environ: Mapping[str, str],
    sleep: Callable[[float], None] = time.sleep,
    max_cycles: int | None = None,
) -> None:
    """Run an injected refresh hook at a validated 15–60 minute cadence.

    ``max_cycles`` is useful for local smoke checks; omit it in a managed worker.
    """
    interval = scheduler_interval_seconds(environ)
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        refresh()
        cycles += 1
        if max_cycles is None or cycles < max_cycles:
            sleep(interval)
