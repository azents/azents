"""Scheduled Task management detached projections and stable errors."""

import dataclasses
import datetime
from typing import Literal

from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelProvider,
    ScheduledTaskScheduleType,
)

ScheduledTaskExecutionState = Literal[
    "idle",
    "admitted",
    "running",
    "running_with_pending",
]


class ScheduledTaskManagementUnavailable(ValueError):
    """Stable fail-closed management error."""

    def __init__(
        self,
        code: Literal["not_found", "invalid_schedule", "conflict"],
    ) -> None:
        super().__init__(code)
        self.code = code


@dataclasses.dataclass(frozen=True)
class ScheduledTaskSessionProjection:
    """Canonical Session navigation identity for one Task."""

    id: str
    handle: str
    title: str | None


@dataclasses.dataclass(frozen=True)
class ScheduledTaskTargetProjection:
    """Opaque current External Channel target presentation."""

    channel_id: str
    provider: ExternalChannelProvider
    location: ExternalChannelConversationLocation
    label: str


@dataclasses.dataclass(frozen=True)
class ScheduledTaskManagementProjection:
    """Sanitized Task definition and derived management state."""

    id: str
    title: str
    objective: str
    schedule_type: ScheduledTaskScheduleType
    scheduled_at: datetime.datetime | None
    cron_expression: str | None
    timezone: str | None
    next_eligible_at: datetime.datetime
    execution_state: ScheduledTaskExecutionState
    session: ScheduledTaskSessionProjection
    target: ScheduledTaskTargetProjection | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class ScheduledTaskCurrentCycleProjection:
    """Sanitized current occurrence state without internal identities."""

    phase: Literal["admitted", "started"]
    scheduled_for: datetime.datetime
    started_at: datetime.datetime | None
    progress_title: str | None
    ordered_tasks: tuple[str, ...]
