"""Exact graph cleanup preserves incoming non-primary foreign-key identities."""

from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import AgentSessionProductMode
from azents.rdb.session_capabilities import ReadWriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.testing.committed_fixture_cleanup import committed_fixture_graph


async def test_cleanup_follows_composite_fk_referencing_non_primary_status(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """A committed profile graph is collected without discarding its FK status."""
    del latest_db_schema
    metadata = sa.MetaData()
    async with rdb_engine.connect() as connection:
        await connection.run_sync(metadata.reflect)
    suffix = uuid4().hex[:12]
    async with committed_fixture_graph(rdb_engine, metadata):
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            session = ReadWriteSession(raw)
            workspace_id = await _create_workspace(session, f"graph-{suffix}")
            agent_id = await _create_agent(session, workspace_id, f"graph-{suffix}")
            conversation = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    product_mode=AgentSessionProductMode.TEAM,
                    associated_user_id=None,
                    title=None,
                ),
            )
            await raw.commit()
        async with rdb_engine.connect() as connection:
            assert (
                await connection.scalar(
                    sa.select(metadata.tables["conversations"].c.session_id).where(
                        metadata.tables["conversations"].c.session_id == conversation.id
                    )
                )
                == conversation.id
            )
    async with rdb_engine.connect() as connection:
        assert (
            await connection.scalar(
                sa.select(metadata.tables["workspaces"].c.id).where(
                    metadata.tables["workspaces"].c.id == workspace_id
                )
            )
            is None
        )
        assert (
            await connection.scalar(
                sa.select(metadata.tables["agent_sessions"].c.id).where(
                    metadata.tables["agent_sessions"].c.id == conversation.id
                )
            )
            is None
        )
