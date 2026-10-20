"""Active-Agent admission rejects writes even after a stale authorization read."""

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.agent_mutation import AgentMutationReadOnly, AgentMutationTargetMissing
from azents.core.enums import AgentLifecycleStatus
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent_mutation_guard import require_active_agent
from azents.repos.agent_runtime_removal.repository_test import _create_agent


@pytest.mark.asyncio
async def test_guard_rechecks_canonical_lifecycle(rdb_session: WriteSession) -> None:
    fixture = await _create_agent(rdb_session)
    repository = AgentRepository()
    authorized_before = await repository.get_by_id(rdb_session, fixture.agent_id)
    assert authorized_before is not None
    await require_active_agent(rdb_session, agent_id=fixture.agent_id)
    await repository.mark_decommissioning(rdb_session, fixture.agent_id)
    with pytest.raises(AgentMutationReadOnly):
        await require_active_agent(rdb_session, agent_id=authorized_before.id)


@pytest.mark.asyncio
async def test_guard_rejects_disappeared_target(rdb_session: WriteSession) -> None:
    with pytest.raises(AgentMutationTargetMissing):
        await require_active_agent(rdb_session, agent_id="missing-agent")


@pytest.mark.asyncio
async def test_deletion_wins_against_previously_authorized_mutation(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    async with writes() as session:
        fixture = await _create_agent(session)
    contender_pid: asyncio.Queue[int] = asyncio.Queue()

    async def mutate_after_stale_read() -> None:
        async with writes() as session:
            stale = await AgentRepository().get_by_id(session, fixture.agent_id)
            assert stale is not None
            assert stale.lifecycle_status is AgentLifecycleStatus.ACTIVE
            pid = await session.read_session.scalar(sa.select(sa.func.pg_backend_pid()))
            assert isinstance(pid, int)
            await contender_pid.put(pid)
            with pytest.raises(AgentMutationReadOnly):
                await require_active_agent(session, agent_id=stale.id)

    try:
        async with asyncio.timeout(10), asyncio.TaskGroup() as tasks:
            async with writes() as session:
                await AgentRepository().mark_decommissioning(session, fixture.agent_id)
                tasks.create_task(mutate_after_stale_read())
                pid = await contender_pid.get()
                while not await session.read_session.scalar(
                    sa.select(sa.func.cardinality(sa.func.pg_blocking_pids(pid)) > 0)
                ):
                    pass
                # The DB has observed a real lock waiter, not merely a scheduled task.
            # Commit releases the lock; the blocked guard now sees decommissioning.
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == fixture.agent_id)
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == fixture.workspace_id)
            )


async def test_committed_writer_precedes_waiting_deletion(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """Deletion observes the complete earlier mutation, not a partially saved row."""
    writes = create_read_write_session_manager(rdb_engine)
    async with writes() as session:
        fixture = await _create_agent(session)
    contender_pid: asyncio.Queue[int] = asyncio.Queue()

    async def delete_after_writer() -> None:
        async with writes() as session:
            pid = await session.read_session.scalar(sa.select(sa.func.pg_backend_pid()))
            assert isinstance(pid, int)
            await contender_pid.put(pid)
            result = await AgentRepository().mark_decommissioning(
                session, fixture.agent_id
            )
            assert result is not None and result.name == "Committed before deletion"

    try:
        async with asyncio.timeout(10), asyncio.TaskGroup() as tasks:
            async with writes() as session:
                await require_active_agent(session, agent_id=fixture.agent_id)
                result = await AgentRepository().update_by_id(
                    session, fixture.agent_id, {"name": "Committed before deletion"}
                )
                assert result.success
                tasks.create_task(delete_after_writer())
                pid = await contender_pid.get()
                while not await session.read_session.scalar(
                    sa.select(sa.func.cardinality(sa.func.pg_blocking_pids(pid)) > 0)
                ):
                    pass
        async with writes() as session:
            current = await AgentRepository().get_by_id(session, fixture.agent_id)
            assert current is not None
            assert current.lifecycle_status is AgentLifecycleStatus.DECOMMISSIONING
            assert current.name == "Committed before deletion"
            with pytest.raises(AgentMutationReadOnly):
                await require_active_agent(session, agent_id=fixture.agent_id)
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == fixture.agent_id)
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == fixture.workspace_id)
            )
