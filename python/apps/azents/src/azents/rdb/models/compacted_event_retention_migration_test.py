"""Existing-history displacement backfill and migration rollback coverage."""

import asyncio
import datetime
import json
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from azents.core.enums import LLMProvider
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)


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
            # Seed the historical schema directly: current ORM models can contain
            # columns introduced after this migration's predecessor.
            workspace_id, agent_id, session_id = (uuid4().hex for _ in range(3))
            selection = make_test_model_selection_dict(
                integration_id=uuid4().hex,
                provider=LLMProvider.ANTHROPIC,
                model_identifier="retention-migration",
            )
            options = make_test_selectable_model_option_dicts(
                model_selection=selection, lightweight_model_selection=selection
            )
            await raw.execute(
                sa.text(
                    "INSERT INTO workspaces(id,name,handle) "
                    "VALUES (:id,'Retention migration','retention-migration')"
                ),
                {"id": workspace_id},
            )
            await raw.execute(
                sa.text(
                    "INSERT INTO agents(id,workspace_id,name,model_selection,"
                    "lightweight_model_selection,selectable_model_options,"
                    "main_model_label,lightweight_model_label,"
                    "enabled,type,memory_enabled) "
                    "VALUES (:id,:workspace,'Retention migration',"
                    "CAST(:selection AS jsonb),CAST(:selection AS jsonb),"
                    "CAST(:options AS jsonb),"
                    "'default','lightweight',true,'public',true)"
                ),
                {
                    "id": agent_id,
                    "workspace": workspace_id,
                    "selection": json.dumps(selection),
                    "options": json.dumps(options),
                },
            )
            await raw.execute(
                sa.text(
                    "INSERT INTO agent_sessions(id,workspace_id,agent_id,"
                    "status,start_reason) "
                    "VALUES (:id,:workspace,:agent,'active','initial')"
                ),
                {"id": session_id, "workspace": workspace_id, "agent": agent_id},
            )
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
