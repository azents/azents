"""Scheduled Task persistence data contracts."""

import datetime
from dataclasses import dataclass

from azents.core.enums import ScheduledTaskScheduleType


@dataclass(frozen=True)
class ScheduledTask:
    """Durable Scheduled Task definition and current scheduling cursor."""

    id: str
    workspace_id: str
    agent_id: str
    session_id: str
    binding_id: str | None
    title: str
    objective: str
    schedule_type: ScheduledTaskScheduleType
    scheduled_at: datetime.datetime | None
    cron_expression: str | None
    timezone: str | None
    next_eligible_at: datetime.datetime
    active_cycle_id: str | None
    active_scheduled_for: datetime.datetime | None
    pending_scheduled_for: datetime.datetime | None
    lease_owner: str | None
    lease_until: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class ScheduledTaskCreate:
    """Values for one newly registered Scheduled Task."""

    workspace_id: str
    agent_id: str
    session_id: str
    title: str
    objective: str
    schedule_type: ScheduledTaskScheduleType
    next_eligible_at: datetime.datetime
    binding_id: str | None
    scheduled_at: datetime.datetime | None
    cron_expression: str | None
    timezone: str | None


@dataclass(frozen=True)
class ScheduledTaskReplace:
    """Editable definition values for one existing Scheduled Task."""

    title: str
    objective: str
    schedule_type: ScheduledTaskScheduleType
    next_eligible_at: datetime.datetime
    binding_id: str | None
    scheduled_at: datetime.datetime | None
    cron_expression: str | None
    timezone: str | None
