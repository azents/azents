"""Operator sampling uses ordinary source preparation and common Worker routing."""

import asyncio
import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.services.historical_memory.consolidation_discovery import (
    HistoricalMemoryConsolidationDiscoveryService,
)
from azents.services.historical_memory.discovery import HistoricalMemoryDiscoveryService
from azents.services.historical_memory.preparation import (
    HistoricalMemoryPreparationService,
    HistoricalMemoryPreparationSummary,
)


@dataclasses.dataclass(frozen=True)
class HistoricalMemorySamplingReport:
    now: datetime.datetime
    admitted: int
    due_agents: int
    attempted: int
    prepared: int
    empty: int
    failed: int
    quota_advanced: int
    consolidation_dispatched: int


@dataclasses.dataclass(frozen=True)
class HistoricalMemorySamplingService:
    """Sample Stage 1 time without an independent Memory execution loop."""

    discovery: Annotated[
        HistoricalMemoryDiscoveryService, Depends(HistoricalMemoryDiscoveryService)
    ]
    preparation: Annotated[
        HistoricalMemoryPreparationService, Depends(HistoricalMemoryPreparationService)
    ]
    consolidation_discovery: Annotated[
        HistoricalMemoryConsolidationDiscoveryService,
        Depends(HistoricalMemoryConsolidationDiscoveryService),
    ]

    async def sample_agent(
        self, *, agent_id: str, now: datetime.datetime, consolidate: bool
    ) -> HistoricalMemorySamplingReport:
        """Prepare sources, then dispatch real Worker work without claiming success."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Historical sampling requires an aware timestamp.")
        now = now.astimezone(datetime.UTC)
        prepared = HistoricalMemoryPreparationSummary(0, 0, 0, 0, 0)
        async with asyncio.timeout(120):
            admission = await self.discovery.admit_and_list_due_agents(
                now=now, agent_id=agent_id
            )
            if agent_id in admission.due_agent_ids:
                prepared = await self.preparation.prepare_agent(
                    agent_id=agent_id,
                    now=now,
                    deadline=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(seconds=110),
                )
        dispatched = (
            await self.consolidation_discovery.dispatch_pending(agent_id=agent_id)
            if consolidate
            else 0
        )
        return HistoricalMemorySamplingReport(
            now,
            admission.admitted,
            len(admission.due_agent_ids),
            prepared.attempted,
            prepared.prepared,
            prepared.empty,
            prepared.failed,
            prepared.quota_advanced,
            dispatched,
        )
