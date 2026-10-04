"""Completed Worker recovery scan with detached broker routing identities."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.worker_session_data import StuckWorkerSession


@dataclasses.dataclass(frozen=True)
class WorkerSessionRecoveryOperationRepository:
    """Own the existing threshold/limit/order recovery read transaction."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]

    async def find_stuck_running(
        self, *, stale_threshold: datetime.timedelta, limit: int
    ) -> list[StuckWorkerSession]:
        """Finish the scan before any per-record durable mark or broker send."""
        async with self.session_manager() as session:
            records = await self.agent_session_repository.find_stuck_running(
                session, stale_threshold=stale_threshold, limit=limit
            )
            return [
                StuckWorkerSession(id=record.id, agent_id=record.agent_id)
                for record in records
            ]
