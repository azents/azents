"""Provider-neutral Scheduled Task runtime message rendering."""

import datetime

from azents.core.enums import ScheduledTaskScheduleType
from azents.repos.scheduled_task.schedule import (
    CanonicalSchedule,
    canonical_schedule_text,
)


def render_scheduled_task_runtime_message(
    *,
    title: str,
    objective: str,
    schedule_type: ScheduledTaskScheduleType,
    scheduled_at: datetime.datetime | None,
    cron_expression: str | None,
    timezone: str | None,
    scheduled_for: datetime.datetime,
) -> str:
    """Render complete canonical guidance for one Scheduled occurrence."""
    schedule = CanonicalSchedule(
        schedule_type=schedule_type,
        scheduled_at=scheduled_at,
        cron_expression=cron_expression,
        timezone=timezone,
        next_eligible_at=scheduled_for,
    )
    return (
        "Scheduled Task work is due.\n"
        f"Title: {title}\n"
        f"Objective: {objective}\n"
        f"Schedule: {canonical_schedule_text(schedule)}\n"
        f"Scheduled for: {_utc_text(scheduled_for)}\n"
        "Continue autonomously across Agent runs until the objective is complete. "
        "If required information, authority, user choice, or another prerequisite "
        "is unavailable after reasonable attempts, submit a failed result explaining "
        "what is missing. Submit a finished or failed Scheduled Task result explicitly."
    )


def _utc_text(value: datetime.datetime) -> str:
    """Render one timezone-aware instant as canonical UTC RFC3339 text."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Scheduled Task runtime instant must be timezone-aware.")
    return value.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")
