"""Application Job Runtime handler registry."""

from azents.job_runtime.types import JobHandlerDefinition, JobHandlerRegistry
from azents.scheduler.executor import (
    SCHEDULER_JOB_HANDLER_KEY,
    execute_scheduled_task_job,
)
from azents.services.external_channel.ingress_queue import (
    EXTERNAL_CHANNEL_INGRESS_JOB_HANDLER_KEY,
    execute_external_channel_ingress_job,
)
from azents.services.historical_memory.job import (
    HISTORICAL_MEMORY_MAX_CONCURRENCY,
    HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
    execute_historical_memory_preparation_job,
)


def get_job_handler_registry() -> JobHandlerRegistry:
    """Return the closed application background-handler registry."""
    return JobHandlerRegistry(
        (
            JobHandlerDefinition(
                key=EXTERNAL_CHANNEL_INGRESS_JOB_HANDLER_KEY,
                handler=execute_external_channel_ingress_job,
                rerun_on_coalesce=True,
            ),
            JobHandlerDefinition(
                key=SCHEDULER_JOB_HANDLER_KEY,
                handler=execute_scheduled_task_job,
            ),
            JobHandlerDefinition(
                key=HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
                handler=execute_historical_memory_preparation_job,
                max_concurrency=HISTORICAL_MEMORY_MAX_CONCURRENCY,
            ),
        )
    )
