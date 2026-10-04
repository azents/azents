"""Executable repository/caller sample for the opt-in Session foundation."""

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from psycopg.errors import ReadOnlySqlTransaction
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from testcontainers.postgres import PostgresContainer

from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    ReadOnlySession,
    ReadSession,
    ReadWriteSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)


class _SampleBase(DeclarativeBase):
    """Schema isolated to the test container; not an application migration."""


class _SampleRecord(_SampleBase):
    __tablename__ = "session_foundation_sample"

    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[int] = mapped_column(nullable=False)


class _SampleRepository:
    """One repository, with capabilities declared per method, not per class."""

    async def read_value(self, session: ReadSession, record_id: int) -> int | None:
        """Read normally, accepting either concrete session implementation."""
        return await session.read_session.scalar(
            sa.select(_SampleRecord.value).where(_SampleRecord.id == record_id)
        )

    async def insert(self, session: WriteSession, record_id: int, value: int) -> None:
        """Write without taking ownership of the caller's transaction."""
        await session.write_session.execute(
            sa.insert(_SampleRecord).values(id=record_id, value=value)
        )

    async def lock_value(self, session: WriteSession, record_id: int) -> int | None:
        """A row lock is a write capability, even when SQL returns only a value."""
        return await session.write_session.scalar(
            sa.select(_SampleRecord.value)
            .where(_SampleRecord.id == record_id)
            .with_for_update()
        )


@pytest_asyncio.fixture
async def sample_engine(
    postgres_container: PostgresContainer,
) -> AsyncIterator[AsyncEngine]:
    """Force reuse of one physical connection to exercise option restoration."""
    engine = create_async_engine(
        postgres_container.get_connection_url(), pool_size=1, max_overflow=0
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_SampleBase.metadata.create_all)
            await connection.execute(sa.insert(_SampleRecord).values(id=1, value=10))
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(_SampleBase.metadata.drop_all)
        await engine.dispose()


async def test_default_read_caller_uses_read_only(sample_engine: AsyncEngine) -> None:
    """The existing covariant manager can return the read capability Protocol."""
    reads: SessionManager[ReadSession] = create_read_only_session_manager(sample_engine)
    repository = _SampleRepository()
    async with reads() as session:
        assert isinstance(session, ReadOnlySession)
        assert (
            await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
            == "on"
        )
        assert await repository.read_value(session, 1) == 10
        assert await repository.read_value(session, 2) is None


async def test_write_caller_can_compose_reads_in_same_transaction(
    sample_engine: AsyncEngine,
) -> None:
    writes: SessionManager[WriteSession] = create_read_write_session_manager(
        sample_engine
    )
    repository = _SampleRepository()
    async with writes() as session:
        assert isinstance(session, ReadWriteSession)
        assert session.read_session is session.write_session
        assert (
            await session.write_session.scalar(sa.text("SHOW transaction_read_only"))
            == "off"
        )
        await repository.insert(session, 2, 20)
        assert await repository.read_value(session, 2) == 20
        assert await repository.lock_value(session, 2) == 20
    # Normal subsequent reads still use the ReadOnly factory, not WriteSession.
    async with create_read_only_session_manager(sample_engine)() as session:
        assert await repository.read_value(session, 2) == 20


@pytest.mark.parametrize(
    "statement",
    [
        sa.insert(_SampleRecord).values(id=2, value=20),
        sa.update(_SampleRecord).where(_SampleRecord.id == 1).values(value=99),
        sa.delete(_SampleRecord).where(_SampleRecord.id == 1),
        sa.select(_SampleRecord.value).with_for_update(),
        sa.select(_SampleRecord.value).with_for_update(read=True),
    ],
    ids=["insert", "update", "delete", "row-update-lock", "row-share-lock"],
)
async def test_db_rejects_writes_and_row_locks_through_read_attribute(
    sample_engine: AsyncEngine,
    statement: sa.Executable,
) -> None:
    """Raw execute accepts arbitrary SQL; the real DB provides enforcement."""
    with pytest.raises(DBAPIError) as raised:
        async with create_read_only_session_manager(sample_engine)() as session:
            await session.read_session.execute(statement)
    assert isinstance(raised.value.orig, ReadOnlySqlTransaction)
    async with create_read_only_session_manager(sample_engine)() as session:
        assert await _SampleRepository().read_value(session, 1) == 10


async def test_read_only_flush_is_rejected(sample_engine: AsyncEngine) -> None:
    with pytest.raises(DBAPIError) as raised:
        async with create_read_only_session_manager(sample_engine)() as session:
            session.read_session.add(_SampleRecord(id=2, value=20))
            # Disabled autoflush prevents a read from flushing accidental ORM state.
            assert await _SampleRepository().read_value(session, 2) is None
            await session.read_session.flush()
    assert isinstance(raised.value.orig, ReadOnlySqlTransaction)


async def test_read_only_scope_does_not_commit_accidental_orm_writes(
    sample_engine: AsyncEngine,
) -> None:
    with pytest.raises(DBAPIError) as raised:
        async with create_read_only_session_manager(sample_engine)() as session:
            session.read_session.add(_SampleRecord(id=2, value=20))
    assert isinstance(raised.value.orig, ReadOnlySqlTransaction)


@pytest.mark.parametrize("cancelled", [False, True], ids=["exception", "cancellation"])
async def test_write_scope_rolls_back_on_failure(
    sample_engine: AsyncEngine,
    cancelled: bool,
) -> None:
    repository = _SampleRepository()
    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            async with create_read_write_session_manager(sample_engine)() as session:
                await repository.insert(session, 2, 20)
                raise asyncio.CancelledError
    else:
        with pytest.raises(ValueError, match="sample failure"):
            async with create_read_write_session_manager(sample_engine)() as session:
                await repository.insert(session, 2, 20)
                raise ValueError("sample failure")
    async with create_read_only_session_manager(sample_engine)() as session:
        assert await repository.read_value(session, 2) is None


@pytest.mark.parametrize("failed_read", [False, True], ids=["success", "failed-read"])
async def test_pool_restores_read_only_connection_options(
    sample_engine: AsyncEngine,
    failed_read: bool,
) -> None:
    reads = create_read_only_session_manager(sample_engine)
    writes = create_read_write_session_manager(sample_engine)
    async with reads() as session:
        read_backend = await session.read_session.scalar(
            sa.text("SELECT pg_backend_pid()")
        )
    if failed_read:
        with pytest.raises(DBAPIError):
            async with reads() as session:
                await session.read_session.execute(
                    sa.insert(_SampleRecord).values(id=2, value=20)
                )
    async with writes() as session:
        write_backend = await session.write_session.scalar(
            sa.text("SELECT pg_backend_pid()")
        )
        assert read_backend == write_backend
        assert (
            await session.write_session.scalar(sa.text("SHOW transaction_read_only"))
            == "off"
        )
        await _SampleRepository().insert(session, 2, 20)
    # Also verify the shared unmodified engine has not inherited read-only mode.
    async with sample_engine.connect() as connection:
        assert await connection.scalar(sa.text("SHOW transaction_read_only")) == "off"
    async with reads() as session:
        assert (
            await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
            == "on"
        )
        assert await _SampleRepository().read_value(session, 2) == 20
