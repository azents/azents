"""Scheduled Task cycle Toolkit State contracts."""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from azents.core.enums import (
    ExternalChannelWorkProjectionStatus,
    ScheduledTaskScheduleType,
)


class ScheduledTaskCycleState(BaseModel):
    """Immutable occurrence snapshot plus mutable runtime admission state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    cycle_id: str = Field(min_length=32, max_length=32)
    task_id: str = Field(min_length=32, max_length=32)
    phase: Literal["admitted", "started"]
    workspace_id: str = Field(min_length=32, max_length=32)
    agent_id: str = Field(min_length=32, max_length=32)
    session_id: str = Field(min_length=32, max_length=32)
    binding_id: str | None = Field(min_length=32, max_length=32)
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    schedule_type: ScheduledTaskScheduleType
    scheduled_at: datetime.datetime | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    scheduled_for: datetime.datetime
    current_run_id: str | None = Field(min_length=32, max_length=32)
    started_at: datetime.datetime | None
    progress_title: str | None
    ordered_tasks: list[str] = Field(default_factory=list)
    tracker_desired_revision: int = Field(default=0, ge=0)
    tracker_current_projection_parts: list["ScheduledTrackerProjectionPart"] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_tracker_projection_parts(self) -> "ScheduledTaskCycleState":
        """Require deterministic current Tracker projection identities."""
        ordinals = [part.part_ordinal for part in self.tracker_current_projection_parts]
        if ordinals != sorted(ordinals):
            raise ValueError("Scheduled Tracker projection parts must be ordered.")
        if len(ordinals) != len(set(ordinals)):
            raise ValueError(
                "Scheduled Tracker projection part ordinals must be unique."
            )
        if any(
            part.desired_revision > self.tracker_desired_revision
            for part in self.tracker_current_projection_parts
        ):
            raise ValueError(
                "Scheduled Tracker projection revision exceeds desired state."
            )
        return self


class ScheduledTaskCycleRecord(BaseModel):
    """Cycle state with Toolkit State row version for CAS updates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: ScheduledTaskCycleState
    version: int = Field(ge=1)
    toolkit_state_id: str = Field(min_length=32, max_length=32)


class ScheduledTaskCycleSnapshot(BaseModel):
    """Immutable admitted Task snapshot used to create a cycle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cycle_id: str = Field(min_length=32, max_length=32)
    task_id: str = Field(min_length=32, max_length=32)
    workspace_id: str = Field(min_length=32, max_length=32)
    agent_id: str = Field(min_length=32, max_length=32)
    session_id: str = Field(min_length=32, max_length=32)
    binding_id: str | None = Field(min_length=32, max_length=32)
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    schedule_type: ScheduledTaskScheduleType
    scheduled_at: datetime.datetime | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    scheduled_for: datetime.datetime


class ScheduledTrackerProjectionPart(BaseModel):
    """Current provider projection state for one ordered Scheduled Tracker part."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    part_ordinal: int = Field(ge=0)
    desired_revision: int = Field(ge=0)
    status: ExternalChannelWorkProjectionStatus
    provider_message_key: str | None
