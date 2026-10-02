"""Authentication dependency tests."""

import datetime
from typing import Literal

import pytest
from azcommon.result import Success
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.account_access import ActiveAccountSubjectStatus
from azents.core.auth.deps import (
    CurrentUser,
    _require_active_user_session,
    get_current_user,
    get_current_user_optional,
    get_elevated_user,
    get_system_admin,
    get_workspace_member,
)
from azents.core.auth.jwt import create_access_token
from azents.core.auth.roles import get_permissions_for_role
from azents.core.config import (
    AuthConfig,
    JWTConfig,
    RefreshTokenConfig,
    SignupTokenConfig,
)
from azents.core.enums import SystemUserRole, WorkspaceUserRole
from azents.rdb.session import SessionManager
from azents.repos.account_access_test import (
    SubjectIdentity,
    access_fixture,
    seed_subject,
    seed_workspace,
)
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
from azents.repos.system_user_role.operations import SystemUserRoleOperationRepository
from azents.repos.system_user_role.repository import SystemUserRoleRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.system_user_role.service import SystemUserRoleService


def _make_role_service(
    session_manager: SessionManager[AsyncSession],
) -> SystemUserRoleService:
    """Create a system role service for dependency tests."""
    return SystemUserRoleService(
        repository=SystemUserRoleOperationRepository(
            system_role_repository=SystemUserRoleRepository(),
            user_repository=UserRepository(),
            session_manager=session_manager,
        ),
    )


