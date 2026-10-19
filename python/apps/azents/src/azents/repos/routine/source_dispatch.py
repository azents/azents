"""Read-only Routine checking opportunities and their next shared-Scheduler time."""

import datetime
from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.enums import AgentLifecycleStatus, AgentSessionStatus, SessionAgentKind
from azents.core.routine import (
    RoutineScope,
)
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.routine import RDBRoutine
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.routine.state import ROUTINE_CHECK_STATE_NAME, ROUTINE_STATE_NAMESPACE


def _checking_opportunities(
    now: datetime.datetime,
) -> sa.Select[tuple[str, str, str, datetime.datetime]]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Routine source time must be timezone-aware.")
    last_tick = RDBToolkitState.state_json["last_tick_at"].astext.cast(
        sa.DateTime(timezone=True)
    )
    last_action = RDBToolkitState.state_json["last_action_at"].astext.cast(
        sa.DateTime(timezone=True)
    )
    due_at = sa.func.coalesce(
        sa.func.greatest(
            last_tick
            + RDBAgent.routine_check_interval_minutes * datetime.timedelta(minutes=1),
            last_action
            + RDBAgent.routine_min_action_delay_minutes * datetime.timedelta(minutes=1),
        ),
        now,
        type_=sa.DateTime(timezone=True),
    ).label("due_at")
    definitions = sa.exists(
        sa.select(RDBRoutine.id).where(
            RDBRoutine.session_id == RDBAgentSession.id,
            RDBRoutine.agent_id == RDBAgentSession.agent_id,
            RDBRoutine.workspace_id == RDBAgentSession.workspace_id,
        )
    )
    return (
        sa.select(
            RDBAgentSession.workspace_id,
            RDBAgentSession.agent_id,
            RDBAgentSession.id,
            due_at,
        )
        .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
        .join(RDBSessionAgent, RDBSessionAgent.agent_session_id == RDBAgentSession.id)
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
        )
    )


@dataclass(frozen=True)
class RoutineSourceRepository:
    """Read due roots; ordinary inbox composition owns all admission writes."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def list_due_scopes(
        self, *, now: datetime.datetime, limit: int
    ) -> list[RoutineScope]:
        """Read a bounded due batch using the same clock as next-time selection."""
        if limit < 1:
            raise ValueError("Routine source batch limit must be positive.")
        opportunities = _checking_opportunities(now).subquery()
        async with self.session_manager() as session:
            rows = await session.read_session.execute(
                sa.select(
                    opportunities.c.workspace_id,
                    opportunities.c.agent_id,
                    opportunities.c.id,
                )
                .where(opportunities.c.due_at <= now)
                .order_by(opportunities.c.due_at, opportunities.c.id)
                .limit(limit)
            )
            return [
                RoutineScope(
                    workspace_id=workspace_id, agent_id=agent_id, session_id=session_id
                )
                for workspace_id, agent_id, session_id in rows
            ]

    async def next_check_at(
        self, *, now: datetime.datetime
    ) -> datetime.datetime | None:
        """Return the earliest eligible Session time without creating a timer."""
        opportunities = _checking_opportunities(now).subquery()
        async with self.session_manager() as session:
            return await session.read_session.scalar(
                sa.select(sa.func.min(opportunities.c.due_at))
            )
