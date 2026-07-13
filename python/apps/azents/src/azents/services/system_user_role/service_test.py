"""SystemUserRoleService tests."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from azents.core.enums import SystemUserRole
from azents.rdb.session import SessionManager
from azents.repos.system_user_role.data import (
    LastSystemAdmin,
    SystemRoleAssignmentNotFound,
    SystemUserNotFound,
)
from azents.repos.system_user_role.repository import SystemUserRoleRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.services.system_user_role.service import SystemUserRoleService
from azents.services.user import UserService


def _make_role_service(
    session_manager: SessionManager[AsyncSession],
) -> SystemUserRoleService:
    """Create a system role service for tests."""
    return SystemUserRoleService(
        system_role_repository=SystemUserRoleRepository(),
        user_repository=UserRepository(),
        session_manager=session_manager,
    )


def _make_committing_session_manager(
    rdb_engine: AsyncEngine,
) -> SessionManager[AsyncSession]:
    """Create independent committing sessions for concurrency tests."""
    session_factory = async_sessionmaker(rdb_engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory.begin() as session:
            yield session

    return session_manager


class TestSystemUserRoleService:
    """SystemUserRoleService tests."""

    async def test_grant_by_exact_email_is_idempotent(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Resolve normalized exact email and keep one assignment."""
        service = _make_role_service(rdb_session_manager)
        async with rdb_session_manager() as session:
            user = await UserRepository().create(
                session,
                UserCreate(email="admin@example.com"),
            )

        first = await service.grant_by_email(
            " ADMIN@example.com ",
            SystemUserRole.SYSTEM_ADMIN,
            source="test",
        )
        second = await service.grant_by_email(
            "admin@example.com",
            SystemUserRole.SYSTEM_ADMIN,
            source="test",
        )

        assert isinstance(first, Success)
        assert isinstance(second, Success)
        assert first.value.user_id == user.id
        assert second.value == first.value
        listed = await service.list_all()
        assert listed.total == 1
        assert (await service.get_current_roles(user.id)).roles == [
            SystemUserRole.SYSTEM_ADMIN
        ]

    async def test_grant_rejects_unknown_email(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Do not grant a role when exact email is absent."""
        service = _make_role_service(rdb_session_manager)

        result = await service.grant_by_email(
            "missing@example.com",
            SystemUserRole.SYSTEM_ADMIN,
            source="test",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, SystemUserNotFound)

    async def test_revoke_rejects_missing_assignment(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Return a typed error when the target assignment does not exist."""
        service = _make_role_service(rdb_session_manager)

        result = await service.revoke(
            "missing-user",
            SystemUserRole.SYSTEM_ADMIN,
            revoked_by_user_id="acting-user",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, SystemRoleAssignmentNotFound)

    async def test_revoke_preserves_final_system_admin(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject final-admin revoke and allow revoke when another remains."""
        service = _make_role_service(rdb_session_manager)
        async with rdb_session_manager() as session:
            first_user = await UserRepository().create(
                session,
                UserCreate(email="first@example.com"),
            )
            second_user = await UserRepository().create(
                session,
                UserCreate(email="second@example.com"),
            )
        assert isinstance(
            await service.grant(
                first_user.id,
                SystemUserRole.SYSTEM_ADMIN,
                granted_by_user_id=None,
                source="test",
            ),
            Success,
        )

        final_result = await service.revoke(
            first_user.id,
            SystemUserRole.SYSTEM_ADMIN,
            revoked_by_user_id=first_user.id,
        )
        assert isinstance(final_result, Failure)
        assert isinstance(final_result.error, LastSystemAdmin)

        assert isinstance(
            await service.grant(
                second_user.id,
                SystemUserRole.SYSTEM_ADMIN,
                granted_by_user_id=first_user.id,
                source="test",
            ),
            Success,
        )
        result = await service.revoke(
            first_user.id,
            SystemUserRole.SYSTEM_ADMIN,
            revoked_by_user_id=second_user.id,
        )
        assert isinstance(result, Success)
        assert not await service.has_role(
            first_user.id,
            SystemUserRole.SYSTEM_ADMIN,
        )

    async def test_user_delete_preserves_final_system_admin(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Apply the final-admin invariant to global User deletion."""
        role_service = _make_role_service(rdb_session_manager)
        user_repo = UserRepository()
        role_repo = SystemUserRoleRepository()
        user_service = UserService(
            user_repository=user_repo,
            system_role_repository=role_repo,
            session_manager=rdb_session_manager,
        )
        async with rdb_session_manager() as session:
            first_user = await user_repo.create(
                session,
                UserCreate(email="delete-first@example.com"),
            )
            second_user = await user_repo.create(
                session,
                UserCreate(email="delete-second@example.com"),
            )
        assert isinstance(
            await role_service.grant(
                first_user.id,
                SystemUserRole.SYSTEM_ADMIN,
                granted_by_user_id=None,
                source="test",
            ),
            Success,
        )

        final_result = await user_service.delete(first_user.id)
        assert isinstance(final_result, Failure)
        assert isinstance(final_result.error, LastSystemAdmin)

        assert isinstance(
            await role_service.grant(
                second_user.id,
                SystemUserRole.SYSTEM_ADMIN,
                granted_by_user_id=first_user.id,
                source="test",
            ),
            Success,
        )
        result = await user_service.delete(first_user.id)
        assert isinstance(result, Success)
        async with rdb_session_manager() as session:
            assert await user_repo.get(session, first_user.id) is None
            assert (
                await role_repo.count_by_role(
                    session,
                    SystemUserRole.SYSTEM_ADMIN,
                )
                == 1
            )

    async def test_concurrent_revoke_and_delete_preserve_one_system_admin(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """Serialize concurrent mutations so exactly one administrator remains."""
        del latest_db_schema
        session_manager = _make_committing_session_manager(rdb_engine)
        user_repo = UserRepository()
        role_repo = SystemUserRoleRepository()
        role_service = _make_role_service(session_manager)
        user_service = UserService(
            user_repository=user_repo,
            system_role_repository=role_repo,
            session_manager=session_manager,
        )
        async with session_manager() as session:
            revoked_user = await user_repo.create(
                session,
                UserCreate(email="concurrent-revoke@example.com"),
            )
            deleted_user = await user_repo.create(
                session,
                UserCreate(email="concurrent-delete@example.com"),
            )
        try:
            for user_id in (revoked_user.id, deleted_user.id):
                result = await role_service.grant(
                    user_id,
                    SystemUserRole.SYSTEM_ADMIN,
                    granted_by_user_id=None,
                    source="test",
                )
                assert isinstance(result, Success)

            results = await asyncio.gather(
                role_service.revoke(
                    revoked_user.id,
                    SystemUserRole.SYSTEM_ADMIN,
                    revoked_by_user_id=deleted_user.id,
                ),
                user_service.delete(deleted_user.id),
            )

            assert sum(isinstance(result, Success) for result in results) == 1
            failures = [result for result in results if isinstance(result, Failure)]
            assert len(failures) == 1
            assert isinstance(failures[0].error, LastSystemAdmin)
            async with session_manager() as session:
                assert (
                    await role_repo.count_by_role(
                        session,
                        SystemUserRole.SYSTEM_ADMIN,
                    )
                    == 1
                )
        finally:
            async with session_manager() as session:
                await user_repo.delete(session, revoked_user.id)
                await user_repo.delete(session, deleted_user.id)
