"""Workspace upload authorization repository operation tests."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import NamedTuple

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentLifecycleStatus, AgentType, WorkspaceUserRole
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.workspace_upload_authority.data import (
    WorkspaceUploadRequesterAccessDenied,
    WorkspaceUploadRequesterAgentUnavailable,
)
from azents.repos.workspace_upload_authority.operations import (
    WorkspaceUploadAuthorizationRepository,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUser

_AGENT_ID = "0123456789abcdef0123456789abcdef"
_WORKSPACE_ID = "workspace-1"
_USER_ID = "user-1"


class _SessionManager:
    """Provide one session-shaped value for repository doubles."""

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[AsyncSession]:
        yield AsyncSession()


class _AgentRepository(AgentRepository):
    """Return one configurable Agent."""

    def __init__(self, agent: Agent | None) -> None:
        self.agent = agent

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> Agent | None:
        """Return the configured Agent for its exact ID."""
        del session
        if self.agent is None or self.agent.id != agent_id:
            return None
        return self.agent


class _WorkspaceUserRepository(WorkspaceUserRepository):
    """Return one configurable Workspace membership."""

    def __init__(self, membership: WorkspaceUser | None) -> None:
        self.membership = membership

    async def get_by_workspace_and_user(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceUser | None:
        """Return membership only for its exact Workspace and user."""
        del session
        membership = self.membership
        if (
            membership is not None
            and membership.workspace_id == workspace_id
            and membership.user_id == user_id
        ):
            return membership
        return None


class _AgentAdminRepository(AgentAdminRepository):
    """Return one configurable private-Agent admin decision."""

    def __init__(self, admin: bool) -> None:
        self.admin = admin
        self.calls: list[tuple[str, str]] = []

    async def is_admin(
        self,
        session: AsyncSession,
        agent_id: str,
        workspace_user_id: str,
    ) -> bool:
        """Record and return the configured admin decision."""
        del session
        self.calls.append((agent_id, workspace_user_id))
        return self.admin


def _agent(
    *,
    agent_type: AgentType = AgentType.PUBLIC,
    lifecycle_status: AgentLifecycleStatus = AgentLifecycleStatus.ACTIVE,
) -> Agent:
    """Build one Agent authorization projection."""
    return Agent.model_construct(
        id=_AGENT_ID,
        workspace_id=_WORKSPACE_ID,
        lifecycle_status=lifecycle_status,
        type=agent_type,
    )


def _membership(*, role: WorkspaceUserRole) -> WorkspaceUser:
    """Build one Workspace membership projection."""
    return WorkspaceUser.model_construct(
        id="workspace-user-1",
        workspace_id=_WORKSPACE_ID,
        user_id=_USER_ID,
        role=role,
    )


class _RepositoryDependencies(NamedTuple):
    """Authorization repository and observable admin dependency."""

    repository: WorkspaceUploadAuthorizationRepository
    admin_repository: _AgentAdminRepository


def _repository(
    *,
    agent: Agent | None,
    membership: WorkspaceUser | None,
    admin: bool,
) -> _RepositoryDependencies:
    """Build the operation repository and observable admin dependency."""
    admin_repository = _AgentAdminRepository(admin)
    return _RepositoryDependencies(
        repository=WorkspaceUploadAuthorizationRepository(
            agent_repository=_AgentRepository(agent),
            agent_admin_repository=admin_repository,
            workspace_user_repository=_WorkspaceUserRepository(membership),
            session_manager=_SessionManager(),
        ),
        admin_repository=admin_repository,
    )


@pytest.mark.asyncio
async def test_authorize_rejects_unavailable_agent() -> None:
    """Missing and inactive Agents are unavailable."""
    for agent in (
        None,
        _agent(lifecycle_status=AgentLifecycleStatus.DECOMMISSIONING),
    ):
        repository, _ = _repository(
            agent=agent,
            membership=_membership(role=WorkspaceUserRole.OWNER),
            admin=False,
        )

        result = await repository.authorize(agent_id=_AGENT_ID, user_id=_USER_ID)

        assert isinstance(result, Failure)
        assert isinstance(result.error, WorkspaceUploadRequesterAgentUnavailable)


@pytest.mark.asyncio
async def test_authorize_rejects_missing_membership() -> None:
    """Workspace membership is required."""
    repository, _ = _repository(agent=_agent(), membership=None, admin=False)

    result = await repository.authorize(agent_id=_AGENT_ID, user_id=_USER_ID)

    assert isinstance(result, Failure)
    assert isinstance(result.error, WorkspaceUploadRequesterAccessDenied)


@pytest.mark.asyncio
async def test_authorize_accepts_public_agent_member() -> None:
    """Public Agents accept any current Workspace member."""
    repository, admin_repository = _repository(
        agent=_agent(),
        membership=_membership(role=WorkspaceUserRole.MEMBER),
        admin=False,
    )

    result = await repository.authorize(agent_id=_AGENT_ID, user_id=_USER_ID)

    assert isinstance(result, Success)
    assert result.value.agent.id == _AGENT_ID
    assert result.value.workspace_user_id == "workspace-user-1"
    assert result.value.role is WorkspaceUserRole.MEMBER
    assert admin_repository.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "admin", "allowed"),
    [
        (WorkspaceUserRole.OWNER, False, True),
        (WorkspaceUserRole.MEMBER, True, True),
        (WorkspaceUserRole.MEMBER, False, False),
    ],
)
async def test_authorize_private_agent_authority(
    role: WorkspaceUserRole,
    admin: bool,
    allowed: bool,
) -> None:
    """Private Agents require Owner or explicit Agent administration."""
    repository, admin_repository = _repository(
        agent=_agent(agent_type=AgentType.PRIVATE),
        membership=_membership(role=role),
        admin=admin,
    )

    result = await repository.authorize(agent_id=_AGENT_ID, user_id=_USER_ID)

    if allowed:
        assert isinstance(result, Success)
        assert result.value.role is role
    else:
        assert isinstance(result, Failure)
        assert isinstance(result.error, WorkspaceUploadRequesterAccessDenied)
    expected_calls = (
        [] if role is WorkspaceUserRole.OWNER else [(_AGENT_ID, "workspace-user-1")]
    )
    assert admin_repository.calls == expected_calls
