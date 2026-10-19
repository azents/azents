"""Shared Routine Session authority observations and database mutation fences."""

import sqlalchemy as sa

from azents.core.enums import AgentLifecycleStatus, AgentSessionStatus
from azents.core.routine import RoutineScope, RoutineUnavailable
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.session_execution.ownership import fence_owned_session_mutation


async def require_routine_scope(session: ReadSession, *, scope: RoutineScope) -> None:
    """Fail closed for a wrong Workspace, Agent, or inactive Session."""
    found = await session.read_session.scalar(
        sa.select(RDBAgentSession.id)
        .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
        .where(
            RDBAgentSession.id == scope.session_id,
            RDBAgentSession.agent_id == scope.agent_id,
            RDBAgentSession.workspace_id == scope.workspace_id,
            RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            RDBAgent.workspace_id == scope.workspace_id,
            RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
        )
    )
    if found is None:
        raise RoutineUnavailable("Routine Session is not active or authorized.")


async def fence_routine_scope(
    session: WriteSession,
    *,
    scope: RoutineScope,
    owner: SessionExecutionOwner | None,
) -> None:
    """Preserve Agent-to-Session ordering and fence the actual mutation."""
    if owner is not None and owner.session_id != scope.session_id:
        raise RoutineUnavailable("Routine execution owner does not match Session.")
    agent = await session.write_session.scalar(
        sa.select(RDBAgent.id)
        .where(
            RDBAgent.id == scope.agent_id,
            RDBAgent.workspace_id == scope.workspace_id,
            RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
        )
        .with_for_update(read=True, key_share=True)
    )
    if agent is None:
        raise RoutineUnavailable("Routine Agent is not active or authorized.")
    target = await session.write_session.scalar(
        sa.select(RDBAgentSession.id)
        .where(
            RDBAgentSession.id == scope.session_id,
            RDBAgentSession.agent_id == scope.agent_id,
            RDBAgentSession.workspace_id == scope.workspace_id,
            RDBAgentSession.status == AgentSessionStatus.ACTIVE,
        )
        .with_for_update()
    )
    if target is None:
        raise RoutineUnavailable("Routine Session is not active or authorized.")
    if owner is not None:
        await fence_owned_session_mutation(session, owner)
