"""Explicit-time testenv sampling through the ordinary production Memory services."""

import asyncio
import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.core.historical_memory_publication import ConsolidationOutputError
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.discovery import (
    ConsolidationDiscoveryRepository,
)
from azents.services.historical_memory.consolidation_job import (
    HistoricalMemoryConsolidationService,
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
    consolidation_due: int
    consolidation_published: int
    consolidation_unclaimed: int
    consolidation_failed: int


@dataclasses.dataclass
class HistoricalMemorySamplingService:
    """No SQL, fake foreground identity, alternate loop or product clock override."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    discovery: Annotated[
        HistoricalMemoryDiscoveryService, Depends(HistoricalMemoryDiscoveryService)
    ]
    preparation: Annotated[
        HistoricalMemoryPreparationService, Depends(HistoricalMemoryPreparationService)
    ]
    consolidation: Annotated[
        HistoricalMemoryConsolidationService,
        Depends(HistoricalMemoryConsolidationService),
    ]

    async def sample_agent(
        self,
        *,
        agent_id: str,
        now: datetime.datetime,
        consolidate: bool,
    ) -> HistoricalMemorySamplingReport:
        """Sample Stage 1 time only; leases/budgets/attempts use real DB ownership."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Historical sampling requires an aware timestamp.")
        now = now.astimezone(datetime.UTC)
        prepared = HistoricalMemoryPreparationSummary(0, 0, 0, 0, 0)
        due = published = unclaimed = failed = 0
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
            if consolidate:
                keys = await ConsolidationDiscoveryRepository(
                    self.session_manager
                ).list_due(agent_id=agent_id, limit=25)
                due = len(keys)
                for key in keys:
                    try:
                        outcome = await self.consolidation.run_unit(key)
                    except ConsolidationOutputError:
                        # Host-authored validation is a domain failed-attempt result,
                        # not a successful publication or an unexpected-error skip.
                        failed += 1
                    else:
                        if outcome is None:
                            unclaimed += 1
                        else:
                            published += 1
        return HistoricalMemorySamplingReport(
            now,
            admission.admitted,
            len(admission.due_agent_ids),
            prepared.attempted,
            prepared.prepared,
            prepared.empty,
            prepared.failed,
            prepared.quota_advanced,
            due,
            published,
            unclaimed,
            failed,
        )