class TestGetSystemAdmin:
    """System administrator dependency tests."""

    async def test_rejects_missing_user(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject an authenticated subject that no longer has a User row."""
        service = _make_role_service(rdb_session_manager)

        with pytest.raises(HTTPException) as exception:
            await get_system_admin(
                CurrentUser(user_id="missing-user", session_id="session-id"),
                service,
            )

        assert exception.value.status_code == 403

    async def test_rejects_user_without_system_admin_role(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject an authenticated ordinary User."""
        service = _make_role_service(rdb_session_manager)
        async with rdb_session_manager() as session:
            user = await UserRepository().create(
                session,
                UserCreate(email="ordinary-admin-dependency@example.com"),
            )

        with pytest.raises(HTTPException) as exception:
            await get_system_admin(
                CurrentUser(user_id=user.id, session_id="session-id"),
                service,
            )

        assert exception.value.status_code == 403
        assert exception.value.detail == "System administrator access required"

    async def test_returns_system_admin_context(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Return the authenticated context when the role exists."""
        service = _make_role_service(rdb_session_manager)
        async with rdb_session_manager() as session:
            user = await UserRepository().create(
                session,
                UserCreate(email="system-admin-dependency@example.com"),
            )
        grant = await service.grant(
            user.id,
            SystemUserRole.SYSTEM_ADMIN,
            granted_by_user_id=None,
            source="test",
        )
        assert isinstance(grant, Success)

        result = await get_system_admin(
            CurrentUser(
                user_id=user.id,
                session_id="session-id",
                elevated=True,
            ),
            service,
        )

        assert result.user_id == user.id
        assert result.session_id == "session-id"
        assert result.elevated

    async def test_revocation_invalidates_existing_user_context(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Re-check the database role for an already-authenticated User context."""
        service = _make_role_service(rdb_session_manager)
        async with rdb_session_manager() as session:
            first = await UserRepository().create(
                session,
                UserCreate(email="revoked-admin-dependency@example.com"),
            )
            remaining = await UserRepository().create(
                session,
                UserCreate(email="remaining-admin-dependency@example.com"),
            )
        for user_id in (first.id, remaining.id):
            grant = await service.grant(
                user_id,
                SystemUserRole.SYSTEM_ADMIN,
                granted_by_user_id=None,
                source="test",
            )
            assert isinstance(grant, Success)
        current_user = CurrentUser(user_id=first.id, session_id="issued-session")
        assert (await get_system_admin(current_user, service)).user_id == first.id
        revoke = await service.revoke(
            first.id,
            SystemUserRole.SYSTEM_ADMIN,
            revoked_by_user_id=remaining.id,
        )
        assert isinstance(revoke, Success)

        with pytest.raises(HTTPException) as exception:
            await get_system_admin(current_user, service)

        assert exception.value.status_code == 403


class TestRequireActiveUserSession:
    """Account-disable and auth-session admission tests."""

    async def test_rejects_access_disabled_user(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject JWT subjects whose account is marked access-disabled."""
        user_repo = UserRepository()
        session_repo = SessionRepository()
        async with rdb_session_manager() as session:
            user = await user_repo.create(
                session,
                UserCreate(email="disabled-access-user@example.com"),
            )
            auth_session = await session_repo.create(
                session,
                SessionCreate(
                    user_id=user.id,
                    refresh_token="refresh-disabled-user",
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=1),
                ),
            )
            await user_repo.disable_access(
                session,
                user.id,
                disabled_at=datetime.datetime.now(datetime.UTC),
            )

        with pytest.raises(HTTPException) as exception:
            await _require_active_user_session(
                access_service=access_fixture(rdb_session_manager).service,
                user_id=user.id,
                session_id=auth_session.id,
            )
        assert exception.value.status_code == 401

    async def test_rejects_revoked_auth_session(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject JWT subjects whose auth session was revoked."""
        user_repo = UserRepository()
        session_repo = SessionRepository()
        async with rdb_session_manager() as session:
            user = await user_repo.create(
                session,
                UserCreate(email="revoked-session-user@example.com"),
            )
            auth_session = await session_repo.create(
                session,
                SessionCreate(
                    user_id=user.id,
                    refresh_token="refresh-revoked-session",
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=1),
                ),
            )
            await session_repo.revoke(session, auth_session.id)

        with pytest.raises(HTTPException) as exception:
            await _require_active_user_session(
                access_service=access_fixture(rdb_session_manager).service,
                user_id=user.id,
                session_id=auth_session.id,
            )
        assert exception.value.status_code == 401


def _auth_config() -> AuthConfig:
    """Return isolated signing settings without provider or credential setup."""
    return AuthConfig(
        jwt=JWTConfig(secret_key="test-only-auth-dependency-signing-key"),
        refresh_token=RefreshTokenConfig(),
        signup_token=SignupTokenConfig(),
    )


def _credentials(
    config: AuthConfig,
    subject: SubjectIdentity,
    *,
    elevated: bool,
) -> HTTPAuthorizationCredentials:
    """Sign the exact existing subject with the requested elevation claim."""
    return HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=create_access_token(
            config.jwt, subject.user_id, subject.session_id, elevated=elevated
        ),
    )


@pytest.mark.parametrize("optional", [False, True])
@pytest.mark.parametrize("kind", ["missing", "malformed", "expired", "wrong_signature"])
async def test_token_rejection_does_not_open_an_admission_read(
    rdb_session_manager: SessionManager[AsyncSession],
    optional: bool,
    kind: Literal["missing", "malformed", "expired", "wrong_signature"],
) -> None:
    """Keep missing/invalid JWT handling and Bearer errors before DB work."""
    config = _auth_config()
    fixture = access_fixture(rdb_session_manager)
    credentials: HTTPAuthorizationCredentials | None = None
    if kind == "malformed":
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="not-a-jwt"
        )
    elif kind == "expired":
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=create_access_token(
                config.jwt,
                "missing-user",
                "missing-session",
                expires_delta=datetime.timedelta(hours=-1),
            ),
        )
    elif kind == "wrong_signature":
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=create_access_token(
                JWTConfig(secret_key="test-only-other-signing-key"),
                "missing-user",
                "missing-session",
            ),
        )
    if optional:
        assert (
            await get_current_user_optional(config, credentials, fixture.service)
            is None
        )
    else:
        with pytest.raises(HTTPException) as error:
            await get_current_user(config, credentials, fixture.service)
        assert error.value.status_code == 401
        assert error.value.detail == (
            "Not authenticated" if kind == "missing" else "Invalid token"
        )
        assert error.value.headers == {"WWW-Authenticate": "Bearer"}
    assert fixture.scope.completed_reads == 0
    assert fixture.scope.sessions == []
    fixture.scope.assert_closed()


