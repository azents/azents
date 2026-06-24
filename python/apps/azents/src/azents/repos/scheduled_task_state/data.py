"""Scheduled task state repository data."""

import datetime
from dataclasses import dataclass
from typing import Any

from azents.core.enums import ScheduledTaskStatus


@dataclass(frozen=True)
class ScheduledTaskState:
    """Current state of a scheduled task."""

    task_key: str
    latest_status: ScheduledTaskStatus
    next_run_at: datetime.datetime
    last_started_at: datetime.datetime | None
    last_finished_at: datetime.datetime | None
    last_succeeded_at: datetime.datetime | None
    last_failed_at: datetime.datetime | None
    failure_streak: int
    latest_error_code: str | None
    latest_error_message: str | None
    latest_result_summary: dict[str, Any] | None
    lease_owner: str | None
    leased_at: datetime.datetime | None
    lease_until: datetime.datetime | None
    manual_requested_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
