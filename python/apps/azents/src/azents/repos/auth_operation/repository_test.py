"""Auth operation repository tests."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sqlalchemy as sa
from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.rdb.models.session import RDBSession
from azents.rdb.session import SessionManager
from azents.repos.owner_lifecycle import OwnerLifecycleRepository
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_login.data import PasswordLoginCreate
from azents.repos.session import SessionRepository
from azents.repos.session.data import NotFound, Session, SessionCreate
from azents.repos.system_user_role.data import LastSystemAdmin
from azents.repos.system_user_role.repository import SystemUserRoleRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import User, UserCreate
from azents.repos.user_email import UserEmailRepository
from azents.services.runtime_terminal.invalidation import (
    NoopRuntimeTerminalInvalidationPublisher,
)
from azents.services.user import UserService

from . import AuthOperationRepository
from .data import (
    AuthenticationUnavailable,
    PasswordCredentialLookup,
    RefreshAuthenticationSession,
    RefreshTokenRejected,
    RegistrationRequired,
    VerifiedEmailUserResolve,
)


def _make_repository(
    session_manager: SessionManager[AsyncSession],
    *,
    session_repository: SessionRepository | None = None,
) -> AuthOperationRepository:
    """Create an Auth operation repository."""
    return AuthOperationRepository(
        user_repository=UserRepository(),
        user_email_repository=UserEmailRepository(),
        password_login_repository=PasswordLoginRepository(),
        session_repository=session_repository or SessionRepository(),
        session_manager=session_manager,
    )


def _make_independent_session_manager(
    rdb_engine: AsyncEngine,
) -> SessionManager[AsyncSession]:
    """Create a commit-on-exit manager with an independent connection."""

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(bind=rdb_engine, expire_on_commit=False) as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    return session_manager


async def _create_user(
    session_manager: SessionManager[AsyncSession],
    *,
    email: str,
) -> str:
    """Create one User and return its ID."""
    async with session_manager() as session:
        user = await UserRepository().create(session, UserCreate(email=email))
    return user.id


async def _create_authentication_session(
    session_manager: SessionManager[AsyncSession],
    *,
    email: str,
    refresh_token: str,
    expires_at: datetime.datetime | None = None,
    max_expires_at: datetime.datetime | None = None,
) -> tuple[str, str]:
    """Create a User and authentication Session."""
    user_id = await _create_user(session_manager, email=email)
    async with session_manager() as session:
        authentication_session = await SessionRepository().create(
            session,
            SessionCreate(
                user_id=user_id,
                refresh_token=refresh_token,
                expires_at=expires_at or tznow() + datetime.timedelta(hours=1),
                max_expires_at=max_expires_at,
            ),
        )
    return user_id, authentication_session.id


def _refresh_input(
    *,
    refresh_token: str,
    candidate_refresh_token: str = "candidate-refresh-token",
) -> RefreshAuthenticationSession:
    """Build default refresh operation input."""
    return RefreshAuthenticationSession(
        refresh_token=refresh_token,
        candidate_refresh_token=candidate_refresh_token,
        rotation_period=datetime.timedelta(minutes=10),
        grace_period=datetime.timedelta(minutes=5),
        expire_timedelta=datetime.timedelta(days=180),
    )


class TestAuthIdentityOperations:
    """Identity resolution and credential snapshot tests."""

    async def test_registration_disabled_does_not_create_user(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Closed registration returns a typed result without creating a User."""
        repository = _make_repository(rdb_session_manager)
        email = "auth-registration-disabled@example.com"

        result = await repository.resolve_verified_email_user(
            resolve=VerifiedEmailUserResolve(
                email=email,
                registration_open=False,
            )
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, RegistrationRequired)
        async with rdb_session_manager() as session:
            assert await UserEmailRepository().get_by_email(session, email) is None

    async def test_open_registration_creates_user(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Open registration creates the legacy email User atomically."""
        repository = _make_repository(rdb_session_manager)
        email = "auth-registration-open@example.com"

        result = await repository.resolve_verified_email_user(
            resolve=VerifiedEmailUserResolve(
                email=email,
                registration_open=True,
            )
        )

        assert isinstance(result, Success)
        async with rdb_session_manager() as session:
            user = await UserRepository().get(session, result.value.user_id)
        assert user is not None
        assert user.primary_email == email

    async def test_password_snapshot_rejects_disabled_user(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Disabled User credentials cannot produce an authentication snapshot."""
        repository = _make_repository(rdb_session_manager)
        user_id = await _create_user(
            rdb_session_manager,
            email="auth-password-disabled@example.com",
        )
        async with rdb_session_manager() as session:
            await PasswordLoginRepository().create(
                session,
                PasswordLoginCreate(
                    user_id=user_id,
                    password_hash="stored-hash",
                ),
            )
            await UserRepository().disable_access(
                session,
                user_id,
                disabled_at=tznow(),
            )

        result = await repository.get_password_credential(
            lookup=PasswordCredentialLookup(email="auth-password-disabled@example.com")
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AuthenticationUnavailable)

    async def test_session_issue_revalidates_active_user(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Session insertion fails after the User is disabled."""
        repository = _make_repository(rdb_session_manager)
        user_id = await _create_user(
            rdb_session_manager,
            email="auth-issue-disabled@example.com",
        )
        async with rdb_session_manager() as session:
            await UserRepository().disable_access(
                session,
                user_id,
                disabled_at=tznow(),
            )

        result = await repository.issue_session(
            create=SessionCreate(
                user_id=user_id,
                refresh_token="disabled-user-refresh-token",
                expires_at=tznow() + datetime.timedelta(hours=1),
            )
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AuthenticationUnavailable)


class TestAuthRefreshOperations:
    """Refresh token eligibility and rotation tests."""

    async def test_invalid_refresh_token_is_rejected(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Unknown refresh token returns the typed rejected result."""
        repository = _make_repository(rdb_session_manager)

        result = await repository.refresh_session(
            refresh=_refresh_input(refresh_token="unknown-refresh-token")
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, RefreshTokenRejected)

    async def test_disabled_user_refresh_token_is_rejected(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """A token cannot refresh after its User loses access."""
        user_id, _ = await _create_authentication_session(
            rdb_session_manager,
            email="auth-refresh-disabled@example.com",
            refresh_token="disabled-refresh-token",
        )
        async with rdb_session_manager() as session:
            await UserRepository().disable_access(
                session,
                user_id,
                disabled_at=tznow(),
            )
        repository = _make_repository(rdb_session_manager)

        result = await repository.refresh_session(
            refresh=_refresh_input(refresh_token="disabled-refresh-token")
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, RefreshTokenRejected)

    async def test_expired_refresh_token_is_rejected(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """An expired Session cannot authorize refresh."""
        await _create_authentication_session(
            rdb_session_manager,
            email="auth-refresh-expired@example.com",
            refresh_token="expired-refresh-token",
            expires_at=tznow() - datetime.timedelta(seconds=1),
        )
        repository = _make_repository(rdb_session_manager)

        result = await repository.refresh_session(
            refresh=_refresh_input(refresh_token="expired-refresh-token")
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, RefreshTokenRejected)

    async def test_revoked_refresh_token_is_rejected(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """A revoked Session cannot authorize refresh."""
        _, session_id = await _create_authentication_session(
            rdb_session_manager,
            email="auth-refresh-revoked@example.com",
            refresh_token="revoked-refresh-token",
        )
        async with rdb_session_manager() as session:
            await SessionRepository().revoke(session, session_id)
        repository = _make_repository(rdb_session_manager)

        result = await repository.refresh_session(
            refresh=_refresh_input(refresh_token="revoked-refresh-token")
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, RefreshTokenRejected)

    async def test_previous_token_outside_grace_is_rejected(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Previous token becomes invalid after the configured grace period."""
        _, session_id = await _create_authentication_session(
            rdb_session_manager,
            email="auth-refresh-grace@example.com",
            refresh_token="grace-current-token",
        )
        async with rdb_session_manager() as session:
            await session.execute(
                sa.update(RDBSession)
                .where(RDBSession.id == session_id)
                .values(
                    refresh_token="grace-new-token",
                    prev_refresh_token="grace-current-token",
                    refresh_token_created_at=tznow() - datetime.timedelta(minutes=6),
                )
            )
        repository = _make_repository(rdb_session_manager)

        result = await repository.refresh_session(
            refresh=_refresh_input(refresh_token="grace-current-token")
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, RefreshTokenRejected)

    async def test_previous_token_within_grace_returns_current_token(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Previous token within grace resolves to the current Session token."""
        _, session_id = await _create_authentication_session(
            rdb_session_manager,
            email="auth-refresh-within-grace@example.com",
            refresh_token="within-grace-previous-token",
        )
        async with rdb_session_manager() as session:
            await session.execute(
                sa.update(RDBSession)
                .where(RDBSession.id == session_id)
                .values(
                    refresh_token="within-grace-current-token",
                    prev_refresh_token="within-grace-previous-token",
                    refresh_token_created_at=tznow() - datetime.timedelta(minutes=4),
                )
            )
        repository = _make_repository(rdb_session_manager)

        result = await repository.refresh_session(
            refresh=_refresh_input(
                refresh_token="within-grace-previous-token",
                candidate_refresh_token="unused-within-grace-candidate",
            )
        )

        assert isinstance(result, Success)
        assert result.value.refresh_token == "within-grace-current-token"
        assert result.value.prev_refresh_token == "within-grace-previous-token"

    async def test_rotation_clamps_expiry_to_absolute_maximum(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Rotation preserves the Session absolute maximum expiration."""
        max_expires_at = tznow() + datetime.timedelta(hours=1)
        _, session_id = await _create_authentication_session(
            rdb_session_manager,
            email="auth-refresh-maximum@example.com",
            refresh_token="maximum-current-token",
            max_expires_at=max_expires_at,
        )
        async with rdb_session_manager() as session:
            await session.execute(
                sa.update(RDBSession)
                .where(RDBSession.id == session_id)
                .values(
                    refresh_token_created_at=tznow() - datetime.timedelta(minutes=11)
                )
            )
        repository = _make_repository(rdb_session_manager)

        result = await repository.refresh_session(
            refresh=_refresh_input(
                refresh_token="maximum-current-token",
                candidate_refresh_token="maximum-candidate-token",
            )
        )

        assert isinstance(result, Success)
        assert result.value.refresh_token == "maximum-candidate-token"
        assert result.value.expires_at <= max_expires_at


class _RotateBarrierSessionRepository(SessionRepository):
    """Make concurrent refresh operations reach conditional rotation together."""

    def __init__(self, participant_count: int) -> None:
        self.participant_count = participant_count
        self.arrived_count = 0
        self.arrived_lock = asyncio.Lock()
        self.all_arrived = asyncio.Event()

    async def rotate_refresh_token(
        self,
        session: AsyncSession,
        session_id: str,
        current_refresh_token: str,
        new_refresh_token: str,
        new_expires_at: datetime.datetime,
    ) -> Result[Session, NotFound]:
        """Synchronize immediately before the real conditional update."""
        async with self.arrived_lock:
            self.arrived_count += 1
            if self.arrived_count == self.participant_count:
                self.all_arrived.set()
        await self.all_arrived.wait()
        return await super().rotate_refresh_token(
            session,
            session_id,
            current_refresh_token,
            new_refresh_token,
            new_expires_at,
        )


class _CommitGatedSessionManager:
    """Hold one completed transaction immediately before commit."""

    def __init__(self, rdb_engine: AsyncEngine) -> None:
        self.rdb_engine = rdb_engine
        self.database_work_completed = asyncio.Event()
        self.allow_commit = asyncio.Event()

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            bind=self.rdb_engine,
            expire_on_commit=False,
        ) as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                self.database_work_completed.set()
                await self.allow_commit.wait()
                await session.commit()


class _DisableAttemptUserRepository(UserRepository):
    """Gate account deletion immediately before its conflicting User update."""

    def __init__(self) -> None:
        self.disable_ready = asyncio.Event()
        self.allow_disable = asyncio.Event()
        self.backend_pid: int | None = None

    async def disable_access(
        self,
        session: AsyncSession,
        user_id: str,
        *,
        disabled_at: datetime.datetime,
    ) -> User | None:
        """Capture the backend and gate immediately before the disable update."""
        backend_pid = await session.scalar(sa.select(sa.func.pg_backend_pid()))
        assert isinstance(backend_pid, int)
        self.backend_pid = backend_pid
        self.disable_ready.set()
        await self.allow_disable.wait()
        return await super().disable_access(
            session,
            user_id,
            disabled_at=disabled_at,
        )


@dataclasses.dataclass(frozen=True)
class _PostgresLockWaitEvidence:
    """Authoritative PostgreSQL lock-wait observation."""

    wait_event_type: str | None
    wait_event: str | None
    has_ungranted_lock: bool


async def _wait_for_postgres_lock_wait(
    session_manager: SessionManager[AsyncSession],
    *,
    backend_pid: int,
) -> _PostgresLockWaitEvidence:
    """Poll PostgreSQL until one backend is authoritatively waiting on a lock."""
    async with asyncio.timeout(5):
        while True:
            async with session_manager() as session:
                result = await session.execute(
                    sa.text(
                        """
                        SELECT
                            activity.wait_event_type,
                            activity.wait_event,
                            EXISTS (
                                SELECT 1
                                FROM pg_locks AS lock
                                WHERE lock.pid = :backend_pid
                                  AND NOT lock.granted
                            ) AS has_ungranted_lock
                        FROM pg_stat_activity AS activity
                        WHERE activity.pid = :backend_pid
                        """
                    ),
                    {"backend_pid": backend_pid},
                )
                row = result.one()
            evidence = _PostgresLockWaitEvidence(
                wait_event_type=row.wait_event_type,
                wait_event=row.wait_event,
                has_ungranted_lock=row.has_ungranted_lock,
            )
            if evidence.wait_event_type == "Lock" or evidence.has_ungranted_lock:
                return evidence


async def test_session_issue_share_lock_serializes_account_deletion(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Deletion waits for issuance, then revokes the newly committed Session."""
    del latest_db_schema
    session_manager = _make_independent_session_manager(rdb_engine)
    user_id = await _create_user(
        session_manager,
        email="auth-issue-delete-race@example.com",
    )
    gated_session_manager = _CommitGatedSessionManager(rdb_engine)
    auth_repository = _make_repository(gated_session_manager)
    disable_user_repository = _DisableAttemptUserRepository()
    user_service = UserService(
        user_repository=disable_user_repository,
        system_role_repository=SystemUserRoleRepository(),
        session_repository=SessionRepository(),
        owner_lifecycle_repository=OwnerLifecycleRepository(),
        session_manager=session_manager,
        terminal_invalidation_publisher=NoopRuntimeTerminalInvalidationPublisher(),
    )

    issue_task = asyncio.create_task(
        auth_repository.issue_session(
            create=SessionCreate(
                user_id=user_id,
                refresh_token="issue-delete-race-token",
                expires_at=tznow() + datetime.timedelta(hours=1),
            )
        )
    )
    delete_task: asyncio.Task[Result[None, LastSystemAdmin]] | None = None
    try:
        await asyncio.wait_for(
            gated_session_manager.database_work_completed.wait(),
            timeout=5,
        )
        delete_task = asyncio.create_task(user_service.delete(user_id))
        await asyncio.wait_for(
            disable_user_repository.disable_ready.wait(),
            timeout=5,
        )
        delete_backend_pid = disable_user_repository.backend_pid
        assert delete_backend_pid is not None
        disable_user_repository.allow_disable.set()
        lock_wait = await _wait_for_postgres_lock_wait(
            session_manager,
            backend_pid=delete_backend_pid,
        )
        assert lock_wait.wait_event_type == "Lock" or lock_wait.has_ungranted_lock
        gated_session_manager.allow_commit.set()
        issue_result = await asyncio.wait_for(issue_task, timeout=5)
        delete_result = await asyncio.wait_for(delete_task, timeout=5)

        assert isinstance(issue_result, Success)
        assert isinstance(delete_result, Success)
        async with session_manager() as session:
            authentication_session = await SessionRepository().get(
                session,
                issue_result.value.id,
            )
        assert authentication_session is not None
        assert authentication_session.revoked_at is not None
        assert not authentication_session.is_active
    finally:
        gated_session_manager.allow_commit.set()
        disable_user_repository.allow_disable.set()
        if not issue_task.done():
            issue_task.cancel()
        if delete_task is not None and not delete_task.done():
            delete_task.cancel()
        if delete_task is None:
            await asyncio.gather(issue_task, return_exceptions=True)
        else:
            await asyncio.gather(
                issue_task,
                delete_task,
                return_exceptions=True,
            )
        async with session_manager() as session:
            await UserRepository().delete(session, user_id)


async def test_concurrent_refresh_returns_one_committed_rotation(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Concurrent current-token refreshes converge on the committed winner."""
    del latest_db_schema
    independent_session_manager = _make_independent_session_manager(rdb_engine)

    email = "auth-refresh-concurrency@example.com"
    user_id, session_id = await _create_authentication_session(
        independent_session_manager,
        email=email,
        refresh_token="concurrent-current-token",
    )
    try:
        async with independent_session_manager() as session:
            await session.execute(
                sa.update(RDBSession)
                .where(RDBSession.id == session_id)
                .values(
                    refresh_token_created_at=tznow() - datetime.timedelta(minutes=11)
                )
            )

        session_repository = _RotateBarrierSessionRepository(participant_count=2)
        repository = _make_repository(
            independent_session_manager,
            session_repository=session_repository,
        )
        first, second = await asyncio.gather(
            repository.refresh_session(
                refresh=_refresh_input(
                    refresh_token="concurrent-current-token",
                    candidate_refresh_token="concurrent-candidate-one",
                )
            ),
            repository.refresh_session(
                refresh=_refresh_input(
                    refresh_token="concurrent-current-token",
                    candidate_refresh_token="concurrent-candidate-two",
                )
            ),
        )

        assert isinstance(first, Success)
        assert isinstance(second, Success)
        assert first.value.refresh_token == second.value.refresh_token
        assert first.value.refresh_token in {
            "concurrent-candidate-one",
            "concurrent-candidate-two",
        }
        assert first.value.prev_refresh_token == "concurrent-current-token"
    finally:
        async with independent_session_manager() as session:
            await UserRepository().delete(session, user_id)