@pytest.mark.parametrize("optional", [False, True])
@pytest.mark.parametrize(
    "status",
    [
        status
        for status in ActiveAccountSubjectStatus
        if status is not ActiveAccountSubjectStatus.ACTIVE
    ],
)
async def test_valid_jwt_subject_rejection_preserves_required_and_optional_behavior(
    rdb_session_manager: SessionManager[AsyncSession],
    optional: bool,
    status: ActiveAccountSubjectStatus,
) -> None:
    """Reject every disabled/missing/foreign/revoked/expired state after closure."""
    subject = await seed_subject(rdb_session_manager, status)
    config = _auth_config()
    fixture = access_fixture(rdb_session_manager)
    credentials = _credentials(config, subject, elevated=True)

    if optional:
        assert (
            await get_current_user_optional(config, credentials, fixture.service)
            is None
        )
    else:
        with pytest.raises(HTTPException) as error:
            await get_current_user(config, credentials, fixture.service)
        assert error.value.status_code == 401
        assert error.value.detail == "Not authenticated"
        assert error.value.headers == {"WWW-Authenticate": "Bearer"}

    fixture.scope.assert_closed()
    assert fixture.scope.completed_reads == 1
    assert len(fixture.scope.sessions) == 1


@pytest.mark.parametrize("optional", [False, True])
@pytest.mark.parametrize("elevated", [False, True])
async def test_active_subject_preserves_exact_ids_and_elevation_after_closed_read(
    rdb_session_manager: SessionManager[AsyncSession],
    optional: bool,
    elevated: bool,
) -> None:
    """Return the original core context without granting additional authority."""
    subject = await seed_subject(rdb_session_manager, ActiveAccountSubjectStatus.ACTIVE)
    config = _auth_config()
    fixture = access_fixture(rdb_session_manager)
    credentials = _credentials(config, subject, elevated=elevated)

    if optional:
        result = await get_current_user_optional(config, credentials, fixture.service)
    else:
        result = await get_current_user(config, credentials, fixture.service)

    assert result is not None
    assert result.user_id == subject.user_id
    assert result.session_id == subject.session_id
    assert result.elevated is elevated
    fixture.scope.assert_closed()
    assert fixture.scope.completed_reads == 1
    assert fixture.users.read_sessions == fixture.sessions.read_sessions


@pytest.mark.parametrize("elevated", [False, True])
async def test_elevation_guard_remains_core_http_policy(elevated: bool) -> None:
    """Preserve the same 403 and context identity for step-up authorization."""
    context = CurrentUser(user_id="user", session_id="session", elevated=elevated)
    if elevated:
        assert await get_elevated_user(context) is context
    else:
        with pytest.raises(HTTPException) as error:
            await get_elevated_user(context)
        assert error.value.status_code == 403
        assert error.value.detail == "Elevated access required"


@pytest.mark.parametrize("workspace_exists", [False, True])
async def test_workspace_missing_and_nonmember_have_unchanged_http_errors(
    rdb_session_manager: SessionManager[AsyncSession],
    workspace_exists: bool,
) -> None:
    """Map detached missing Workspace/member outcomes only in core auth."""
    subject = await seed_subject(rdb_session_manager, ActiveAccountSubjectStatus.ACTIVE)
    handle = "missing-workspace"
    if workspace_exists:
        workspace = await seed_workspace(
            rdb_session_manager, user_id=subject.user_id, role=None
        )
        handle = workspace.handle
    fixture = access_fixture(rdb_session_manager)

    with pytest.raises(HTTPException) as error:
        await get_workspace_member(
            CurrentUser(user_id=subject.user_id, session_id=subject.session_id),
            fixture.service,
            handle=handle,
        )

    assert error.value.status_code == (403 if workspace_exists else 404)
    assert error.value.detail == (
        "Not a member of this workspace."
        if workspace_exists
        else "Workspace not found."
    )
    fixture.scope.assert_closed()
    assert fixture.scope.completed_reads == 1


