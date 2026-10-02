"""Scheduler dependency providers."""

from typing import Annotated

from fastapi import Depends

from azents.job_runtime.deps import get_job_runtime
from azents.job_runtime.types import JobRuntime
from azents.repos.scheduler_state_operations import SchedulerStateOperationRepository
from azents.scheduler.service import SchedulerService


def get_scheduler_service(
    repository: Annotated[
        SchedulerStateOperationRepository,
        Depends(SchedulerStateOperationRepository),
    ],
    job_runtime: Annotated[JobRuntime, Depends(get_job_runtime)],
) -> SchedulerService:
    """Build a Scheduler service without exposing runtime fields as API inputs."""
    return SchedulerService(
        repository=repository,
        job_runtime=job_runtime,
    )
