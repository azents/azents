"""Real PostgreSQL account/role atomicity and post-commit effect tests."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
import sqlalchemy as sa
from azcommon.result import Failure, Success
from azcommon.uuid import uuid7
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import SystemUserRole
from azents.core.system_user_role import LastSystemAdmin, SystemUserNotFound
from azents.core.user import NotFound, UserDeletionStatus
from azents.rdb.models.owner_lifecycle import RDBOwnerLifecycleJob
from azents.repos.owner_lifecycle import OwnerLifecycleRepository
from azents.repos.owner_lifecycle.data import OwnerLifecycleJob
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
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
from azents.services.user import UserService


class _PersistenceFailure(RuntimeError):
    """An injected error after a real partial database write."""


@dataclasses.dataclass
class _Sessions:
    engine: AsyncEngine
    active: int

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        async with AsyncSession(self.engine, expire_on_commit=False) as session:
            self.active += 1
            try:
                yield session
                await session.commit()
            except asyncio.CancelledError:
                # AsyncSession exit rolls back cancellation, as in production.
                raise
            except Exception:
                await session.rollback()
                raise
            finally:
                self.active -= 1


@dataclasses.dataclass(frozen=True)
class _Account:
    user_id: str
    session_id: str
    email: str


@dataclasses.dataclass(frozen=True)
class _State:
    disabled: bool
    revoked: bool
    administrator: bool
    purge_jobs: int


@dataclasses.dataclass
class _Accounts:
    sessions: _Sessions
    users: UserOperationRepository
    roles: SystemUserRoleOperationRepository
    ids: list[str]

    async def seed(self, *, administrator: bool) -> _Account:
        email = f"account-operations-{uuid7().hex}@example.com"
        user = await self.users.create(UserCreate(email=email))
        self.ids.append(user.id)
        async with self.sessions() as session:
            auth = await SessionRepository().create(
                session,
                SessionCreate(
                    user_id=user.id,
                    refresh_token=uuid7().hex,
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=1),
                ),
            )
        if administrator:
            grant = await self.roles.grant(
                user.id, SystemUserRole.SYSTEM_ADMIN, granted_by_user_id=None
            )
            assert isinstance(grant, Success)
        return _Account(user_id=user.id, session_id=auth.id, email=email)

    async def state(self, account: _Account) -> _State:
        async with self.sessions() as session:
            user = await UserRepository().get(session, account.user_id)
            auth = await SessionRepository().get(session, account.session_id)
            assert user is not None and auth is not None
            administrator = await SystemUserRoleRepository().has_role(
                session, account.user_id, SystemUserRole.SYSTEM_ADMIN
            )
            jobs = await session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBOwnerLifecycleJob)
                .where(RDBOwnerLifecycleJob.user_id == account.user_id)
            )
            assert jobs is not None
            return _State(
                disabled=user.access_disabled_at is not None,
                revoked=auth.revoked_at is not None,
                administrator=administrator,
                purge_jobs=jobs,
            )


@pytest_asyncio.fixture
async def accounts(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncIterator[_Accounts]:
    del latest_db_schema
    sessions = _Sessions(engine=rdb_engine, active=0)
    data = _Accounts(
        sessions=sessions,
        users=UserOperationRepository(
            session_manager=sessions,
            user_repository=UserRepository(),
            system_role_repository=SystemUserRoleRepository(),
            session_repository=SessionRepository(),
            owner_lifecycle_repository=OwnerLifecycleRepository(),
        ),
        roles=SystemUserRoleOperationRepository(
            session_manager=sessions,
            user_repository=UserRepository(),
            system_role_repository=SystemUserRoleRepository(),
        ),
        ids=[],
    )
    try:
        yield data
    finally:
        async with sessions() as session:
            for user_id in data.ids:
                await UserRepository().delete(session, user_id)


@dataclasses.dataclass
class _Publisher(NoopRuntimeTerminalInvalidationPublisher):
    accounts: _Accounts
    account: _Account
    fail: bool
    calls: int

    async def publish_user_terminal_invalidation(self, user_id: str) -> None:
        assert user_id == self.account.user_id
        assert self.accounts.sessions.active == 0
        assert await self.accounts.state(self.account) == _State(
            disabled=True, revoked=True, administrator=False, purge_jobs=1
        )
        self.calls += 1
        if self.fail:
            raise _PersistenceFailure("Injected post-commit publisher failure")


class _FailingRevocation(SessionRepository):
    async def revoke_all_by_user(
        self,
        session: AsyncSession,
        user_id: str,
        *,
        except_session_id: str | None = None,
    ) -> int:
        await super().revoke_all_by_user(
            session, user_id, except_session_id=except_session_id
        )
        raise _PersistenceFailure("Injected failure after Session revocation")


class _FailingPurge(OwnerLifecycleRepository):
    async def create_or_get_account_purge(
        self, session: AsyncSession, *, user_id: str
    ) -> OwnerLifecycleJob:
        await super().create_or_get_account_purge(session, user_id=user_id)
        raise _PersistenceFailure("Injected failure after purge-job insertion")


@dataclasses.dataclass
class _BlockedPurge(OwnerLifecycleRepository):
    entered: asyncio.Event
    release: asyncio.Event

    async def create_or_get_account_purge(
        self, session: AsyncSession, *, user_id: str
    ) -> OwnerLifecycleJob:
        job = await super().create_or_get_account_purge(session, user_id=user_id)
        self.entered.set()
        await self.release.wait()
        return job


async def test_delete_commits_before_publication_and_preserves_repeat(
    accounts: _Accounts,
) -> None:
    account = await accounts.seed(administrator=True)
    await accounts.seed(administrator=True)
    publisher = _Publisher(accounts=accounts, account=account, fail=False, calls=0)
    service = UserService(
        repository=accounts.users, terminal_invalidation_publisher=publisher
    )
    assert isinstance(await service.delete(account.user_id), Success)
    assert isinstance(await service.delete(account.user_id), Success)
    assert publisher.calls == 2
    assert accounts.sessions.active == 0


async def test_missing_and_final_admin_delete_do_not_publish(
    accounts: _Accounts,
) -> None:
    account = await accounts.seed(administrator=True)
    publisher = _Publisher(accounts=accounts, account=account, fail=False, calls=0)
    service = UserService(
        repository=accounts.users, terminal_invalidation_publisher=publisher
    )
    assert isinstance(await service.delete(uuid7().hex), Success)
    denied = await service.delete(account.user_id)
    assert isinstance(denied, Failure)
    assert denied.error == LastSystemAdmin(user_id=account.user_id)
    assert publisher.calls == 0
    assert await accounts.state(account) == _State(
        disabled=False, revoked=False, administrator=True, purge_jobs=0
    )


@pytest.mark.parametrize("stage", ["revoke", "purge"])
async def test_partial_deletion_failure_rolls_back_every_record(
    accounts: _Accounts, stage: str
) -> None:
    account = await accounts.seed(administrator=True)
    await accounts.seed(administrator=True)
    if stage == "revoke":
        accounts.users.session_repository = _FailingRevocation()
    else:
        accounts.users.owner_lifecycle_repository = _FailingPurge()
    publisher = _Publisher(accounts=accounts, account=account, fail=False, calls=0)
    service = UserService(
        repository=accounts.users, terminal_invalidation_publisher=publisher
    )
    with pytest.raises(_PersistenceFailure):
        await service.delete(account.user_id)
    assert publisher.calls == 0
    assert accounts.sessions.active == 0
    assert await accounts.state(account) == _State(
        disabled=False, revoked=False, administrator=True, purge_jobs=0
    )


async def test_cancelled_deletion_rolls_back_before_publication(
    accounts: _Accounts,
) -> None:
    account = await accounts.seed(administrator=True)
    await accounts.seed(administrator=True)
    blocked = _BlockedPurge(entered=asyncio.Event(), release=asyncio.Event())
    accounts.users.owner_lifecycle_repository = blocked
    publisher = _Publisher(accounts=accounts, account=account, fail=False, calls=0)
    service = UserService(
        repository=accounts.users, terminal_invalidation_publisher=publisher
    )
    task = asyncio.create_task(service.delete(account.user_id))
    try:
        await asyncio.wait_for(blocked.entered.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        blocked.release.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert publisher.calls == 0
    assert accounts.sessions.active == 0
    assert await accounts.state(account) == _State(
        disabled=False, revoked=False, administrator=True, purge_jobs=0
    )


async def test_publication_failure_keeps_committed_deletion(
    accounts: _Accounts,
) -> None:
    account = await accounts.seed(administrator=False)
    publisher = _Publisher(accounts=accounts, account=account, fail=True, calls=0)
    service = UserService(
        repository=accounts.users, terminal_invalidation_publisher=publisher
    )
    with pytest.raises(_PersistenceFailure, match="post-commit"):
        await service.delete(account.user_id)
    assert publisher.calls == 1
    assert accounts.sessions.active == 0
    assert await accounts.state(account) == _State(
        disabled=True, revoked=True, administrator=False, purge_jobs=1
    )


async def test_completed_user_reads_update_and_missing_result(
    accounts: _Accounts,
) -> None:
    account = await accounts.seed(administrator=False)
    service = UserService(
        repository=accounts.users,
        terminal_invalidation_publisher=NoopRuntimeTerminalInvalidationPublisher(),
    )
    by_email = await service.get_by_email(account.email)
    assert by_email is not None and by_email.id == account.user_id
    updated = await service.update(account.user_id, {"locale": "ko-KR"})
    assert isinstance(updated, Success)
    assert updated.value.locale == "ko-KR"
    unchanged = await service.update(account.user_id, {})
    assert isinstance(unchanged, Success)
    assert unchanged.value.locale == "ko-KR"
    assert (await service.list_all(offset=0, limit=100)).total >= 1
    missing_id = uuid7().hex
    assert await service.get(missing_id) is None
    missing = await service.update(missing_id, {})
    assert isinstance(missing, Failure)
    assert missing.error == NotFound(user_id=missing_id)
    deleted = await accounts.users.delete(
        missing_id, disabled_at=datetime.datetime.now(datetime.UTC)
    )
    assert deleted == Success(UserDeletionStatus.MISSING)
    assert accounts.sessions.active == 0


async def test_grant_created_fact_preserves_idempotent_metadata(
    accounts: _Accounts,
) -> None:
    account = await accounts.seed(administrator=False)
    actor = await accounts.seed(administrator=False)
    initial = await accounts.roles.grant(
        account.user_id, SystemUserRole.SYSTEM_ADMIN, granted_by_user_id=None
    )
    assert isinstance(initial, Success) and initial.value.created
    repeated = await accounts.roles.grant(
        account.user_id,
        SystemUserRole.SYSTEM_ADMIN,
        granted_by_user_id=actor.user_id,
    )
    assert isinstance(repeated, Success) and not repeated.value.created
    assert repeated.value.assignment == initial.value.assignment
    assert await accounts.roles.has_role(account.user_id, SystemUserRole.SYSTEM_ADMIN)
    assert len(await accounts.roles.list_by_user(account.user_id)) == 1
    assert (await accounts.roles.list_all(offset=0, limit=100)).total == 1
    assert accounts.sessions.active == 0


async def test_grant_rechecks_disabled_user_after_email_lookup(
    accounts: _Accounts,
) -> None:
    account = await accounts.seed(administrator=False)
    assert await accounts.roles.get_user_by_email(account.email) is not None
    async with accounts.sessions() as session:
        await UserRepository().disable_access(
            session,
            account.user_id,
            disabled_at=datetime.datetime.now(datetime.UTC),
        )
    result = await accounts.roles.grant(
        account.user_id, SystemUserRole.SYSTEM_ADMIN, granted_by_user_id=None
    )
    assert result == Failure(SystemUserNotFound(user_id=account.user_id))
    assert not await accounts.roles.has_role(
        account.user_id, SystemUserRole.SYSTEM_ADMIN
    )


class _FailingRoleCreate(SystemUserRoleRepository):
    async def create(
        self, session: AsyncSession, create: SystemUserRoleAssignmentCreate
    ) -> SystemUserRoleAssignment:
        await super().create(session, create)
        raise _PersistenceFailure("Injected failure after assignment creation")


class _FailingRoleDelete(SystemUserRoleRepository):
    async def delete(
        self, session: AsyncSession, user_id: str, role: SystemUserRole
    ) -> bool:
        await super().delete(session, user_id, role)
        raise _PersistenceFailure("Injected failure after assignment removal")


async def test_role_mutation_failures_rollback_assignment(
    accounts: _Accounts,
) -> None:
    account = await accounts.seed(administrator=False)
    accounts.roles.system_role_repository = _FailingRoleCreate()
    with pytest.raises(_PersistenceFailure, match="creation"):
        await accounts.roles.grant(
            account.user_id, SystemUserRole.SYSTEM_ADMIN, granted_by_user_id=None
        )
    assert not await accounts.roles.has_role(
        account.user_id, SystemUserRole.SYSTEM_ADMIN
    )
    accounts.roles.system_role_repository = SystemUserRoleRepository()
    await accounts.roles.grant(
        account.user_id, SystemUserRole.SYSTEM_ADMIN, granted_by_user_id=None
    )
    await accounts.seed(administrator=True)
    accounts.roles.system_role_repository = _FailingRoleDelete()
    with pytest.raises(_PersistenceFailure, match="removal"):
        await accounts.roles.revoke(account.user_id, SystemUserRole.SYSTEM_ADMIN)
    assert await accounts.roles.has_role(account.user_id, SystemUserRole.SYSTEM_ADMIN)
    assert (await accounts.roles.list_all(offset=0, limit=100)).total == 2
    assert accounts.sessions.active == 0
