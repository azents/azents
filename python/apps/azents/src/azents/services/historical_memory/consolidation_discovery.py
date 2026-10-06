"""Route due Memory units into the common Session Worker, without a job host."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.broker.deps import get_broker
from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.historical_memory_consolidation import FreshMemoryAdmission
from azents.repos.historical_memory_consolidation.discovery import (
    ConsolidationDiscoveryRepository,
)
from azents.repos.historical_memory_consolidation.execution import (
    MemoryExecutionRepository,
)
from azents.services.historical_memory.execution_policy import (
    HistoricalMemoryExecutionPolicyService,
)


@dataclasses.dataclass(frozen=True)
class ConsolidationDiscoverySummary:
    consolidation_due_units: int
    consolidation_dispatched: int


@dataclasses.dataclass(frozen=True)
class HistoricalMemoryConsolidationDiscoveryService:
    """Observe domain work and publish routing only after durable admission."""

    discovery: Annotated[
        ConsolidationDiscoveryRepository, Depends(ConsolidationDiscoveryRepository)
    ]
    executions: Annotated[MemoryExecutionRepository, Depends(MemoryExecutionRepository)]
    broker: Annotated[SessionBroker, Depends(get_broker)]
    execution_settings: Annotated[
        HistoricalMemoryExecutionPolicyService,
        Depends(HistoricalMemoryExecutionPolicyService),
    ]

    async def dispatch_pending(self, *, agent_id: str | None) -> int:
        return (await self._dispatch(agent_id=agent_id)).consolidation_dispatched

    async def _dispatch(self, *, agent_id: str | None) -> ConsolidationDiscoverySummary:
        keys = await self.discovery.list_due(agent_id=agent_id, limit=25)
        policy = await self.execution_settings.resolve()
        deadline = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            seconds=policy.timeout_seconds
        )
        dispatched = 0
        for key in keys:
            binding = await self.executions.ensure_execution(
                key,
                admission=FreshMemoryAdmission(
                    deadline_at=deadline, execution_policy=policy
                ),
            )
            if binding is None or binding.accepted is not None:
                continue
            await self.broker.send_message(SessionWakeUp(session_id=binding.session_id))
            dispatched += 1
        return ConsolidationDiscoverySummary(len(keys), dispatched)

    async def discover_once(self) -> ConsolidationDiscoverySummary:
        return await self._dispatch(agent_id=None)
