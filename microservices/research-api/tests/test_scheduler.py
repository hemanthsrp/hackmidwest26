import pytest

from research_api.scheduler import (
    SchedulerConfigurationError,
    run_scheduler,
    scheduler_interval_seconds,
)


def test_scheduler_hook_defaults_to_a_fifteen_minute_interval() -> None:
    assert scheduler_interval_seconds({}) == 900


def test_scheduler_hook_accepts_an_hour_interval() -> None:
    assert scheduler_interval_seconds({"RESEARCH_REFRESH_INTERVAL_SECONDS": "3600"}) == 3600


@pytest.mark.parametrize("value", ["899", "3601", "not-a-number"])
def test_scheduler_hook_rejects_intervals_outside_the_demo_window(value: str) -> None:
    with pytest.raises(SchedulerConfigurationError):
        scheduler_interval_seconds({"RESEARCH_REFRESH_INTERVAL_SECONDS": value})


def test_scheduler_hook_runs_refreshes_at_the_configured_cadence() -> None:
    refreshes: list[str] = []
    sleeps: list[int] = []

    run_scheduler(
        refresh=lambda: refreshes.append("ran"),
        environ={"RESEARCH_REFRESH_INTERVAL_SECONDS": "1800"},
        sleep=sleeps.append,
        max_cycles=2,
    )

    assert refreshes == ["ran", "ran"]
    assert sleeps == [1800]
