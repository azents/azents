"""SystemBootstrapService tests."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from azents.core.config import (
    AuthConfig,
    JWTConfig,
    RefreshTokenConfig,
    SignupTokenConfig,
    SystemBootstrapConfig,
)
from azents.core.enums import SystemUserRole
from azents.rdb.models.system_user_role import RDBSystemBootstrapState
from azents.rdb.session import SessionManager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.session import SessionRepository
from azents.repos.system_bootstrap.repository import SystemBootstrapRepository
from azents.repos.system_user_role.repository import SystemUserRoleRepository
from azents.repos.user import UserRepository
from azents.repos.workspace import WorkspaceRepository
from azents.services.system_bootstrap.data import (
    BootstrapUnavailable,
    InvalidSetupToken,
    SystemBootstrapInput,
    WeakBootstrapPassword,
)
from azents.services.system_bootstrap.service import SystemBootstrapService

_TEST_AUTH_CONFIG = AuthConfig(
    jwt=JWTConfig(
        secret_key="test-secret-key-for-jwt-signing-1234567890",
        algorithm="HS256",
        access_token_expire_minutes=30,
    ),
    refresh_token=RefreshTokenConfig(
        expire_days=180,
        rotation_period_minutes=10,
        grace_period_minutes=5,
    ),
    signup_token=SignupTokenConfig(default_expire_hours=168, default_max_uses=1),
)


def _service(
    session_manager: SessionManager[AsyncSession],
    *,
    setup_token: str | None,
) -> SystemBootstrapService:
    return SystemBootstrapService(
        bootstrap_repository=SystemBootstrapRepository(),
        system_role_repository=SystemUserRoleRepository(),
        user_repository=UserRepository(),
        password_login_repository=PasswordLoginRepository(),
        session_repository=SessionRepository(),
        session_manager=session_manager,
        auth_config=_TEST_AUTH_CONFIG,
        bootstrap_config=SystemBootstrapConfig(setup_token=setup_token),
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


class _FailingConsumeRepository(SystemBootstrapRepository):
    async def consume(self, session: AsyncSession) -> None:
        """Fail after all account records have been staged."""
        del session
        raise RuntimeError("Injected bootstrap consume failure")


def _input(setup_token: str, *, password: str = "Aa123456!") -> SystemBootstrapInput:
    return SystemBootstrapInput(
        setup_token=setup_token,
        email="admin@example.com",
        password=password,
        user_agent="bootstrap-test",
        ip_address="127.0.0.1",
    )


async def test_generated_token_is_logged_once_and_bootstraps_without_workspace(
    rdb_session_manager: SessionManager[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = _service(rdb_session_manager, setup_token=None)

    with caplog.at_level(logging.WARNING):
        await service.initialize()
        await service.initialize()

    token_records = [
        record
        for record in caplog.records
        if record.getMessage() == "Generated one-time system bootstrap setup token"
    ]
    assert len(token_records) == 1
    setup_token = token_records[0].__dict__.get("setup_token")
    assert isinstance(setup_token, str)
    assert setup_token not in token_records[0].getMessage()
    assert (await service.get_status()).available

    result = await service.bootstrap(_input(setup_token))

    assert isinstance(result, Success)
    assert result.value.access_token
    assert result.value.refresh_token
    assert not (await service.get_status()).available
    repeated = await service.bootstrap(_input(setup_token))
    assert isinstance(repeated, Failure)
    assert isinstance(repeated.error, BootstrapUnavailable)
    async with rdb_session_manager() as session:
        user = await UserRepository().get_by_email(session, "admin@example.com")
        assert user is not None
        assert await SystemUserRoleRepository().has_role(
            session,
            user.id,
            SystemUserRole.SYSTEM_ADMIN,
        )
        workspaces = await WorkspaceRepository().list_all(session)
        assert workspaces.items == []


async def test_invalid_token_and_weak_password_do_not_consume_bootstrap(
    rdb_session_manager: SessionManager[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    setup_token = "configured-bootstrap-token-0123456789"
    service = _service(rdb_session_manager, setup_token=setup_token)
    await service.initialize()

    with caplog.at_level(logging.INFO):
        invalid = await service.bootstrap(_input("incorrect-token"))
        weak = await service.bootstrap(_input(setup_token, password="weak"))

    assert isinstance(invalid, Failure)
    assert isinstance(invalid.error, InvalidSetupToken)
    assert isinstance(weak, Failure)
    assert isinstance(weak.error, WeakBootstrapPassword)
    rejection_records = [
        record
        for record in caplog.records
        if record.getMessage() == "System bootstrap attempt rejected"
    ]
    assert [record.__dict__.get("reason") for record in rejection_records] == [
        "invalid_setup_token"
    ]
    assert all(
        setup_token not in repr(record.__dict__)
        and "incorrect-token" not in repr(record.__dict__)
        for record in rejection_records
    )
    assert (await service.get_status()).available
    async with rdb_session_manager() as session:
        assert await UserRepository().count(session) == 0


async def test_configured_token_replaces_an_unconsumed_generated_token(
    rdb_session_manager: SessionManager[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    generated_service = _service(rdb_session_manager, setup_token=None)
    await generated_service.initialize()

    configured_token = "replacement-bootstrap-token-0123456789"
    configured_service = _service(
        rdb_session_manager,
        setup_token=configured_token,
    )
    with caplog.at_level(logging.INFO):
        await configured_service.initialize()
        await configured_service.initialize()

    activation_records = [
        record
        for record in caplog.records
        if record.getMessage() == "Configured system bootstrap setup token activated"
    ]
    assert len(activation_records) == 1
    assert all(
        configured_token not in repr(record.__dict__) for record in caplog.records
    )

    result = await configured_service.bootstrap(_input(configured_token))
    assert isinstance(result, Success)


async def test_failed_transaction_rolls_back_and_leaves_token_usable(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    setup_token = "rollback-bootstrap-token-0123456789"
    service = _service(rdb_session_manager, setup_token=setup_token)
    await service.initialize()
    service.bootstrap_repository = _FailingConsumeRepository()

    with pytest.raises(RuntimeError, match="Injected bootstrap consume failure"):
        await service.bootstrap(_input(setup_token))

    assert (await service.get_status()).available
    async with rdb_session_manager() as session:
        assert await UserRepository().count(session) == 0

    service.bootstrap_repository = SystemBootstrapRepository()
    result = await service.bootstrap(_input(setup_token))
    assert isinstance(result, Success)


async def test_concurrent_bootstrap_creates_exactly_one_system_admin(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    del latest_db_schema
    setup_token = "concurrent-bootstrap-token-0123456789"
    session_manager = _make_committing_session_manager(rdb_engine)
    service = _service(session_manager, setup_token=setup_token)
    await service.initialize()

    try:
        results = await asyncio.gather(
            service.bootstrap(_input(setup_token)),
            service.bootstrap(_input(setup_token)),
        )

        assert sum(isinstance(result, Success) for result in results) == 1
        failures = [result for result in results if isinstance(result, Failure)]
        assert len(failures) == 1
        assert isinstance(failures[0].error, BootstrapUnavailable)
        async with session_manager() as session:
            assert await UserRepository().count(session) == 1
            assert (
                await SystemUserRoleRepository().count_by_role(
                    session,
                    SystemUserRole.SYSTEM_ADMIN,
                )
                == 1
            )
    finally:
        async with session_manager() as session:
            user = await UserRepository().get_by_email(session, "admin@example.com")
            if user is not None:
                await UserRepository().delete(session, user.id)
            await session.execute(sa.delete(RDBSystemBootstrapState))
