"""Completed Worker recovery scan with detached broker routing identities."""

import dataclasses
import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionRunState,
    AgentSessionStatus,
)
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.worker_session_data import StuckWorkerSession


class WorkerSessionRecoveryQueryRepository:
    """Read common execution routing without requiring a public profile."""

    async def find_stuck_running(
        self,
        session: ReadSession,
        *,
        stale_threshold: datetime.timedelta,
        limit: int,
    ) -> list[StuckWorkerSession]:
        """Preserve the existing strict heartbeat cutoff and oldest-first limit."""
        cutoff = sa.func.now() - stale_threshold
        result = await session.read_session.execute(
            sa.select(RDBAgentSession.id, RDBAgentSession.agent_id)
            .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
            .where(
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.run_state == AgentSessionRunState.RUNNING,
                RDBAgentSession.run_heartbeat_at < cutoff,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            )
            .order_by(RDBAgentSession.run_heartbeat_at)
            .limit(limit)
        )
        return [StuckWorkerSession(id=row.id, agent_id=row.agent_id) for row in result]


@dataclasses.dataclass(frozen=True)
class WorkerSessionRecoveryOperationRepository:
    """Own the existing threshold/limit/order recovery read transaction."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    query_repository: Annotated[
        WorkerSessionRecoveryQueryRepository,
        Depends(WorkerSessionRecoveryQueryRepository),
    ]

    async def find_stuck_running(
        self, *, stale_threshold: datetime.timedelta, limit: int
    ) -> list[StuckWorkerSession]:
        """Finish the scan before any per-record durable mark or broker send."""
        async with self.session_manager() as session:
            return await self.query_repository.find_stuck_running(
                session, stale_threshold=stale_threshold, limit=limit
            )
