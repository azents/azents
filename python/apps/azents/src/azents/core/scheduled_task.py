"""Canonical shared scheduled task contracts."""

from pydantic import BaseModel, Field

MAX_SCHEDULED_TASK_OBJECTIVE_LENGTH = 3_000


class ScheduledTaskCycleTarget(BaseModel):
    """Exact model-supplied selection; separate execution scope grants authority."""

    cycle_id: str = Field(
        min_length=32,
        max_length=32,
        description="Exact server-issued occurrence ID from the current work context.",
    )
