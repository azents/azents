"""Real PostgreSQL Runtime admission cannot invert Agent foreign-key locks."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.rdb.models.agent import RDBAgent
from azents.rdb.session_capabilities import create_read_write_session_manager
from azents.repos.agent_mutation_guard import require_active_agent
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntimeCreate
from azents.repos.agent_runtime.repository_test import _create_agent, _create_workspace
from azents.repos.agent_session import AgentSessionRepository
from azents.testing.committed_fixture_cleanup import committed_fixture_graph


@asynccontextmanager
async def _committed_agent(
    rdb_engine: AsyncEngine,
) -> AsyncIterator[AgentRuntimeCreate]:
    """Own committed fixtures needed by independent real transactions."""
    writes = create_read_write_session_manager(rdb_engine)
    suffix = uuid4().hex
    async with committed_fixture_graph(rdb_engine, RDBAgent.metadata):
        async with writes() as session:
            workspace_id = await _create_workspace(
                session, f"runtime-admission-{suffix}"
            )
            agent_id = await _create_agent(session, workspace_id, suffix)
        yield AgentRuntimeCreate(workspace_id=workspace_id, agent_id=agent_id)


@pytest.mark.parametrize("explicit_create", [False, True])
@pytest.mark.parametrize("primary_session", [False, True])
async def test_admission_then_concurrent_runtime_ensure_has_no_lock_inversion(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    explicit_create: bool,
    primary_session: bool,
) -> None:
    """Agent admission precedes Runtime uniqueness and its Agent foreign key."""
    writes = create_read_write_session_manager(rdb_engine)
    contender_pid: asyncio.Queue[int] = asyncio.Queue()
    runtime_ids: list[str] = []

    async def ensure_runtime(create: AgentRuntimeCreate) -> None:
        async with writes() as session:
            pid = await session.read_session.scalar(sa.select(sa.func.pg_backend_pid()))
            assert isinstance(pid, int)
            await contender_pid.put(pid)
            repo = AgentRuntimeRepository()
            runtime = (
                (await repo.ensure_with_create(session, create=create)).runtime
                if explicit_create
                else await repo.ensure_for_agent(session, create.agent_id)
            )
            runtime_ids.append(runtime.id)

    async with _committed_agent(rdb_engine) as create:
        async with asyncio.timeout(15), asyncio.TaskGroup() as tasks:
            async with writes() as holder:
                await require_active_agent(holder, agent_id=create.agent_id)
                tasks.create_task(ensure_runtime(create))
                pid = await contender_pid.get()
                while not await holder.read_session.scalar(
                    sa.select(sa.func.cardinality(sa.func.pg_blocking_pids(pid)) > 0)
                ):
                    pass
                # PostgreSQL now observes the contender waiting on Agent admission.
                repo = AgentRuntimeRepository()
                if primary_session:
                    ensured = (
                        await AgentSessionRepository().ensure_team_primary_for_agent(
                            holder,
                            workspace_id=create.workspace_id,
                            agent_id=create.agent_id,
                        )
                    )
                    assert ensured.created
                    runtime = await repo.get_by_agent_id(holder, create.agent_id)
                    assert runtime is not None
                else:
                    runtime = await repo.ensure_for_agent(holder, create.agent_id)
                runtime_ids.append(runtime.id)
        assert len(runtime_ids) == 2
        assert runtime_ids[0] == runtime_ids[1]


@pytest.mark.parametrize("admission", [False, True])
async def test_runtime_creator_precedes_waiting_admission_or_creation(
    rdb_engine: AsyncEngine, latest_db_schema: None, admission: bool
) -> None:
    """A waiter gets the committed canonical Runtime without a lock upgrade cycle."""
    writes = create_read_write_session_manager(rdb_engine)
    contender_pid: asyncio.Queue[int] = asyncio.Queue()
    runtime_ids: list[str] = []

    async def contend(create: AgentRuntimeCreate) -> None:
        async with writes() as session:
            pid = await session.read_session.scalar(sa.select(sa.func.pg_backend_pid()))
            assert isinstance(pid, int)
            await contender_pid.put(pid)
            if admission:
                await require_active_agent(session, agent_id=create.agent_id)
            result = await AgentRuntimeRepository().ensure_with_create(
                session, create=create
            )
            assert not result.created
            runtime_ids.append(result.runtime.id)

    async with _committed_agent(rdb_engine) as create:
        async with asyncio.timeout(15), asyncio.TaskGroup() as tasks:
            async with writes() as holder:
                runtime = await AgentRuntimeRepository().ensure_for_agent(
                    holder, create.agent_id
                )
                runtime_ids.append(runtime.id)
                tasks.create_task(contend(create))
                pid = await contender_pid.get()
                while not await holder.read_session.scalar(
                    sa.select(sa.func.cardinality(sa.func.pg_blocking_pids(pid)) > 0)
                ):
                    pass
        assert len(runtime_ids) == 2
        assert runtime_ids[0] == runtime_ids[1]
