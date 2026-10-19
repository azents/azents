"""Routine obligations participate in ordinary explicit User Stop settlement."""

import datetime
from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.routine import RoutineScope
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.mailbox_item import RDBMailboxItem
from azents.rdb.session_capabilities import WriteSession
from azents.repos.routine.lifecycle import RoutineLifecycleRepository
from azents.repos.routine.state import RoutineStateRepository


@dataclass(frozen=True)
class RoutineStopRepository:
    """Close attempts in the existing owner-fenced Stop transaction."""

    states: Annotated[RoutineStateRepository, Depends()]

    async def cancel_session(
        self,
        session: WriteSession,
        *,
        session_id: str,
        now: datetime.datetime,
    ) -> None:
        """Preserve definitions, source continuity and already completed work."""
        row = (
            await session.write_session.execute(
                sa.select(
                    RDBAgentSession.workspace_id,
                    RDBAgentSession.agent_id,
                ).where(RDBAgentSession.id == session_id)
            )
        ).one_or_none()
        if row is None:
            return
        scope = RoutineScope(
            workspace_id=row.workspace_id, agent_id=row.agent_id, session_id=session_id
        )
        await self.states.cancel_for_stop(session, scope=scope, now=now)
        await session.write_session.execute(
            sa.delete(RDBMailboxItem).where(
                RoutineLifecycleRepository.input_predicate((session_id,)),
            )
        )
