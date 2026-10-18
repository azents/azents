"""Real PostgreSQL contracts for test-owned outer transactions and ORM scopes."""

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.testing.transaction_fixture import rollback_session_manager


@pytest_asyncio.fixture
async def probe_table(rdb_engine: AsyncEngine) -> AsyncIterator[sa.Table]:
    """Own a unique physical table independently of application fixture rows."""
    table = sa.Table(
        "pytest_transaction_probe_" + uuid4().hex[:12],
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    async with rdb_engine.begin() as connection:
        await connection.run_sync(table.create)
    try:
        yield table
    finally:
        async with rdb_engine.begin() as connection:
            await connection.run_sync(table.drop)


async def _ids(engine: AsyncEngine, table: sa.Table) -> list[int]:
    async with engine.connect() as connection:
        return list(
            await connection.scalars(sa.select(table.c.id).order_by(table.c.id))
        )


async def test_context_commit_is_visible_locally_but_outer_exit_rolls_back(
    rdb_engine: AsyncEngine, probe_table: sa.Table
) -> None:
    async with rollback_session_manager(rdb_engine) as manager:
        async with manager() as session:
            await session.write_session.execute(probe_table.insert().values(id=1))
        async with manager() as session:
            assert list(
                await session.read_session.scalars(sa.select(probe_table.c.id))
            ) == [1]
        assert await _ids(rdb_engine, probe_table) == []
    assert await _ids(rdb_engine, probe_table) == []


async def test_explicit_commit_and_rollback_do_not_end_outer_transaction(
    rdb_engine: AsyncEngine, probe_table: sa.Table
) -> None:
    async with rollback_session_manager(rdb_engine) as manager:
        async with manager() as session:
            await session.write_session.execute(probe_table.insert().values(id=1))
            await session.write_session.commit()
            await session.write_session.execute(probe_table.insert().values(id=2))
            await session.write_session.rollback()
            await session.write_session.execute(probe_table.insert().values(id=3))
        async with manager() as session:
            assert list(
                await session.read_session.scalars(
                    sa.select(probe_table.c.id).order_by(probe_table.c.id)
                )
            ) == [1, 3]
        assert await _ids(rdb_engine, probe_table) == []
    assert await _ids(rdb_engine, probe_table) == []


async def test_failed_context_rolls_back_without_discarding_prior_context(
    rdb_engine: AsyncEngine, probe_table: sa.Table
) -> None:
    async with rollback_session_manager(rdb_engine) as manager:
        async with manager() as session:
            await session.write_session.execute(probe_table.insert().values(id=1))
        with pytest.raises(RuntimeError, match="controlled failure"):
            async with manager() as session:
                await session.write_session.execute(probe_table.insert().values(id=2))
                raise RuntimeError("controlled failure")
        async with manager() as session:
            assert list(
                await session.read_session.scalars(sa.select(probe_table.c.id))
            ) == [1]
    assert await _ids(rdb_engine, probe_table) == []


async def test_cancelled_context_rolls_back_before_next_context(
    rdb_engine: AsyncEngine, probe_table: sa.Table
) -> None:
    ready = asyncio.Event()
    blocked = asyncio.Event()
    async with rollback_session_manager(rdb_engine) as manager:

        async def write_then_wait() -> None:
            async with manager() as session:
                await session.write_session.execute(probe_table.insert().values(id=1))
                ready.set()
                await blocked.wait()

        task = asyncio.create_task(write_then_wait())
        try:
            await asyncio.wait_for(ready.wait(), timeout=5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        async with manager() as session:
            assert (
                list(await session.read_session.scalars(sa.select(probe_table.c.id)))
                == []
            )
            await session.write_session.execute(probe_table.insert().values(id=2))
        assert await _ids(rdb_engine, probe_table) == []
    assert await _ids(rdb_engine, probe_table) == []


async def test_each_orm_context_owns_only_one_savepoint(
    rdb_engine: AsyncEngine, probe_table: sa.Table
) -> None:
    statements: list[str] = []

    def observe(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement)

    event.listen(rdb_engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with rollback_session_manager(rdb_engine) as manager:
            for identity in (1, 2):
                async with manager() as session:
                    await session.write_session.execute(
                        probe_table.insert().values(id=identity)
                    )
    finally:
        event.remove(rdb_engine.sync_engine, "before_cursor_execute", observe)
    assert sum(sql.startswith("SAVEPOINT ") for sql in statements) == 2
    assert sum(sql.startswith("RELEASE SAVEPOINT ") for sql in statements) == 2
    assert await _ids(rdb_engine, probe_table) == []
