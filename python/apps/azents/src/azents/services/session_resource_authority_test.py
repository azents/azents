"""Shared public Session resource authority tests."""

import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
    WorkspaceUserRole,
)
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, SessionAgent
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUser
from azents.services.chat import ChatSessionService

from .session_resource_authority import (
    AuthorizedPublicSessionResource,
    PublicSessionResourceDenied,
    PublicSessionResourceNotFound,
    SessionExecutionOwner,
    SessionResourceAuthority,
    accepts_execution_authority,
    accepts_execution_owner,
    authorize_public_session_resource,
)


def _session(
    session_id: str,
    *,
    workspace_id: str = "workspace",
    agent_id: str = "agent",
    kind: AgentSessionKind = AgentSessionKind.ROOT,
    status: AgentSessionStatus = AgentSessionStatus.ACTIVE,
    product_mode: AgentSessionProductMode | None = AgentSessionProductMode.TEAM,
    associated_user_id: str | None = None,
) -> AgentSession:
    now = datetime.datetime.now(datetime.UTC)
    return AgentSession.model_construct(
        id=session_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        handle=session_id,
        session_kind=kind,
        status=status,
        product_mode=product_mode,
        associated_user_id=associated_user_id,
        created_at=now,
        updated_at=now,
    )


def _workspace_user(workspace_id: str, user_id: str) -> WorkspaceUser:
    now = datetime.datetime.now(datetime.UTC)
    return WorkspaceUser(
        id=f"membership-{user_id}",
        workspace_id=workspace_id,
        user_id=user_id,
        name=user_id,
        role=WorkspaceUserRole.MEMBER,
        created_at=now,
        updated_at=now,
    )


def _repositories(
    *,
    sessions: dict[str, AgentSession],
    roots: dict[str, str] | None = None,
    members: set[tuple[str, str]] | None = None,
) -> tuple[AgentSessionRepository, WorkspaceUserRepository]:
    agent_sessions = AsyncMock(spec=AgentSessionRepository)
    agent_sessions.get_by_id.side_effect = lambda _session, session_id: sessions.get(
        session_id
    )
    root_ids = roots or {}
    agent_sessions.get_root_session_agent_by_session_id.side_effect = (
        lambda _session, session_id: (
            SessionAgent.model_construct(agent_session_id=root_ids[session_id])
            if session_id in root_ids
            else None
        )
    )
    workspace_users = AsyncMock(spec=WorkspaceUserRepository)
    membership_keys = members or set()
    workspace_users.get_by_workspace_and_user.side_effect = (
        lambda _session, workspace_id, user_id: (
            _workspace_user(workspace_id, user_id)
            if (workspace_id, user_id) in membership_keys
            else None
        )
    )
    return agent_sessions, workspace_users


async def _authorize(
    agent_session: AgentSession,
    *,
    user_id: str,
    require_active: bool = True,
    denied_as_not_found: bool = False,
    expected_workspace_id: str | None = None,
    expected_agent_id: str | None = None,
    sessions: dict[str, AgentSession] | None = None,
    roots: dict[str, str] | None = None,
    members: set[tuple[str, str]] | None = None,
) -> (
    AuthorizedPublicSessionResource
    | PublicSessionResourceDenied
    | PublicSessionResourceNotFound
):
    agent_sessions, workspace_users = _repositories(
        sessions=sessions or {agent_session.id: agent_session},
        roots=roots,
        members=members,
    )
    session: AsyncSession = AsyncMock(spec=AsyncSession)
    return await authorize_public_session_resource(
        session,
        agent_session=agent_session,
        user_id=user_id,
        require_active=require_active,
        denied_as_not_found=denied_as_not_found,
        expected_workspace_id=expected_workspace_id,
        expected_agent_id=expected_agent_id,
        agent_session_repository=agent_sessions,
        workspace_user_repository=workspace_users,
    )


def _authority(
    *, run_id: str, run_index: int, generation: int = 3
) -> SessionResourceAuthority:
    return SessionResourceAuthority(
        workspace_id="workspace",
        agent_id="agent",
        session_id="session",
        root_session_id="session",
        run_id=run_id,
        run_index=run_index,
        owner_generation=generation,
    )


def test_full_authority_refreshes_across_runs_for_same_session_owner() -> None:
    """Run-specific authority may refresh while durable ownership stays unchanged."""
    first = _authority(run_id="run-1", run_index=1)
    second = _authority(run_id="run-2", run_index=2)

    assert accepts_execution_authority(
        None,
        first,
        agent_id="agent",
        session_id="session",
    )
    assert accepts_execution_authority(
        first,
        second,
        agent_id="agent",
        session_id="session",
    )
    assert not accepts_execution_authority(
        second,
        second,
        agent_id="agent",
        session_id="session",
    )


