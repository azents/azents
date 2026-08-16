"""Canonical Scheduled Task schedule tests."""

import datetime

import pytest

from .schedule import (
    InvalidScheduledTaskSchedule,
    advance_cron_cursor,
    parse_rfc3339_explicit_offset,
    validate_schedule,
)


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-16 12:00:00Z",
        "2026-08-16T12:00:00",
        "2026-08-16T12:00:00+0000",
        "2026-08-16T12:00:00+00:00:00",
    ],
)
def test_rfc3339_requires_canonical_explicit_offset(value: str) -> None:
    """Reject datetime.fromisoformat extensions outside RFC3339 input."""
    with pytest.raises(InvalidScheduledTaskSchedule):
        parse_rfc3339_explicit_offset(value)


def test_one_time_z_is_normalized_to_utc() -> None:
    """Accept Z and normalize the instant to UTC."""
    assert parse_rfc3339_explicit_offset("2026-08-16T12:00:00Z") == datetime.datetime(
        2026,
        8,
        16,
        12,
        tzinfo=datetime.UTC,
    )


def test_cron_requires_exactly_five_fields() -> None:
    """Reject seconds and year fields."""
    with pytest.raises(InvalidScheduledTaskSchedule):
        validate_schedule(
            at=None,
            cron_expression="0 0 * * * *",
            timezone="UTC",
            now=datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC),
        )


def test_cron_cursor_includes_exact_due_boundary() -> None:
    """A cursor exactly at now is represented as the due occurrence."""
    instant = datetime.datetime(2026, 8, 16, 12, 0, tzinfo=datetime.UTC)
    due, future = advance_cron_cursor(
        expression="0 * * * *",
        timezone="UTC",
        cursor=instant,
        now=instant,
    )
    assert due == instant
    assert future == instant + datetime.timedelta(hours=1)


def test_cron_cursor_handles_dst_gap_in_named_zone() -> None:
    """Cron calculation persists UTC instants across a DST spring transition."""
    cursor = datetime.datetime(2026, 3, 8, 6, 0, tzinfo=datetime.UTC)
    due, future = advance_cron_cursor(
        expression="30 2 * * *",
        timezone="America/New_York",
        cursor=cursor,
        now=datetime.datetime(2026, 3, 8, 7, 0, tzinfo=datetime.UTC),
    )
    assert due == cursor
    assert future > due
    assert future.tzinfo is datetime.UTC
