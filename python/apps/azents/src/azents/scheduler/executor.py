"""Scheduler Job Runtime handler adapter."""

import datetime

from pydantic import BaseModel

from azents.job_runtime.types import (
    JobExecutionContext,
    JobPayload,
    validate_job_payload,
)
from azents.scheduler.registry import get_task_definitions
from azents.scheduler.types import TaskContext

SCHEDULER_JOB_HANDLER_KEY = "scheduler.task"


class ScheduledTaskJobPayload(BaseModel):
    """JSON-safe Scheduler claim passed through the common Runtime."""

    task_key: str
    attempt_started_at: datetime.datetime
    lease_owner: str
    manual_triggered: bool


async def execute_scheduled_task_job(
    context: JobExecutionContext,
) -> JobPayload | None:
    """Resolve and execute one claimed Scheduler task through task-local DI."""
    payload = ScheduledTaskJobPayload.model_validate(context.request.payload)
    definition = next(
        (
            candidate
            for candidate in get_task_definitions()
            if candidate.key == payload.task_key
        ),
        None,
    )
    if definition is None:
        raise ValueError(f"Unknown scheduled task key: {payload.task_key}")
    result = await definition.handler(
        TaskContext(
            task_key=payload.task_key,
            attempt_started_at=payload.attempt_started_at,
            lease_owner=payload.lease_owner,
            deadline=context.request.deadline,
            manual_triggered=payload.manual_triggered,
            container=context.container,
        )
    )
    if result.summary is None:
        return None
    return validate_job_payload(result.summary)
