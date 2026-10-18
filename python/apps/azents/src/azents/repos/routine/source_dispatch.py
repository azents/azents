"""Bounded read-only selection of Session Routine source-check opportunities."""

import datetime
from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.enums import AgentLifecycleStatus, AgentSessionStatus, SessionAgentKind
from azents.core.routine import ROUTINE_TICK_INTERVAL, RoutineScope
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.routine import RDBRoutine
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.routine.state import ROUTINE_CHECK_STATE_NAME, ROUTINE_STATE_NAMESPACE


@dataclass(frozen=True)
class RoutineSourceRepository:
    """Find due roots; the ordinary inbox composition owns all admission writes."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def list_due_scopes(
        self, *, now: datetime.datetime, limit: int
    ) -> list[RoutineScope]:
        """Read a bounded due batch ordered by oldest checking opportunity."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Routine source time must be timezone-aware.")
        if limit < 1:
            raise ValueError("Routine source batch limit must be positive.")
        last_tick = RDBToolkitState.state_json["last_tick_at"].astext.cast(
            sa.DateTime(timezone=True)
        )
        definitions = sa.exists(
            sa.select(RDBRoutine.id).where(
                RDBRoutine.session_id == RDBAgentSession.id,
                RDBRoutine.agent_id == RDBAgentSession.agent_id,
                RDBRoutine.workspace_id == RDBAgentSession.workspace_id,
            )
        )
        async with self.session_manager() as session:
            rows = await session.read_session.execute(
                sa.select(
                    RDBAgentSession.workspace_id,
                    RDBAgentSession.agent_id,
                    RDBAgentSession.id,
                )
                .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
                .join(
                    RDBSessionAgent,
                    RDBSessionAgent.agent_session_id == RDBAgentSession.id,
                )
                .outerjoin(
                    RDBToolkitState,
                    sa.and_(
                        RDBToolkitState.agent_id == RDBAgentSession.agent_id,
                        RDBToolkitState.session_id == RDBAgentSession.id,
                        RDBToolkitState.toolkit_namespace == ROUTINE_STATE_NAMESPACE,
                        RDBToolkitState.state_name == ROUTINE_CHECK_STATE_NAME,
                    ),
                )
                .where(
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgentSession.stop_requested_at.is_(None),
                    RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                    RDBAgent.workspace_id == RDBAgentSession.workspace_id,
                    RDBSessionAgent.kind == SessionAgentKind.ROOT,
                    definitions,
                    sa.or_(
                        last_tick.is_(None), last_tick <= now - ROUTINE_TICK_INTERVAL
                    ),
                )
                .order_by(last_tick.asc().nulls_first(), RDBAgentSession.id)
                .limit(limit)
            )
            return [
                RoutineScope(
                    workspace_id=workspace_id, agent_id=agent_id, session_id=session_id
                )
                for workspace_id, agent_id, session_id in rows
            ]
