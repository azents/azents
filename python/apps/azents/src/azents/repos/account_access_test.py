"""Real PostgreSQL admission reads and completed-lifetime regressions."""

import asyncio
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from azcommon.result import Success
from azcommon.uuid import uuid7

from azents.core.account_access import ActiveAccountSubjectStatus
from azents.core.enums import WorkspaceUserRole
from azents.core.workspace import WorkspaceCreate
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.account_access import AccountAccessOperationRepository
from azents.repos.session import SessionRepository
from azents.repos.session.data import Session, SessionCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import User, UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUser, WorkspaceUserCreate
from azents.services.account_access import AccountAccessService


class RecordedReadScope:
    """Track the actual PostgreSQL session until its infrastructure scope closes."""

    def __init__(self, session_manager: SessionManager[WriteSession]) -> None:
        self.session_manager = session_manager
        self.active_scopes = 0
        self.completed_reads = 0
        self.aborted_reads = 0
        self.sessions: list[ReadSession] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        """Delegate the actual commit/rollback/close boundary without callbacks."""
        self.active_scopes += 1
        try:
            async with self.session_manager() as session:
                self.sessions.append(session)
                yield session
        except asyncio.CancelledError:
            self.aborted_reads += 1
            raise
        except Exception:
            self.aborted_reads += 1
            raise
        else:
            self.completed_reads += 1
        finally:
            self.active_scopes -= 1

    def assert_closed(self) -> None:
        """Require no active admission transaction after detached return."""
        assert self.active_scopes == 0
        assert all(
            not session.read_session.in_transaction() for session in self.sessions
        )


class RecordedUserRepository(UserRepository):
    """Record real User query sessions, including disabled/missing subjects."""

    def __init__(self) -> None:
        self.read_sessions: list[ReadSession] = []

    async def get(self, session: ReadSession, user_id: str) -> User | None:
        """Perform the retained narrow User read using the composing session."""
        self.read_sessions.append(session)
        return await super().get(session, user_id)


class RecordedSessionRepository(SessionRepository):
    """Record exact Session reads and injected DB failures after real queries."""

    def __init__(self) -> None:
        self.read_sessions: list[ReadSession] = []
        self.failure: BaseException | None = None

    async def get(self, session: ReadSession, session_id: str) -> Session | None:
        """Keep the actual Session query rather than an application callback."""
        self.read_sessions.append(session)
        result = await super().get(session, session_id)
        if self.failure is not None:
            raise self.failure
        return result


class RecordedWorkspaceRepository(WorkspaceRepository):
    """Record real handle resolution sessions."""

    def __init__(self) -> None:
        self.read_sessions: list[ReadSession] = []

    async def resolve_id(self, session: ReadSession, handle: str) -> str | None:
        """Resolve the handle in the same completed membership read."""
        self.read_sessions.append(session)
        return await super().resolve_id(session, handle)


