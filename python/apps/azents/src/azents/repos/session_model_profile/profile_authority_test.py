"""Blocking model-profile authorization after dormant NOWAIT removal."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent_session_data import AgentSession, SessionAgent
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
)
from azents.rdb.session_capabilities import ReadWriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_model_profile.repository import SessionModelProfileRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUser


@pytest.mark.parametrize("denied", [None, "subagent", "private", "agent", "membership"])
async def test_writable_root_retains_blocking_locks_and_authority(
    denied: str | None,
) -> None:
    """The remaining path preserves root, private-user and membership checks."""
    current = AgentSession.model_construct(
        id="session",
        agent_id="agent",
        workspace_id="workspace",
        session_kind=(
            AgentSessionKind.SUBAGENT if denied == "subagent" else AgentSessionKind.ROOT
        ),
        status=AgentSessionStatus.ACTIVE,
        product_mode=AgentSessionProductMode.USER,
        associated_user_id="other" if denied == "private" else "user",
    )
    agents = AsyncMock(spec=AgentRepository)
    agents.lock_by_id.return_value = Agent.model_construct(
        lifecycle_status=(
            AgentLifecycleStatus.DECOMMISSIONING
            if denied == "agent"
            else AgentLifecycleStatus.ACTIVE
        ),
        workspace_id="workspace",
    )
    sessions = AsyncMock(spec=AgentSessionRepository)
    sessions.lock_by_id.return_value = current
    sessions.get_root_session_agent_by_session_id.return_value = (
        SessionAgent.model_construct(agent_session_id="session")
    )
    memberships = AsyncMock(spec=WorkspaceUserRepository)
    memberships.get_by_workspace_and_user.return_value = (
        None
        if denied == "membership"
        else WorkspaceUser.model_construct(
            id="membership", workspace_id="workspace", user_id="user"
        )
    )
    repository = SessionModelProfileRepository(
        agents, sessions, memberships, AsyncMock(), AsyncMock(), AsyncMock()
    )
    async with AsyncSession() as raw:
        scope = ReadWriteSession(raw)
        if denied is None:
            assert (
                await repository.lock_writable_root(
                    scope, agent_id="agent", session_id="session", user_id="user"
                )
                is current
            )
        else:
            expected = {
                "subagent": "Subagent sessions are read-only",
                "private": "Requester does not have session access",
                "agent": "AgentSession is not active",
                "membership": "Requester does not have session access",
            }
            with pytest.raises(ValueError, match=expected[denied]):
                await repository.lock_writable_root(
                    scope, agent_id="agent", session_id="session", user_id="user"
                )
        sessions.lock_by_id.assert_awaited_once_with(scope, "session")
        if denied in {"subagent", "private"}:
            agents.lock_by_id.assert_not_awaited()
        else:
            agents.lock_by_id.assert_awaited_once_with(scope, "agent")
