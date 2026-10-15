"""Canonical public Browser identity and Session visibility boundary tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import NamedTuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from azents.core.agent_session_data import AgentSession, SessionAgent
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
    AgentType,
    WorkspaceUserRole,
)
from azents.rdb.session_capabilities import ReadSession
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.runtime_browser_authority_read import (
    RuntimeBrowserAuthorityReadRepository,
    RuntimeBrowserDurableSnapshot,
    RuntimeBrowserIdentityDenied,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.session import SessionRepository
from azents.repos.user import UserRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository

_NOW = datetime(2026, 10, 15, tzinfo=UTC)


class _Harness(NamedTuple):
    repository: RuntimeBrowserAuthorityReadRepository
    users: AsyncMock
    authentication: AsyncMock
    workspaces: AsyncMock
    members: AsyncMock
    agents: AsyncMock
    admins: AsyncMock
    sessions: AsyncMock
    runtimes: AsyncMock
    profiles: AsyncMock
    transaction_exited: list[bool]


def _agent_session() -> AgentSession:
    return AgentSession.model_construct(
        id="session-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        status=AgentSessionStatus.ACTIVE,
        session_kind=AgentSessionKind.ROOT,
        product_mode=AgentSessionProductMode.USER,
        associated_user_id="user-a",
    )


def _harness() -> _Harness:
    exited: list[bool] = []

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[ReadSession]:
        try:
            yield AsyncMock()
        finally:
            exited.append(True)

    users = AsyncMock(spec=UserRepository)
    users.get.return_value = SimpleNamespace(access_disabled_at=None)
    authentication = AsyncMock(spec=SessionRepository)
    authentication.get.return_value = SimpleNamespace(
        user_id="user-a", revoked_at=None, expires_at=_NOW + timedelta(hours=1)
    )
    workspaces = AsyncMock(spec=WorkspaceRepository)
    workspaces.get_with_id_by_handle.return_value = SimpleNamespace(
        workspace_id="workspace-1"
    )
    members = AsyncMock(spec=WorkspaceUserRepository)
    members.get_by_workspace_and_user.return_value = SimpleNamespace(
        id="member-a", role=WorkspaceUserRole.MEMBER
    )
    agents = AsyncMock(spec=AgentRepository)
    agents.get_by_id.return_value = Agent.model_construct(
        id="agent-1",
        workspace_id="workspace-1",
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
        type=AgentType.PUBLIC,
    )
    admins = AsyncMock(spec=AgentAdminRepository)
    admins.is_admin.return_value = False
    sessions = AsyncMock(spec=AgentSessionRepository)
    sessions.get_by_id.return_value = _agent_session()
    runtimes = AsyncMock(spec=AgentRuntimeRepository)
    runtimes.get_by_agent_id.return_value = AgentRuntime.model_construct(id="runtime-1")
    profiles = AsyncMock(spec=RuntimeProfileRepository)
    profiles.get_configuration_state.return_value = None
    repository = RuntimeBrowserAuthorityReadRepository(
        session_manager=MagicMock(side_effect=session_manager),
        user_repository=users,
        authentication_session_repository=authentication,
        workspace_repository=workspaces,
        workspace_user_repository=members,
        agent_repository=agents,
        agent_admin_repository=admins,
        agent_session_repository=sessions,
        runtime_repository=runtimes,
        profile_repository=profiles,
    )
    return _Harness(
        repository,
        users,
        authentication,
        workspaces,
        members,
        agents,
        admins,
        sessions,
        runtimes,
        profiles,
        exited,
    )


async def _read(
    h: _Harness,
) -> RuntimeBrowserDurableSnapshot | RuntimeBrowserIdentityDenied:
    return await h.repository.read_snapshot(
        user_id="user-a",
        authentication_session_id="auth-a",
        workspace_handle="workspace",
        agent_id="agent-1",
        session_id="session-1",
        resolved_at=_NOW,
    )


async def test_valid_user_session_snapshot_finishes_database_transaction() -> None:
    h = _harness()
    snapshot = await _read(h)
    assert isinstance(snapshot, RuntimeBrowserDurableSnapshot)
    assert snapshot.agent_session.associated_user_id == "user-a"
    assert h.transaction_exited == [True]
    h.runtimes.get_by_agent_id.assert_awaited_once()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_user",
        "disabled_user",
        "missing_auth",
        "other_auth_owner",
        "revoked_auth",
        "expired_auth",
    ],
)
async def test_active_account_and_exact_authentication_session_required(
    mutation: str,
) -> None:
    h = _harness()
    if mutation == "missing_user":
        h.users.get.return_value = None
    elif mutation == "disabled_user":
        h.users.get.return_value = SimpleNamespace(access_disabled_at=_NOW)
    elif mutation == "missing_auth":
        h.authentication.get.return_value = None
    else:
        h.authentication.get.return_value = SimpleNamespace(
            user_id="user-b" if mutation == "other_auth_owner" else "user-a",
            revoked_at=_NOW if mutation == "revoked_auth" else None,
            expires_at=_NOW
            if mutation == "expired_auth"
            else _NOW + timedelta(hours=1),
        )
    assert await _read(h) == RuntimeBrowserIdentityDenied("unauthenticated")
    h.workspaces.get_with_id_by_handle.assert_not_awaited()
    h.runtimes.get_by_agent_id.assert_not_awaited()


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace_id", "other-workspace"),
        ("agent_id", "other-agent"),
        ("status", AgentSessionStatus.ARCHIVED),
        ("associated_user_id", "user-b"),
    ],
)
async def test_private_user_session_b_and_mismatched_archived_targets_are_not_found(
    field: str, value: str
) -> None:
    h = _harness()
    h.sessions.get_by_id.return_value = _agent_session().model_copy(
        update={field: value}
    )
    assert await _read(h) == RuntimeBrowserIdentityDenied("not_found")
    h.runtimes.get_by_agent_id.assert_not_awaited()


async def test_nonmember_cannot_resolve_runtime_or_any_page_content() -> None:
    h = _harness()
    h.members.get_by_workspace_and_user.return_value = None
    assert await _read(h) == RuntimeBrowserIdentityDenied("access_denied")
    h.sessions.get_by_id.assert_not_awaited()
    h.runtimes.get_by_agent_id.assert_not_awaited()


@pytest.mark.parametrize(
    "root_owner,root_status,expected",
    [
        ("user-a", AgentSessionStatus.ACTIVE, True),
        ("user-b", AgentSessionStatus.ACTIVE, False),
        ("user-a", AgentSessionStatus.ARCHIVED, False),
    ],
)
async def test_subagent_observation_uses_canonical_active_root_visibility(
    root_owner: str, root_status: AgentSessionStatus, expected: bool
) -> None:
    h = _harness()
    child = _agent_session().model_copy(
        update={
            "session_kind": AgentSessionKind.SUBAGENT,
            "product_mode": None,
            "associated_user_id": None,
        }
    )
    root = _agent_session().model_copy(
        update={
            "id": "root-session",
            "associated_user_id": root_owner,
            "status": root_status,
        }
    )
    h.sessions.get_by_id.side_effect = lambda _session, session_id: (
        child if session_id == "session-1" else root
    )
    h.sessions.get_root_session_agent_by_session_id.return_value = (
        SessionAgent.model_construct(agent_session_id="root-session")
    )
    snapshot = await _read(h)
    if expected:
        assert isinstance(snapshot, RuntimeBrowserDurableSnapshot)
        assert snapshot.agent_session.id == "session-1"
    else:
        assert snapshot == RuntimeBrowserIdentityDenied("not_found")
        h.runtimes.get_by_agent_id.assert_not_awaited()


async def test_private_agent_requires_existing_admin_or_owner_access() -> None:
    h = _harness()
    h.agents.get_by_id.return_value = h.agents.get_by_id.return_value.model_copy(
        update={"type": AgentType.PRIVATE}
    )
    assert await _read(h) == RuntimeBrowserIdentityDenied("not_found")
    h.admins.is_admin.assert_awaited_once()
    h.runtimes.get_by_agent_id.assert_not_awaited()
    h.admins.is_admin.return_value = True
    assert isinstance(await _read(h), RuntimeBrowserDurableSnapshot)


async def test_team_root_remains_observable_to_current_workspace_member() -> None:
    h = _harness()
    h.sessions.get_by_id.return_value = _agent_session().model_copy(
        update={
            "product_mode": AgentSessionProductMode.TEAM,
            "associated_user_id": None,
        }
    )
    assert isinstance(await _read(h), RuntimeBrowserDurableSnapshot)


async def test_stream_resource_handle_is_derived_from_current_workspace_relation() -> (
    None
):
    h = _harness()
    h.workspaces.get_by_id.return_value = SimpleNamespace(handle="joined-handle")
    result = await h.repository.read_stream_workspace_handle(
        agent_id="agent-1", session_id="session-1"
    )
    assert result == "joined-handle"
    h.workspaces.get_by_id.assert_awaited_once()
    assert h.transaction_exited == [True]


@pytest.mark.parametrize(
    "updates",
    [
        {"agent_id": "other-agent"},
        {"workspace_id": "other-workspace"},
    ],
)
async def test_stream_handle_lookup_does_not_cross_resource_relations(
    updates: dict[str, str],
) -> None:
    h = _harness()
    h.sessions.get_by_id.return_value = _agent_session().model_copy(update=updates)
    assert (
        await h.repository.read_stream_workspace_handle(
            agent_id="agent-1", session_id="session-1"
        )
        is None
    )
    h.workspaces.get_by_id.assert_not_awaited()
