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


@dataclasses.dataclass(frozen=True)
class HistoricalMemoryAdmissionSample:
    """Bounded admission result and authorized due-Agent identities."""

    admitted: int
    due_agent_ids: tuple[str, ...]


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
        sample = await self.admit_and_list_due_agents(
            now=None,
            agent_id=None,
        )
        deadline = datetime.datetime.now(datetime.UTC) + _PREPARATION_DEADLINE
        dispatched = 0
        for agent_id in sample.due_agent_ids:
            await self.job_runtime.submit(
                JobRequest(
                    handler_key=HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
                    execution_key=f"historical-memory:{agent_id}",
                    deadline=deadline,
                    payload={"agent_id": agent_id},
                )
            )
            dispatched += 1
        return HistoricalMemoryDiscoverySummary(
            admitted=sample.admitted,
            due_agents=len(sample.due_agent_ids),
            dispatched=dispatched,
        )

    async def admit_and_list_due_agents(
        self,
        *,
        now: datetime.datetime | None,
        agent_id: str | None,
    ) -> HistoricalMemoryAdmissionSample:
        """Sample real admission and due work, optionally for one Agent.

        Production passes no sampling instant or Agent filter. The isolated
        testenv sampler supplies both without modifying source activity.
        """
        if now is not None and (now.tzinfo is None or now.utcoffset() is None):
            raise ValueError("Historical Memory sampling instant must be aware.")
        sampled_at = (
            now.astimezone(datetime.UTC)
            if now is not None
            else datetime.datetime.now(datetime.UTC)
        )
        admitted = await self.repository.admit_eligible_sources(
            agent_id=agent_id,
            now=sampled_at,
            oldest_activity_at=sampled_at - _FIRST_ADMISSION_AGE,
            inactive_before=sampled_at - _INACTIVITY,
            limit=_ADMISSION_LIMIT,
        )
        if agent_id is not None:
            due = await self.repository.list_due_for_agent(
                agent_id=agent_id,
                now=sampled_at,
                inactive_before=sampled_at - _INACTIVITY,
                limit=1,
            )
            return HistoricalMemoryAdmissionSample(
                admitted=len(admitted),
                due_agent_ids=(agent_id,) if due else (),
            )
        due_agent_ids = await self.repository.list_due_agent_ids(
            now=sampled_at,
            inactive_before=sampled_at - _INACTIVITY,
            limit=_DUE_AGENT_LIMIT,
        )
        return HistoricalMemoryAdmissionSample(
            admitted=len(admitted),
            due_agent_ids=tuple(due_agent_ids),
        )
