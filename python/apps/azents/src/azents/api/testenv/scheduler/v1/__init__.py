"""Credential-free scheduler execution controls."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from azents.scheduler.deps import get_scheduler_service
from azents.scheduler.service import SchedulerService
from azents.utils.fastapi.route import RouteMounter

router = APIRouter()


class SchedulerRunRequest(BaseModel):
    """Exact scheduler task requested for one execution pass."""

    model_config = ConfigDict(extra="forbid")

    task_key: str


class SchedulerRunResponse(BaseModel):
    """Completed scheduler execution request."""

    task_key: str


@router.post("/run")
async def run_scheduler_task(
    body: SchedulerRunRequest,
    scheduler: Annotated[SchedulerService, Depends(get_scheduler_service)],
) -> SchedulerRunResponse:
    """Trigger one task and execute a real scheduler pass."""
    state = await scheduler.trigger(body.task_key)
    if state is None:
        raise HTTPException(status_code=404, detail="Scheduler task not found.")
    await scheduler.run_once()
    return SchedulerRunResponse(task_key=body.task_key)


def mount(mounter: RouteMounter) -> None:
    """Mount credential-free Scheduler devtools."""
    mounter(
        router,
        prefix="/scheduler/v1",
        tag="Scheduler v1",
        description="Deterministic execution of registered scheduler tasks",
    )
