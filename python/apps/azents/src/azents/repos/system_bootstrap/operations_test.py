"""Actual bootstrap repository admission and cancellation contracts."""

import asyncio
import dataclasses
import datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.rdb.models.system_user_role import RDBSystemBootstrapState
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.session import SessionRepository
from azents.repos.system_bootstrap.operations import (
    BootstrapCommand,
    BootstrapCreated,
    BootstrapRejection,
    SystemBootstrapOperationRepository,
)
from azents.repos.system_bootstrap.repository import SystemBootstrapRepository
from azents.repos.system_user_role.repository import SystemUserRoleRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate


class _CancelledConsume(SystemBootstrapRepository):
    async def consume(self, session: WriteSession) -> None:
        await super().consume(session)
        raise asyncio.CancelledError("isolated bootstrap consume cancellation")


def _operations(
    manager: SessionManager[WriteSession],
) -> SystemBootstrapOperationRepository:
    return SystemBootstrapOperationRepository(
        session_manager=manager,
        read_session_manager=manager,
        bootstrap_repository=SystemBootstrapRepository(),
        role_repository=SystemUserRoleRepository(),
        user_repository=UserRepository(),
        password_repository=PasswordLoginRepository(),
        session_repository=SessionRepository(),
    )


def _command(*, token_hash: str, email: str) -> BootstrapCommand:
    now = datetime.datetime.now(datetime.UTC)
    return BootstrapCommand(
        submitted_hash=token_hash,
        email=email,
        password_hash="prepared-hash",
        now=now,
        refresh_token=uuid4().hex,
        expires_at=now + datetime.timedelta(days=1),
        max_expires_at=None,
        user_agent=None,
        ip_address=None,
    )


async def test_cancellation_after_actual_consume_rolls_back_every_record(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    operations = _operations(rdb_session_manager)
    token_hash = uuid4().hex
    await operations.initialize(token_hash=token_hash, configured=True)
    failing = dataclasses.replace(operations, bootstrap_repository=_CancelledConsume())
    with pytest.raises(asyncio.CancelledError):
        await failing.bootstrap(
            command=_command(
                token_hash=token_hash, email="bootstrap-cancel@example.com"
            )
        )
    assert await operations.available()
    assert await operations.admission(submitted_hash=token_hash) is None
    async with rdb_session_manager() as session:
        assert await UserRepository().count(session) == 0
    result = await operations.bootstrap(
        command=_command(token_hash=token_hash, email="bootstrap-cancel@example.com")
    )
    assert isinstance(result, BootstrapCreated)


async def test_final_mutation_rechecks_user_authority_after_read_admission(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    operations = _operations(rdb_session_manager)
    token_hash = uuid4().hex
    await operations.initialize(token_hash=token_hash, configured=True)
    assert await operations.admission(submitted_hash=token_hash) is None
    async with rdb_session_manager() as session:
        await UserRepository().create_with_verified_primary_email(
            session,
            UserCreate(email="bootstrap-intervening@example.com"),
            verified_at=datetime.datetime.now(datetime.UTC),
        )
    result = await operations.bootstrap(
        command=_command(token_hash=token_hash, email="bootstrap-denied@example.com")
    )
    assert result is BootstrapRejection.USERS_EXIST
    async with rdb_session_manager() as session:
        state = await SystemBootstrapRepository().get(session)
        assert state is not None and state.consumed_at is None
        assert (
            await UserRepository().get_by_email(session, "bootstrap-denied@example.com")
            is None
        )


async def test_native_read_only_status_and_admission_finish_before_preparation(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    operations = dataclasses.replace(
        _operations(manager),
        read_session_manager=create_read_only_session_manager(rdb_engine),
    )
    token_hash = uuid4().hex
    await operations.initialize(token_hash=token_hash, configured=True)
    try:
        assert await operations.available()
        assert await operations.admission(submitted_hash=token_hash) is None
        assert (
            await operations.admission(submitted_hash="wrong")
            is BootstrapRejection.INVALID_TOKEN
        )
        async with manager() as session:
            state = await SystemBootstrapRepository().get(session)
            assert state is not None and state.consumed_at is None
    finally:
        async with manager() as session:
            await session.write_session.execute(sa.delete(RDBSystemBootstrapState))
