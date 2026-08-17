"""Scheduled Task v1 Public API schemas."""

import datetime
from typing import Literal

from pydantic import BaseModel, Field

from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelProvider,
    ScheduledTaskScheduleType,
)
from azents.repos.scheduled_task.data import MAX_SCHEDULED_TASK_OBJECTIVE_LENGTH
from azents.services.scheduled_task.management import (
    ScheduledTaskCurrentCycleProjection,
    ScheduledTaskManagementProjection,
)


class ScheduledTaskSessionResponse(BaseModel):
    """Canonical Session navigation identity."""

    id: str
    handle: str
    title: str | None


class ScheduledTaskTargetResponse(BaseModel):
    """Opaque External Channel target presentation."""

    channel_id: str
    provider: ExternalChannelProvider
    location: ExternalChannelConversationLocation
    label: str


class ScheduledTaskResponse(BaseModel):
    """Sanitized Scheduled Task management projection."""

    id: str
    title: str
    objective: str
    schedule_type: ScheduledTaskScheduleType
    scheduled_at: datetime.datetime | None
    cron_expression: str | None
    timezone: str | None
    next_eligible_at: datetime.datetime
    execution_state: Literal[
        "idle",
        "admitted",
        "running",
        "running_with_pending",
    ]
    session: ScheduledTaskSessionResponse
    target: ScheduledTaskTargetResponse | None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @classmethod
    def convert_from(
        cls,
        projection: ScheduledTaskManagementProjection,
    ) -> "ScheduledTaskResponse":
        """Convert one service-owned management projection."""
        return cls(
            id=projection.id,
            title=projection.title,
            objective=projection.objective,
            schedule_type=projection.schedule_type,
            scheduled_at=projection.scheduled_at,
            cron_expression=projection.cron_expression,
            timezone=projection.timezone,
            next_eligible_at=projection.next_eligible_at,
            execution_state=projection.execution_state,
            session=ScheduledTaskSessionResponse(
                id=projection.session.id,
                handle=projection.session.handle,
                title=projection.session.title,
            ),
            target=(
                None
                if projection.target is None
                else ScheduledTaskTargetResponse(
                    channel_id=projection.target.channel_id,
                    provider=projection.target.provider,
                    location=projection.target.location,
                    label=projection.target.label,
                )
            ),
            created_at=projection.created_at,
            updated_at=projection.updated_at,
        )


class ScheduledTaskListResponse(BaseModel):
    """Ordered authorized Scheduled Task list."""

    items: list[ScheduledTaskResponse]


class ScheduledTaskCreateRequest(BaseModel):
    """Create one Task for an existing authorized Session."""

    session_id: str = Field(min_length=32, max_length=32)
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(
        min_length=1,
        max_length=MAX_SCHEDULED_TASK_OBJECTIVE_LENGTH,
    )
    at: str | None = Field(max_length=64)
    cron: str | None = Field(max_length=256)
    timezone: str | None = Field(max_length=128)
    channel_id: str | None = Field(min_length=1, max_length=256)


class ScheduledTaskReplaceRequest(BaseModel):
    """Replace editable fields that govern future work."""

    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(
        min_length=1,
        max_length=MAX_SCHEDULED_TASK_OBJECTIVE_LENGTH,
    )
    at: str | None = Field(max_length=64)
    cron: str | None = Field(max_length=256)
    timezone: str | None = Field(max_length=128)
    channel_id: str | None = Field(min_length=1, max_length=256)


class ScheduledTaskCurrentCycleResponse(BaseModel):
    """Sanitized current occurrence projection."""

    phase: Literal["admitted", "started"]
    scheduled_for: datetime.datetime
    started_at: datetime.datetime | None
    progress_title: str | None
    ordered_tasks: list[str]

    @classmethod
    def convert_from(
        cls,
        projection: ScheduledTaskCurrentCycleProjection,
    ) -> "ScheduledTaskCurrentCycleResponse":
        """Convert one current cycle without internal identities."""
        return cls(
            phase=projection.phase,
            scheduled_for=projection.scheduled_for,
            started_at=projection.started_at,
            progress_title=projection.progress_title,
            ordered_tasks=list(projection.ordered_tasks),
        )


class ScheduledTaskCurrentCycleEnvelope(BaseModel):
    """Nullable current cycle for one Task."""

    current_cycle: ScheduledTaskCurrentCycleResponse | None
