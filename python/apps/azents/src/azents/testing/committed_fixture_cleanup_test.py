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


async def test_cleanup_collects_fk_graph_and_logical_purge_audit_rows(
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
            job_id = uuid4().hex
            await raw.execute(
                sa.insert(metadata.tables["archived_session_purge_jobs"]).values(
                    id=job_id,
                    root_session_id=conversation.id,
                    eligible_at=sa.func.now(),
                    policy_revision=1,
                )
            )
            await raw.execute(
                sa.insert(
                    metadata.tables["archived_session_purge_participant_executions"]
                ).values(
                    purge_job_id=job_id,
                    participant_key="session.routine",
                    policy_version=1,
                )
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
        jobs = metadata.tables["archived_session_purge_jobs"]
        executions = metadata.tables["archived_session_purge_participant_executions"]
        assert (
            await connection.scalar(sa.select(jobs.c.id).where(jobs.c.id == job_id))
            is None
        )
        assert (
            await connection.scalar(
                sa.select(executions.c.purge_job_id).where(
                    executions.c.purge_job_id == job_id
                )
            )
            is None
        )
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
