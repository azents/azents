"""Existing-history displacement backfill and migration rollback coverage."""

import asyncio
import datetime
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from azents.rdb.session_capabilities import ReadWriteSession
from azents.services.archived_session_retention_test import _create_root


async def test_existing_history_recovers_first_displacement(
    rdb_engine: AsyncEngine,
) -> None:
    database_name = "compacted_retention_" + uuid4().hex[:12]
    url = rdb_engine.url.set(database=database_name)
    async with rdb_engine.connect() as connection:
        transactionless = await connection.execution_options(
            isolation_level="AUTOCOMMIT"
        )
        await transactionless.execute(sa.text(f'CREATE DATABASE "{database_name}"'))
    engine = create_async_engine(url)
    project = Path(__file__).resolve().parents[4]
    config = AlembicConfig(str(project / "db-schemas/rdb/alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    first_at = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    second_at = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
    try:
        await asyncio.to_thread(command.upgrade, config, "d4bf6286235d")
        async with AsyncSession(engine, expire_on_commit=False) as raw:
            session_id = await _create_root(ReadWriteSession(raw), suffix="migration")
            for ordinal, kind, created_at in (
                (1, "user_message", first_at - datetime.timedelta(days=100)),
                (2, "compaction_summary", first_at),
                (3, "user_message", first_at - datetime.timedelta(days=100)),
                (4, "compaction_summary", second_at),
                (5, "user_message", second_at),
            ):
                await raw.execute(
                    sa.text(
                        "INSERT INTO events(id,session_id,kind,payload,created_at) "
                        "VALUES (:id,:session_id,CAST(:kind AS event_kind),"
                        "'{}',:created_at)"
                    ),
                    {
                        "id": str(ordinal) * 32,
                        "session_id": session_id,
                        "kind": kind,
                        "created_at": created_at,
                    },
                )
            await raw.execute(
                sa.text(
                    "UPDATE agent_sessions SET model_input_head_event_id=:head "
                    "WHERE id=:session_id"
                ),
                {"head": "4" * 32, "session_id": session_id},
            )
            await raw.commit()
        await asyncio.to_thread(command.upgrade, config, "042a6603f202")
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text("SELECT id,compacted_at FROM events ORDER BY id")
                )
            ).all()
            assert {event_id: compacted_at for event_id, compacted_at in rows} == {
                "1" * 32: first_at,
                "2" * 32: second_at,
                "3" * 32: second_at,
                "4" * 32: None,
                "5" * 32: None,
            }
            assert (
                await connection.execute(
                    sa.text(
                        "SELECT compacted_event_retention_days "
                        "FROM system_file_lifecycle_settings"
                    )
                )
            ).scalar_one() is None
        await asyncio.to_thread(command.downgrade, config, "d4bf6286235d")
        async with engine.connect() as connection:
            assert (
                await connection.execute(sa.text("SELECT count(*) FROM events"))
            ).scalar_one() == 5
            assert (
                await connection.execute(
                    sa.text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name='events' AND column_name='compacted_at'"
                    )
                )
            ).scalar_one() == 0
    finally:
        await engine.dispose()
        async with rdb_engine.connect() as connection:
            transactionless = await connection.execution_options(
                isolation_level="AUTOCOMMIT"
            )
            await transactionless.execute(
                sa.text(f'DROP DATABASE "{database_name}" WITH (FORCE)')
            )
