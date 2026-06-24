"""Scheduler service tests."""

import datetime

from azents.scheduler.service import compute_failure_next_run_at
from azents.scheduler.types import RetryPolicy


def test_compute_failure_next_run_at_uses_next_interval() -> None:
    """next_interval retry waits for regular interval."""
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

    result = compute_failure_next_run_at(
        RetryPolicy(kind="next_interval"),
        datetime.timedelta(hours=1),
        3,
        now,
    )

    assert result == now + datetime.timedelta(hours=1)


def test_compute_failure_next_run_at_bounds_backoff() -> None:
    """bounded_backoff is capped by max_delay."""
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

    result = compute_failure_next_run_at(
        RetryPolicy(
            kind="bounded_backoff",
            min_delay=datetime.timedelta(minutes=5),
            max_delay=datetime.timedelta(minutes=30),
        ),
        datetime.timedelta(hours=1),
        5,
        now,
    )

    assert result == now + datetime.timedelta(minutes=30)
