"""SystemUserRoleService tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from unittest.mock import AsyncMock

import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from azents.core.enums import SystemUserRole
from azents.core.system_user_role import (
    LastSystemAdmin,
    SystemRoleAssignmentNotFound,
    SystemUserNotFound,
)
from azents.rdb.models.user import RDBUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.owner_lifecycle import OwnerLifecycleRepository
from azents.repos.session import SessionRepository
from azents.repos.system_user_role.data import (
    SystemUserRoleAssignment,
    SystemUserRoleAssignmentCreate,
)
from azents.repos.system_user_role.operations import SystemUserRoleOperationRepository
from azents.repos.system_user_role.repository import SystemUserRoleRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.user.operations import UserOperationRepository
from azents.services.runtime_terminal.invalidation import (
    NoopRuntimeTerminalInvalidationPublisher,
)
from azents.services.system_user_role.service import SystemUserRoleService
from azents.services.user import UserService


def _make_role_service(
    session_manager: SessionManager[WriteSession],
) -> SystemUserRoleService:
    """Create a system role service for tests."""
    return SystemUserRoleService(
        repository=SystemUserRoleOperationRepository(
            system_role_repository=SystemUserRoleRepository(),
            user_repository=UserRepository(),
            session_manager=session_manager,
        ),
    )


def _make_user_service(
    session_manager: SessionManager[WriteSession],
) -> UserService:
    """Create a UserService with owner-lifecycle collaborators for tests."""
    return UserService(
        repository=UserOperationRepository(
            user_repository=UserRepository(),
            system_role_repository=SystemUserRoleRepository(),
            session_repository=SessionRepository(),
            owner_lifecycle_repository=OwnerLifecycleRepository(),
            session_manager=session_manager,
        ),
        terminal_invalidation_publisher=NoopRuntimeTerminalInvalidationPublisher(),
    )


def _make_committing_session_manager(
    rdb_engine: AsyncEngine,
) -> SessionManager[WriteSession]:
    """Create independent committing sessions for concurrency tests."""
    session_factory = async_sessionmaker(rdb_engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[WriteSession, None]:
        async with session_factory.begin() as raw_session:
            session = ReadWriteSession(raw_session)
            yield session

    return session_manager


class TestSystemUserRoleService:
    """SystemUserRoleService tests."""

    async def test_grant_by_exact_email_is_idempotent(
        self,
        rdb_session_manager: SessionManager[WriteSession],
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
        rdb_session_manager: SessionManager[WriteSession],
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
        rdb_session_manager: SessionManager[WriteSession],
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
        rdb_session_manager: SessionManager[WriteSession],
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
        rdb_session_manager: SessionManager[WriteSession],
    ) -> None:
        """Apply the final-admin invariant to global User deletion."""
        role_service = _make_role_service(rdb_session_manager)
        user_repo = UserRepository()
        role_repo = SystemUserRoleRepository()
        user_service = _make_user_service(rdb_session_manager)
        user_service.terminal_invalidation_publisher = AsyncMock()
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
        publisher = user_service.terminal_invalidation_publisher
        publish = publisher.publish_user_terminal_invalidation
        publish.assert_awaited_once_with(first_user.id)
        async with rdb_session_manager() as session:
            deleted_user = await user_repo.get(session, first_user.id)
            assert deleted_user is not None
            assert deleted_user.access_disabled_at is not None
            assert (
                await role_repo.count_by_role(
                    session,
                    SystemUserRole.SYSTEM_ADMIN,
                )
                == 1
            )
            assert (
                await role_repo.get(
                    session,
                    first_user.id,
                    SystemUserRole.SYSTEM_ADMIN,
                )
                is None
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
        user_service = _make_user_service(session_manager)
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


async def test_ordinary_grant_does_not_inherit_final_admin_gate(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Assignment uniqueness admits a grant while the removal gate is held."""
    del latest_db_schema
    suffix = str(id(rdb_engine))
    manager = _make_committing_session_manager(rdb_engine)
    role_service = _make_role_service(manager)
    async with manager() as session:
        user = await UserRepository().create(
            session, UserCreate(email=f"grant-with-held-gate-{suffix}@example.com")
        )
    try:
        async with manager() as holder:
            await SystemUserRoleRepository().acquire_mutation_lock(holder)
            async with asyncio.timeout(5):
                outcome = await role_service.grant(
                    user.id,
                    SystemUserRole.SYSTEM_ADMIN,
                    granted_by_user_id=None,
                    source="test",
                )
            assert isinstance(outcome, Success)
            repeated = await role_service.grant(
                user.id,
                SystemUserRole.SYSTEM_ADMIN,
                granted_by_user_id=None,
                source="test",
            )
            assert isinstance(repeated, Success)
    finally:
        async with manager() as session:
            await UserRepository().delete(session, user.id)