def test_execution_owner_rejects_takeover_on_reused_toolkit() -> None:
    """A Toolkit instance cannot cross a durable owner-generation boundary."""
    current = SessionExecutionOwner(session_id="session", owner_generation=3)

    assert accepts_execution_owner(None, current, session_id="session")
    assert not accepts_execution_owner(current, current, session_id="session")
    with pytest.raises(ValueError, match="another execution owner"):
        accepts_execution_owner(
            current,
            SessionExecutionOwner(session_id="session", owner_generation=4),
            session_id="session",
        )


def test_full_authority_rejects_identity_mismatch() -> None:
    """Full resource binding validates captured Agent and Session identity."""
    authority = _authority(run_id="run-1", run_index=1)

    with pytest.raises(ValueError, match="Agent"):
        accepts_execution_authority(
            None,
            authority,
            agent_id="other-agent",
            session_id="session",
        )
    with pytest.raises(ValueError, match="Session"):
        accepts_execution_authority(
            None,
            authority,
            agent_id="agent",
            session_id="other-session",
        )


class TestPublicSessionResourceAuthority:
    """Verify Chat-compatible Team, User, and subagent authorization."""

    async def test_team_membership_and_not_found_safe_denial(self) -> None:
        root = _session("team-root")
        authorized = await _authorize(
            root,
            user_id="member",
            members={("workspace", "member")},
        )
        disclosed = await _authorize(root, user_id="outsider")
        hidden = await _authorize(
            root,
            user_id="outsider",
            denied_as_not_found=True,
        )

        assert isinstance(authorized, AuthorizedPublicSessionResource)
        assert authorized.session is root
        assert authorized.root_session is root
        assert isinstance(disclosed, PublicSessionResourceDenied)
        assert isinstance(hidden, PublicSessionResourceNotFound)

    async def test_user_session_is_owner_only_and_always_not_found_safe(self) -> None:
        root = _session(
            "user-root",
            product_mode=AgentSessionProductMode.USER,
            associated_user_id="owner",
        )
        owner = await _authorize(
            root,
            user_id="owner",
            members={("workspace", "owner"), ("workspace", "other")},
        )
        other_member = await _authorize(
            root,
            user_id="other",
            members={("workspace", "owner"), ("workspace", "other")},
        )
        outsider = await _authorize(root, user_id="outsider")

        assert isinstance(owner, AuthorizedPublicSessionResource)
        assert isinstance(other_member, PublicSessionResourceNotFound)
        assert isinstance(outsider, PublicSessionResourceNotFound)

    async def test_subagent_keeps_concrete_identity_and_uses_root_permission(
        self,
    ) -> None:
        root = _session("root")
        child = _session(
            "child",
            kind=AgentSessionKind.SUBAGENT,
            product_mode=None,
        )
        authorized = await _authorize(
            child,
            user_id="member",
            sessions={root.id: root, child.id: child},
            roots={child.id: root.id},
            members={("workspace", "member")},
        )

        assert isinstance(authorized, AuthorizedPublicSessionResource)
        assert authorized.session is child
        assert authorized.root_session is root

    @pytest.mark.parametrize(
        ("expected_workspace_id", "expected_agent_id"),
        [("other-workspace", "agent"), ("workspace", "other-agent")],
    )
    async def test_expected_workspace_and_agent_mismatch_are_not_found(
        self,
        expected_workspace_id: str,
        expected_agent_id: str,
    ) -> None:
        result = await _authorize(
            _session("root"),
            user_id="member",
            expected_workspace_id=expected_workspace_id,
            expected_agent_id=expected_agent_id,
            members={("workspace", "member")},
        )

        assert isinstance(result, PublicSessionResourceNotFound)

    async def test_chat_preserves_archived_session_authorization(self) -> None:
        archived = _session("archived", status=AgentSessionStatus.ARCHIVED)
        agent_sessions, workspace_users = _repositories(
            sessions={archived.id: archived},
            members={("workspace", "member")},
        )
        chat = ChatSessionService.__new__(ChatSessionService)
        chat.agent_session_repository = agent_sessions
        chat.workspace_user_repository = workspace_users
        session: AsyncSession = AsyncMock(spec=AsyncSession)

        result = await chat._authorize_public_session(
            session,
            agent_session=archived,
            user_id="member",
            denied_as_not_found=True,
        )
        runtime_active_only = await _authorize(
            archived,
            user_id="member",
            require_active=True,
            members={("workspace", "member")},
        )

        assert result is None
        assert isinstance(runtime_active_only, PublicSessionResourceNotFound)
