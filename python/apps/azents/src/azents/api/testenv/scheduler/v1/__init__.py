"""Credential-free scheduler execution controls."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from azents.scheduler.deps import get_scheduler_service
from azents.scheduler.service import SchedulerService
from azents.scheduler.user_scheduled_task_dispatch import (
    get_user_scheduled_task_dispatcher,
)
from azents.services.historical_memory.sampling import (
    HistoricalMemorySamplingService,
)
from azents.services.scheduled_task.service import ScheduledTaskDispatcher
from azents.utils.fastapi.route import RouteMounter

router = APIRouter()
_TESTENV_SCHEDULED_TASK_LEASE_OWNER = "testenv-scheduled-task-dispatch"


class SchedulerRunRequest(BaseModel):
    """Exact scheduler task requested for one execution pass."""

    model_config = ConfigDict(extra="forbid")

    task_key: str


class SchedulerRunResponse(BaseModel):
    """Completed scheduler execution request."""

    task_key: str


class ScheduledTaskDispatchRequest(BaseModel):
    """Exact aware instant used to claim due user Scheduled Tasks."""

    model_config = ConfigDict(extra="forbid")

    now: AwareDatetime


class ScheduledTaskDispatchResponse(BaseModel):
    """Aggregate result from one bounded user Scheduled Task dispatch pass."""

    now: datetime.datetime
    claimed: int
    admitted: int
    coalesced: int
    skipped: int
    wake_failed: int


class HistoricalMemorySampleRequest(BaseModel):
    """Sample one product-created Agent at a deterministic aware instant."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    now: AwareDatetime
    consolidate: bool


class HistoricalMemorySampleResponse(BaseModel):
    """Safe aggregate evidence from ordinary admission and preparation."""

    now: datetime.datetime
    admitted: int
    due_agents: int
    attempted: int
    prepared: int
    empty: int
    failed: int
    quota_advanced: int
    consolidation_dispatched: int


@router.post("/historical-memory/sample")
async def sample_historical_memory(
    body: HistoricalMemorySampleRequest,
    sampling: Annotated[HistoricalMemorySamplingService, Depends()],
) -> HistoricalMemorySampleResponse:
    """Run real bounded services without changing source activity.

    Optional consolidation routes actual common Worker Sessions. A dispatched
    notification is not publication evidence; callers observe accepted results
    separately. Sampling never overrides execution ownership or admitted clocks.
    """
    now = body.now.astimezone(datetime.UTC)
    report = await sampling.sample_agent(
        now=now, agent_id=body.agent_id, consolidate=body.consolidate
    )
    return HistoricalMemorySampleResponse(**dataclasses.asdict(report))


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


@router.post("/scheduled-tasks/dispatch")
async def dispatch_scheduled_tasks(
    body: ScheduledTaskDispatchRequest,
    dispatcher: Annotated[
        ScheduledTaskDispatcher,
        Depends(get_user_scheduled_task_dispatcher),
    ],
) -> ScheduledTaskDispatchResponse:
    """Dispatch due user Scheduled Tasks at one deterministic test instant."""
    now = body.now.astimezone(datetime.UTC)
    summary = await dispatcher.dispatch_once(
        lease_owner=_TESTENV_SCHEDULED_TASK_LEASE_OWNER,
        now=now,
    )
    return ScheduledTaskDispatchResponse(
        now=now,
        claimed=summary.claimed,
        admitted=summary.admitted,
        coalesced=summary.coalesced,
        skipped=summary.skipped,
        wake_failed=summary.wake_failed,
    )


def mount(mounter: RouteMounter) -> None:
    """Mount credential-free Scheduler devtools."""
    mounter(
        router,
        prefix="/scheduler/v1",
        tag="Scheduler v1",
        description="Deterministic execution of registered scheduler tasks",
    )
