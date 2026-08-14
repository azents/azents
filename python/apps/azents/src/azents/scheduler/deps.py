"""Scheduler dependency providers."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.job_runtime.deps import get_job_runtime
from azents.job_runtime.types import JobRuntime
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.scheduled_task_state import ScheduledTaskStateRepository
from azents.scheduler.service import SchedulerService


def get_scheduler_service(
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ],
    state_repository: Annotated[
        ScheduledTaskStateRepository,
        Depends(ScheduledTaskStateRepository),
    ],
    job_runtime: Annotated[JobRuntime, Depends(get_job_runtime)],
) -> SchedulerService:
    """Build a Scheduler service without exposing runtime fields as API inputs."""
    return SchedulerService(
        session_manager=session_manager,
        state_repository=state_repository,
        job_runtime=job_runtime,
    )
