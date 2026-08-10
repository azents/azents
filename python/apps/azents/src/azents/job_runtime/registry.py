"""Application Job Runtime handler registry."""

from azents.job_runtime.types import JobHandlerDefinition, JobHandlerRegistry
from azents.scheduler.executor import (
    SCHEDULER_JOB_HANDLER_KEY,
    execute_scheduled_task_job,
)


def get_job_handler_registry() -> JobHandlerRegistry:
    """Return the closed application background-handler registry."""
    return JobHandlerRegistry(
        (
            JobHandlerDefinition(
                key=SCHEDULER_JOB_HANDLER_KEY,
                handler=execute_scheduled_task_job,
            ),
        )
    )
