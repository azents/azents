"""Authentication dependency tests."""

import datetime

import pytest
from azcommon.result import Success
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.auth.deps import (
    CurrentUser,
    _require_active_user_session,
    get_system_admin,
)
from azents.core.enums import SystemUserRole
from azents.rdb.session import SessionManager
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
from azents.repos.system_user_role.repository import SystemUserRoleRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.services.system_user_role.service import SystemUserRoleService


def _make_role_service(
    session_manager: SessionManager[AsyncSession],
) -> SystemUserRoleService:
    """Create a system role service for dependency tests."""
    return SystemUserRoleService(
        system_role_repository=SystemUserRoleRepository(),
        user_repository=UserRepository(),
        session_manager=session_manager,
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
                session_manager=rdb_session_manager,
                user_repository=user_repo,
                session_repository=session_repo,
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
                session_manager=rdb_session_manager,
                user_repository=user_repo,
                session_repository=session_repo,
                user_id=user.id,
                session_id=auth_session.id,
            )
        assert exception.value.status_code == 401
