"Existing-data migration preserves Conversation and execution identities."

import asyncio
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from azents.core.enums import (
    SessionAgentKind,
    SessionWorkingFolderBindingState,
    SessionWorkingFolderCleanupStatus,
)
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.session_capabilities import ReadWriteSession
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace


async def test_existing_conversation_backfill_keeps_common_ids_and_child_group(
    rdb_engine: AsyncEngine,
) -> None:
    "Upgrade an isolated pre-extraction DB containing real root/child records."
    database_name = "conversation_migration_" + uuid4().hex[:12]
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
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    try:
        await asyncio.to_thread(command.upgrade, config, "a332f5e0f329")
        async with AsyncSession(engine, expire_on_commit=False) as raw:
            session = ReadWriteSession(raw)
            suffix = uuid4().hex[:10]
            workspace_id = await _create_workspace(session, f"migration-{suffix}")
            agent_id = await _create_agent(session, workspace_id, f"migration-{suffix}")
            root_id, child_id = uuid4().hex, uuid4().hex
            for session_id, handle, kind, product_mode, title in (
                (root_id, "migration-root", "root", "team", "Original root title"),
                (child_id, "migration-child", "subagent", None, "Original child"),
            ):
                await raw.execute(
                    sa.text(
                        (
                            "INSERT INTO agent_sessions "
                            "(id,workspace_id,agent_id,handle,session_kind,"
                            "product_mode,title,pinned,status,start_reason) "
                            "VALUES (:id,:workspace,:agent,:handle,:kind,"
                            ":mode,:title,:pinned,'active','initial')"
                        )
                    ),
                    {
                        "id": session_id,
                        "workspace": workspace_id,
                        "agent": agent_id,
                        "handle": handle,
                        "kind": kind,
                        "mode": product_mode,
                        "title": title,
                        "pinned": session_id == root_id,
                    },
                )
            context = RDBSessionAgentContext(
                agent_id=agent_id,
                workspace_id=workspace_id,
                agent_runtime_id=None,
                working_folder_path=None,
                working_folder_binding_state=SessionWorkingFolderBindingState.NONE,
                working_folder_cleanup_status=SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED,
                working_folder_cleanup_summary=None,
                working_folder_cleanup_completed_at=None,
            )
            raw.add(context)
            await raw.flush()
            root_node_id = uuid4().hex
            root_node = RDBSessionAgent(
                context_id=context.id,
                root_session_agent_id=root_node_id,
                agent_session_id=root_id,
                kind=SessionAgentKind.ROOT,
                name="root",
                path="/root",
                agent_type="default",
                parent_session_agent_id=None,
            )
            root_node.id = root_node_id
            raw.add(root_node)
            await raw.flush()
            context.root_session_agent_id = root_node.id
            raw.add(
                RDBSessionAgent(
                    context_id=context.id,
                    root_session_agent_id=root_node.id,
                    agent_session_id=child_id,
                    kind=SessionAgentKind.SUBAGENT,
                    name="child",
                    path="/root/child",
                    agent_type="default",
                    parent_session_agent_id=root_node.id,
                )
            )
            event_id = uuid4().hex
            await raw.execute(
                sa.text(
                    (
                        "INSERT INTO events(id,session_id,kind,payload) VALUES "
                        "(:id,:session,'assistant_message','{\"content\":\"kept\"}'::jsonb)"
                    )
                ),
                {"id": event_id, "session": root_id},
            )
            await raw.commit()
        await asyncio.to_thread(command.upgrade, config, "6a05f4a01f6f")
        async with engine.connect() as connection:
            root = (
                (
                    await connection.execute(
                        sa.text(
                            (
                                "SELECT "
                                "s.id,s.lifecycle_root_session_id,c.handle,"
                                "c.title,c.pinned "
                                "FROM agent_sessions s JOIN conversations c ON "
                                "c.session_id=s.id WHERE s.id=:id"
                            )
                        ),
                        {"id": root_id},
                    )
                )
                .mappings()
                .one()
            )
            assert root["id"] == root_id
            assert root["lifecycle_root_session_id"] is None
            assert root["handle"] == "migration-root"
            assert root["title"] == "Original root title"
            assert root["pinned"] is True
            index_definition = await connection.scalar(
                sa.text("SELECT indexdef FROM pg_indexes WHERE indexname=:name"),
                {"name": "ix_agent_sessions_lifecycle_root_session_id"},
            )
            assert isinstance(index_definition, str)
            assert "lifecycle_root_session_id IS NOT NULL" in index_definition
            assert (
                await connection.scalar(
                    sa.text(
                        "SELECT lifecycle_root_session_id FROM agent_sessions "
                        "WHERE id=:id"
                    ),
                    {"id": child_id},
                )
                == root_id
            )
            assert (
                await connection.scalar(
                    sa.text("SELECT session_id FROM events WHERE id=:id"),
                    {"id": event_id},
                )
                == root_id
            )
            assert (
                await connection.scalar(
                    sa.text(
                        (
                            "SELECT count(*) FROM information_schema.columns WHERE "
                            "table_name='agent_sessions' AND column_name IN "
                            "('handle','title','pinned')"
                        )
                    )
                )
                == 0
            )
    finally:
        await engine.dispose()
        async with rdb_engine.connect() as connection:
            transactionless = await connection.execution_options(
                isolation_level="AUTOCOMMIT"
            )
            await transactionless.execute(sa.text(f'DROP DATABASE "{database_name}"'))