class RecordedMembershipRepository(WorkspaceUserRepository):
    """Record real membership reads and their narrow database failure boundary."""

    def __init__(self) -> None:
        self.read_sessions: list[ReadSession] = []
        self.failure: BaseException | None = None

    async def get_by_workspace_and_user(
        self,
        session: ReadSession,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceUser | None:
        """Return current persisted role authority without any HTTP dependency."""
        self.read_sessions.append(session)
        result = await super().get_by_workspace_and_user(session, workspace_id, user_id)
        if self.failure is not None:
            raise self.failure
        return result


@dataclass(frozen=True)
class AccessFixture:
    """Named access-service and query dependencies for real database tests."""

    service: AccountAccessService
    repository: AccountAccessOperationRepository
    scope: RecordedReadScope
    users: RecordedUserRepository
    sessions: RecordedSessionRepository
    workspaces: RecordedWorkspaceRepository
    members: RecordedMembershipRepository


def access_fixture(session_manager: SessionManager[WriteSession]) -> AccessFixture:
    """Build completed access operations with real PostgreSQL query primitives."""
    scope = RecordedReadScope(session_manager)
    users = RecordedUserRepository()
    sessions = RecordedSessionRepository()
    workspaces = RecordedWorkspaceRepository()
    members = RecordedMembershipRepository()
    repository = AccountAccessOperationRepository(
        session_manager=scope,
        user_repository=users,
        session_repository=sessions,
        workspace_repository=workspaces,
        workspace_user_repository=members,
    )
    return AccessFixture(
        service=AccountAccessService(repository=repository),
        repository=repository,
        scope=scope,
        users=users,
        sessions=sessions,
        workspaces=workspaces,
        members=members,
    )


@dataclass(frozen=True)
class SubjectIdentity:
    """Exact subject IDs used by valid signed JWTs and database admission."""

    user_id: str
    session_id: str


async def seed_subject(
    session_manager: SessionManager[WriteSession],
    status: ActiveAccountSubjectStatus,
) -> SubjectIdentity:
    """Create isolated authoritative state for every existing rejection condition."""
    if status is ActiveAccountSubjectStatus.USER_MISSING:
        return SubjectIdentity(user_id="0" * 32, session_id="0" * 32)
    async with session_manager() as session:
        users = UserRepository()
        sessions = SessionRepository()
        user = await users.create(
            session, UserCreate(email=f"access-{uuid7().hex}@example.com")
        )
        if status is ActiveAccountSubjectStatus.SESSION_MISSING:
            return SubjectIdentity(user_id=user.id, session_id="0" * 32)
        session_user_id = user.id
        if status is ActiveAccountSubjectStatus.SESSION_FOREIGN:
            other = await users.create(
                session, UserCreate(email=f"foreign-{uuid7().hex}@example.com")
            )
            session_user_id = other.id
        now = datetime.datetime.now(datetime.UTC)
        expires_at = now + datetime.timedelta(hours=1)
        if status is ActiveAccountSubjectStatus.SESSION_EXPIRED:
            expires_at = now - datetime.timedelta(hours=1)
        auth_session = await sessions.create(
            session,
            SessionCreate(
                user_id=session_user_id,
                refresh_token=f"test-{uuid7().hex}",
                expires_at=expires_at,
            ),
        )
        if status is ActiveAccountSubjectStatus.USER_DISABLED:
            await users.disable_access(session, user.id, disabled_at=now)
        if status is ActiveAccountSubjectStatus.SESSION_REVOKED:
            await sessions.revoke(session, auth_session.id)
        return SubjectIdentity(user_id=user.id, session_id=auth_session.id)


@dataclass(frozen=True)
class WorkspaceIdentity:
    """Resolved handle and membership IDs from direct test setup."""

    handle: str
    workspace_id: str
    workspace_user_id: str | None


async def seed_workspace(
    session_manager: SessionManager[WriteSession],
    *,
    user_id: str,
    role: WorkspaceUserRole | None,
) -> WorkspaceIdentity:
    """Create an ordinary Workspace and optional membership in test infrastructure."""
    handle = f"access-{uuid7().hex}"
    async with session_manager() as session:
        workspaces = WorkspaceRepository()
        created = await workspaces.create(
            session, WorkspaceCreate(name="Access tests", handle=handle)
        )
        assert isinstance(created, Success)
        workspace_id = await workspaces.resolve_id(session, handle)
        assert workspace_id is not None
        membership_id: str | None = None
        if role is not None:
            member = await WorkspaceUserRepository().create(
                session,
                WorkspaceUserCreate(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    name="Test member",
                    role=role,
                ),
            )
            assert isinstance(member, Success)
            membership_id = member.value.id
        return WorkspaceIdentity(
            handle=handle,
            workspace_id=workspace_id,
            workspace_user_id=membership_id,
        )


@pytest.mark.parametrize("status", list(ActiveAccountSubjectStatus))
async def test_exact_subject_status_is_detached_after_one_real_database_read(
    rdb_session_manager: SessionManager[WriteSession],
    status: ActiveAccountSubjectStatus,
) -> None:
    """Retain all current rejection predicates with User-first short circuiting."""
    subject = await seed_subject(rdb_session_manager, status)
    fixture = access_fixture(rdb_session_manager)

    result = await fixture.repository.read_active_subject(
        user_id=subject.user_id,
        session_id=subject.session_id,
    )

    assert result is status
    assert fixture.scope.completed_reads == 1
    fixture.scope.assert_closed()
    assert len(fixture.scope.sessions) == 1
    assert fixture.users.read_sessions == fixture.scope.sessions
    if status in {
        ActiveAccountSubjectStatus.USER_MISSING,
        ActiveAccountSubjectStatus.USER_DISABLED,
    }:
        assert fixture.sessions.read_sessions == []
    else:
        assert fixture.sessions.read_sessions == fixture.scope.sessions


@pytest.mark.parametrize("role", list(WorkspaceUserRole))
async def test_membership_snapshot_returns_the_current_role_after_database_close(
    rdb_session_manager: SessionManager[WriteSession],
    role: WorkspaceUserRole,
) -> None:
    """Handle and membership queries share one read and return only pure authority."""
    subject = await seed_subject(rdb_session_manager, ActiveAccountSubjectStatus.ACTIVE)
    workspace = await seed_workspace(
        rdb_session_manager, user_id=subject.user_id, role=role
    )
    fixture = access_fixture(rdb_session_manager)

    result = await fixture.service.read_workspace_membership(
        handle=workspace.handle, user_id=subject.user_id
    )

    assert result.workspace_id == workspace.workspace_id
    assert result.membership is not None
    assert result.membership.workspace_user_id == workspace.workspace_user_id
    assert result.membership.role is role
    fixture.scope.assert_closed()
    assert fixture.scope.completed_reads == 1
    assert fixture.workspaces.read_sessions == fixture.scope.sessions
    assert fixture.members.read_sessions == fixture.scope.sessions


@pytest.mark.parametrize("workspace_exists", [False, True])
async def test_workspace_and_membership_missing_are_distinct_detached_outcomes(
    rdb_session_manager: SessionManager[WriteSession],
    workspace_exists: bool,
) -> None:
    """Preserve the distinction used by core HTTP 404 and 403 errors."""
    subject = await seed_subject(rdb_session_manager, ActiveAccountSubjectStatus.ACTIVE)
    handle = "missing-workspace"
    if workspace_exists:
        workspace = await seed_workspace(
            rdb_session_manager, user_id=subject.user_id, role=None
        )
        handle = workspace.handle
    fixture = access_fixture(rdb_session_manager)

    result = await fixture.repository.read_workspace_membership(
        handle=handle, user_id=subject.user_id
    )

    assert (result.workspace_id is not None) is workspace_exists
    assert result.membership is None
    fixture.scope.assert_closed()
    assert fixture.scope.completed_reads == 1
    assert fixture.members.read_sessions == (
        fixture.scope.sessions if workspace_exists else []
    )


async def test_session_revocation_is_revalidated_on_each_completed_read(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A previously admitted JWT subject gains no cached Session authority."""
    subject = await seed_subject(rdb_session_manager, ActiveAccountSubjectStatus.ACTIVE)
    fixture = access_fixture(rdb_session_manager)
    assert (
        await fixture.service.read_active_subject(
            user_id=subject.user_id, session_id=subject.session_id
        )
        is ActiveAccountSubjectStatus.ACTIVE
    )
    fixture.scope.assert_closed()
    async with rdb_session_manager() as session:
        await SessionRepository().revoke(session, subject.session_id)

    assert (
        await fixture.service.read_active_subject(
            user_id=subject.user_id, session_id=subject.session_id
        )
        is ActiveAccountSubjectStatus.SESSION_REVOKED
    )
    fixture.scope.assert_closed()
    assert fixture.scope.completed_reads == 2


@pytest.mark.parametrize("cancelled", [False, True])
async def test_subject_read_failure_or_cancellation_closes_real_database_transaction(
    rdb_session_manager: SessionManager[WriteSession],
    cancelled: bool,
) -> None:
    """Propagate a later database-read failure without returning admission success."""
    subject = await seed_subject(rdb_session_manager, ActiveAccountSubjectStatus.ACTIVE)
    fixture = access_fixture(rdb_session_manager)
    fixture.sessions.failure = (
        asyncio.CancelledError() if cancelled else ValueError("session read failed")
    )
    expected = asyncio.CancelledError if cancelled else ValueError

    with pytest.raises(expected):
        await fixture.repository.read_active_subject(
            user_id=subject.user_id, session_id=subject.session_id
        )

    assert fixture.scope.completed_reads == 0
    assert fixture.scope.aborted_reads == 1
    fixture.scope.assert_closed()
    assert fixture.users.read_sessions == fixture.sessions.read_sessions


async def test_membership_read_failure_closes_the_handle_resolution_transaction(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Abandon the whole read if its later membership query fails."""
    subject = await seed_subject(rdb_session_manager, ActiveAccountSubjectStatus.ACTIVE)
    workspace = await seed_workspace(
        rdb_session_manager, user_id=subject.user_id, role=WorkspaceUserRole.MEMBER
    )
    fixture = access_fixture(rdb_session_manager)
    fixture.members.failure = ValueError("membership read failed")

    with pytest.raises(ValueError, match="membership read failed"):
        await fixture.service.read_workspace_membership(
            handle=workspace.handle, user_id=subject.user_id
        )

    assert fixture.scope.completed_reads == 0
    assert fixture.scope.aborted_reads == 1
    fixture.scope.assert_closed()
    assert fixture.workspaces.read_sessions == fixture.members.read_sessions
