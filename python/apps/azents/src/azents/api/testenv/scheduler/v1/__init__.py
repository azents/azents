"""Credential-free scheduler execution controls."""

import asyncio
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
from azents.services.historical_memory.discovery import HistoricalMemoryDiscoveryService
from azents.services.historical_memory.preparation import (
    HistoricalMemoryPreparationService,
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


@router.post("/historical-memory/sample")
async def sample_historical_memory(
    body: HistoricalMemorySampleRequest,
    discovery: Annotated[HistoricalMemoryDiscoveryService, Depends()],
    preparation: Annotated[HistoricalMemoryPreparationService, Depends()],
) -> HistoricalMemorySampleResponse:
    """Run real bounded services without changing source activity.

    This isolated testenv sampling endpoint proves admission, model execution,
    and publication. Scheduler dispatch and Job Runtime supervision have
    separate integration coverage; this endpoint does not bypass their clocks
    or claim to execute a registered job.
    """
    now = body.now.astimezone(datetime.UTC)
    async with asyncio.timeout(120):
        sample = await discovery.admit_and_list_due_agents(
            now=now,
            agent_id=body.agent_id,
        )
        counters = {
            "attempted": 0,
            "prepared": 0,
            "empty": 0,
            "failed": 0,
            "quota_advanced": 0,
        }
        if body.agent_id in sample.due_agent_ids:
            summary = await preparation.prepare_agent(
                agent_id=body.agent_id,
                deadline=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(seconds=110),
                now=now,
            )
            counters = dataclasses.asdict(summary)
    return HistoricalMemorySampleResponse(
        now=now,
        admitted=sample.admitted,
        due_agents=len(sample.due_agent_ids),
        **counters,
    )


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