@pytest.mark.parametrize("role", list(WorkspaceUserRole))
async def test_workspace_context_and_permissions_use_current_persisted_membership(
    rdb_session_manager: SessionManager[AsyncSession],
    role: WorkspaceUserRole,
) -> None:
    """Preserve membership IDs, role permission projection and Session identity."""
    subject = await seed_subject(rdb_session_manager, ActiveAccountSubjectStatus.ACTIVE)
    workspace = await seed_workspace(
        rdb_session_manager, user_id=subject.user_id, role=role
    )
    fixture = access_fixture(rdb_session_manager)

    result = await get_workspace_member(
        CurrentUser(user_id=subject.user_id, session_id=subject.session_id),
        fixture.service,
        handle=workspace.handle,
    )

    assert result.user_id == subject.user_id
    assert result.session_id == subject.session_id
    assert result.workspace_id == workspace.workspace_id
    assert result.workspace_user_id == workspace.workspace_user_id
    assert result.role is role
    assert result.permissions == get_permissions_for_role(role)
    fixture.scope.assert_closed()
    assert fixture.workspaces.read_sessions == fixture.members.read_sessions


async def test_workspace_role_change_and_removal_are_authoritative_on_next_read(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A retained User context neither freezes role nor bypasses revoked membership."""
    subject = await seed_subject(rdb_session_manager, ActiveAccountSubjectStatus.ACTIVE)
    workspace = await seed_workspace(
        rdb_session_manager, user_id=subject.user_id, role=WorkspaceUserRole.MEMBER
    )
    assert workspace.workspace_user_id is not None
    fixture = access_fixture(rdb_session_manager)
    context = CurrentUser(user_id=subject.user_id, session_id=subject.session_id)
    first = await get_workspace_member(
        context, fixture.service, handle=workspace.handle
    )
    fixture.scope.assert_closed()
    async with rdb_session_manager() as session:
        updated = await WorkspaceUserRepository().update_role(
            session, workspace.workspace_user_id, WorkspaceUserRole.MANAGER
        )
        assert isinstance(updated, Success)
    second = await get_workspace_member(
        context, fixture.service, handle=workspace.handle
    )
    fixture.scope.assert_closed()
    assert first.role is WorkspaceUserRole.MEMBER
    assert second.role is WorkspaceUserRole.MANAGER
    assert second.permissions == get_permissions_for_role(WorkspaceUserRole.MANAGER)
    async with rdb_session_manager() as session:
        await WorkspaceUserRepository().delete(session, workspace.workspace_user_id)
    with pytest.raises(HTTPException) as error:
        await get_workspace_member(context, fixture.service, handle=workspace.handle)
    assert error.value.status_code == 403
    fixture.scope.assert_closed()


async def test_system_admin_and_elevated_subject_get_no_implicit_workspace_membership(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Keep instance-wide administration separate from Workspace membership."""
    subject = await seed_subject(rdb_session_manager, ActiveAccountSubjectStatus.ACTIVE)
    workspace = await seed_workspace(
        rdb_session_manager, user_id=subject.user_id, role=None
    )
    roles = _make_role_service(rdb_session_manager)
    granted = await roles.grant(
        subject.user_id,
        SystemUserRole.SYSTEM_ADMIN,
        granted_by_user_id=None,
        source="test",
    )
    assert isinstance(granted, Success)
    context = CurrentUser(
        user_id=subject.user_id, session_id=subject.session_id, elevated=True
    )
    assert (await get_system_admin(context, roles)).user_id == subject.user_id
    fixture = access_fixture(rdb_session_manager)

    with pytest.raises(HTTPException) as error:
        await get_workspace_member(context, fixture.service, handle=workspace.handle)

    assert error.value.status_code == 403
    assert error.value.detail == "Not a member of this workspace."
    fixture.scope.assert_closed()


@pytest.mark.parametrize("optional", [False, True])
async def test_authentication_database_failures_remain_transparent(
    rdb_session_manager: SessionManager[AsyncSession],
    optional: bool,
) -> None:
    """Optional auth must not disguise a DB failure as an unauthenticated subject."""
    subject = await seed_subject(rdb_session_manager, ActiveAccountSubjectStatus.ACTIVE)
    config = _auth_config()
    fixture = access_fixture(rdb_session_manager)
    fixture.sessions.failure = ValueError("session lookup failed")
    credentials = _credentials(config, subject, elevated=False)

    with pytest.raises(ValueError, match="session lookup failed"):
        if optional:
            await get_current_user_optional(config, credentials, fixture.service)
        else:
            await get_current_user(config, credentials, fixture.service)

    fixture.scope.assert_closed()
    assert fixture.scope.completed_reads == 0
    assert fixture.scope.aborted_reads == 1
