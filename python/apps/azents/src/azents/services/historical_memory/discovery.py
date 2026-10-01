"""Historical Memory rolling admission and Agent-job dispatch."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.job_runtime.deps import get_job_runtime
from azents.job_runtime.types import JobRequest, JobRuntime
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.services.historical_memory.constants import (
    HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
)

_ADMISSION_LIMIT = 500
_DUE_AGENT_LIMIT = 25
_INACTIVITY = datetime.timedelta(hours=6)
_FIRST_ADMISSION_AGE = datetime.timedelta(days=10)
_PREPARATION_DEADLINE = datetime.timedelta(minutes=30)


@dataclasses.dataclass(frozen=True)
class HistoricalMemoryDiscoverySummary:
    """One bounded discovery/admission/dispatch result."""

    admitted: int
    due_agents: int
    dispatched: int


@dataclasses.dataclass
class HistoricalMemoryDiscoveryService:
    """Admit rolling sources and submit coalesced per-Agent preparation jobs."""

    repository: Annotated[
        HistoricalMemoryRepository,
        Depends(HistoricalMemoryRepository),
    ]
    job_runtime: Annotated[JobRuntime, Depends(get_job_runtime)]

    async def discover_once(self) -> HistoricalMemoryDiscoverySummary:
        """Run one bounded database pass and post-commit dispatch."""
        now = datetime.datetime.now(datetime.UTC)
        admitted = await self.repository.admit_eligible_sources(
            now=now,
            oldest_activity_at=now - _FIRST_ADMISSION_AGE,
            inactive_before=now - _INACTIVITY,
            limit=_ADMISSION_LIMIT,
        )
        due_agent_ids = await self.repository.list_due_agent_ids(
            now=now,
            inactive_before=now - _INACTIVITY,
            limit=_DUE_AGENT_LIMIT,
        )
        dispatched = 0
        for agent_id in due_agent_ids:
            await self.job_runtime.submit(
                JobRequest(
                    handler_key=HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
                    execution_key=f"historical-memory:{agent_id}",
                    deadline=now + _PREPARATION_DEADLINE,
                    payload={"agent_id": agent_id},
                )
            )
            dispatched += 1
        return HistoricalMemoryDiscoverySummary(
            admitted=len(admitted),
            due_agents=len(due_agent_ids),
            dispatched=dispatched,
        )