async def test_late_admin_grant_cannot_create_disabled_phantom_administrator(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Final grant eligibility excludes disable and the following role sweep."""
    del latest_db_schema
    manager = _make_committing_session_manager(rdb_engine)
    task: asyncio.Task[object] | None = None
    async with manager() as session:
        user = await UserRepository().create(
            session, UserCreate(email="late-admin-grant@example.com")
        )
    try:
        async with manager() as disabler, manager() as grant_session:
            await disabler.write_session.execute(
                sa.update(RDBUser)
                .where(RDBUser.id == user.id)
                .values(access_disabled_at=datetime.datetime.now(datetime.UTC))
            )
            await SystemUserRoleRepository().delete(
                disabler, user.id, SystemUserRole.SYSTEM_ADMIN
            )
            blocker_pid = await disabler.read_session.scalar(
                sa.text("SELECT pg_backend_pid()")
            )
            grant_pid = await grant_session.read_session.scalar(
                sa.text("SELECT pg_backend_pid()")
            )
            assert isinstance(blocker_pid, int) and isinstance(grant_pid, int)

            async def grant() -> object:
                repository = SystemUserRoleOperationRepository(
                    system_role_repository=SystemUserRoleRepository(),
                    user_repository=UserRepository(),
                    session_manager=lambda: _existing_grant_scope(grant_session),
                )
                return await repository.grant(
                    user.id, SystemUserRole.SYSTEM_ADMIN, granted_by_user_id=None
                )

            @asynccontextmanager
            async def _existing_grant_scope(
                session: WriteSession,
            ) -> AsyncGenerator[WriteSession, None]:
                yield session

            task = asyncio.create_task(grant())
            async with asyncio.timeout(5), manager() as observer:
                while True:
                    blockers = await observer.read_session.scalar(
                        sa.text("SELECT pg_blocking_pids(:pid)"), {"pid": grant_pid}
                    )
                    if blocker_pid in blockers:
                        break
                    assert not task.done()
            await disabler.write_session.commit()
            outcome = await asyncio.wait_for(task, timeout=5)
            assert isinstance(outcome, Failure)
            assert isinstance(outcome.error, SystemUserNotFound)
        async with manager() as session:
            assert not await SystemUserRoleRepository().has_role(
                session, user.id, SystemUserRole.SYSTEM_ADMIN
            )
    finally:
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        async with manager() as session:
            await UserRepository().delete(session, user.id)


async def test_completed_grant_is_removed_by_following_disable_sweep(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Grant winning first cannot survive the waiting account-deletion sweep."""
    del latest_db_schema
    manager = _make_committing_session_manager(rdb_engine)
    task: asyncio.Task[object] | None = None
    async with manager() as session:
        survivor = await UserRepository().create(
            session, UserCreate(email="grant-survivor@example.com")
        )
        target = await UserRepository().create(
            session, UserCreate(email="grant-then-disable@example.com")
        )
        await SystemUserRoleRepository().create(
            session,
            SystemUserRoleAssignmentCreate(
                user_id=survivor.id,
                role=SystemUserRole.SYSTEM_ADMIN,
                granted_by_user_id=None,
            ),
        )
    try:
        async with manager() as grant_session, manager() as delete_session:
            repository = SystemUserRoleRepository()
            assert await repository.admit_active_user_grant(grant_session, target.id)
            grant_pid = await grant_session.read_session.scalar(
                sa.text("SELECT pg_backend_pid()")
            )
            delete_pid = await delete_session.read_session.scalar(
                sa.text("SELECT pg_backend_pid()")
            )
            assert isinstance(grant_pid, int) and isinstance(delete_pid, int)

            @asynccontextmanager
            async def delete_scope() -> AsyncGenerator[WriteSession, None]:
                yield delete_session

            deletion = _make_user_service(delete_scope)
            task = asyncio.create_task(deletion.delete(target.id))
            async with asyncio.timeout(5), manager() as observer:
                while True:
                    blockers = await observer.read_session.scalar(
                        sa.text("SELECT pg_blocking_pids(:pid)"), {"pid": delete_pid}
                    )
                    if grant_pid in blockers:
                        break
                    assert not task.done()
            await repository.create_if_absent(
                grant_session,
                SystemUserRoleAssignmentCreate(
                    user_id=target.id,
                    role=SystemUserRole.SYSTEM_ADMIN,
                    granted_by_user_id=None,
                ),
            )
            await grant_session.write_session.commit()
            await asyncio.wait_for(task, timeout=5)
            await delete_session.write_session.commit()
        async with manager() as session:
            assert not await repository.has_role(
                session, target.id, SystemUserRole.SYSTEM_ADMIN
            )
            assert (
                await repository.count_by_role(session, SystemUserRole.SYSTEM_ADMIN)
                == 1
            )
    finally:
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        async with manager() as session:
            await UserRepository().delete(session, target.id)
            await UserRepository().delete(session, survivor.id)


async def test_disabled_legacy_role_does_not_satisfy_final_admin_count(
    rdb_session: WriteSession,
) -> None:
    """A retained disabled assignment cannot authorize removal of the last admin."""
    user = await UserRepository().create(
        rdb_session, UserCreate(email="disabled-role-count@example.com")
    )
    repository = SystemUserRoleRepository()
    await repository.create(
        rdb_session,
        SystemUserRoleAssignmentCreate(
            user_id=user.id,
            role=SystemUserRole.SYSTEM_ADMIN,
            granted_by_user_id=None,
        ),
    )
    await UserRepository().disable_access(
        rdb_session, user.id, disabled_at=datetime.datetime.now(datetime.UTC)
    )
    assert await repository.count_by_role(rdb_session, SystemUserRole.SYSTEM_ADMIN) == 0


async def test_grant_existing_assignment_and_revoke_have_a_legal_order(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Revoke cannot remove the assignment between grant's insert and result load."""
    del latest_db_schema
    manager = _make_committing_session_manager(rdb_engine)
    async with manager() as session:
        user = await UserRepository().create(
            session, UserCreate(email="grant-revoke-race@example.com")
        )
        survivor = await UserRepository().create(
            session, UserCreate(email="grant-revoke-survivor@example.com")
        )
        for user_id in (user.id, survivor.id):
            await SystemUserRoleRepository().create(
                session,
                SystemUserRoleAssignmentCreate(
                    user_id=user_id,
                    role=SystemUserRole.SYSTEM_ADMIN,
                    granted_by_user_id=None,
                ),
            )
    inserted = asyncio.Event()
    release_result = asyncio.Event()
    grant_task: asyncio.Task[object] | None = None
    revoke_task: asyncio.Task[object] | None = None

    class PausedAssignmentResult(SystemUserRoleRepository):
        async def create_if_absent(
            self,
            session: WriteSession,
            create: SystemUserRoleAssignmentCreate,
        ) -> SystemUserRoleAssignment | None:
            result = await super().create_if_absent(session, create)
            assert result is None
            inserted.set()
            await release_result.wait()
            return result

    try:
        async with manager() as grant_session, manager() as revoke_session:

            @asynccontextmanager
            async def grant_scope() -> AsyncGenerator[WriteSession, None]:
                yield grant_session

            @asynccontextmanager
            async def revoke_scope() -> AsyncGenerator[WriteSession, None]:
                yield revoke_session

            grant_repo = SystemUserRoleOperationRepository(
                session_manager=grant_scope,
                user_repository=UserRepository(),
                system_role_repository=PausedAssignmentResult(),
            )
            revoke_repo = SystemUserRoleOperationRepository(
                session_manager=revoke_scope,
                user_repository=UserRepository(),
                system_role_repository=SystemUserRoleRepository(),
            )
            grant_pid = await grant_session.read_session.scalar(
                sa.text("SELECT pg_backend_pid()")
            )
            revoke_pid = await revoke_session.read_session.scalar(
                sa.text("SELECT pg_backend_pid()")
            )
            assert isinstance(grant_pid, int) and isinstance(revoke_pid, int)
            grant_task = asyncio.create_task(
                grant_repo.grant(
                    user.id, SystemUserRole.SYSTEM_ADMIN, granted_by_user_id=None
                )
            )
            await asyncio.wait_for(inserted.wait(), timeout=5)
            revoke_task = asyncio.create_task(
                revoke_repo.revoke(user.id, SystemUserRole.SYSTEM_ADMIN)
            )
            async with asyncio.timeout(5), manager() as observer:
                while True:
                    blockers = await observer.read_session.scalar(
                        sa.text("SELECT pg_blocking_pids(:pid)"), {"pid": revoke_pid}
                    )
                    if grant_pid in blockers:
                        break
                    assert not revoke_task.done()
            release_result.set()
            granted = await asyncio.wait_for(grant_task, timeout=5)
            assert isinstance(granted, Success) and not granted.value.created
            await grant_session.write_session.commit()
            revoked = await asyncio.wait_for(revoke_task, timeout=5)
            assert isinstance(revoked, Success)
            await revoke_session.write_session.commit()
    finally:
        release_result.set()
        for task in (grant_task, revoke_task):
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        async with manager() as session:
            await UserRepository().delete(session, user.id)
            await UserRepository().delete(session, survivor.id)
