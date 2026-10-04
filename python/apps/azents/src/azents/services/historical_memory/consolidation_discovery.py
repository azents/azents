"""Coalesced exact-unit dispatch and periodic private-payload reconciliation."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.job_runtime.deps import get_job_runtime
from azents.job_runtime.types import JobRequest, JobRuntime
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.cleanup import (
    ConsolidationCleanupRepository,
)
from azents.repos.historical_memory_consolidation.discovery import (
    ConsolidationDiscoveryRepository,
)
from azents.services.historical_memory.constants import (
    HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY,
)


@dataclasses.dataclass(frozen=True)
class ConsolidationDiscoverySummary:
    consolidation_due_units: int
    consolidation_dispatched: int
    consolidation_cleanup_drafts: int
    consolidation_expired_owners: int
    consolidation_cleanup_revisions: int


@dataclasses.dataclass
class HistoricalMemoryConsolidationDiscoveryService:
    """Five-minute recovery plus event-driven post-commit work continuation."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    job_runtime: Annotated[JobRuntime, Depends(get_job_runtime)]

    async def dispatch_pending(self, *, agent_id: str | None) -> int:
        keys = await ConsolidationDiscoveryRepository(self.session_manager).list_due(
            agent_id=agent_id, limit=25
        )
        deadline = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10)
        for key in keys:
            scope_owner = (
                "team" if key.associated_user_id is None else key.associated_user_id
            )
            await self.job_runtime.submit(
                JobRequest(
                    handler_key=HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY,
                    execution_key=f"historical-consolidation:{key.workspace_id}:{key.agent_id}:{key.scope.value}:{scope_owner}",
                    deadline=deadline,
                    payload={"unit": key.model_dump(mode="json")},
                )
            )
        return len(keys)

    async def discover_once(self) -> ConsolidationDiscoverySummary:
        cleanup = await ConsolidationCleanupRepository(self.session_manager).sweep(
            limit=50
        )
        revisions = await ConsolidationCleanupRepository(
            self.session_manager
        ).collect_revisions(limit=50)
        dispatched = await self.dispatch_pending(agent_id=None)
        return ConsolidationDiscoverySummary(
            dispatched, dispatched, cleanup.drafts, cleanup.expired_owners, revisions
        )
