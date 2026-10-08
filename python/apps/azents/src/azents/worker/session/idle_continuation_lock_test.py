"""Real PostgreSQL observation and exact idle-finalization contention tests."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import AgentRuntimeCapability, AgentSessionProductMode
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.idle_continuation import IdleContinuationRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.toolkit_state import ToolkitStateRepository


async def _cleanup_workspace_fixture(engine: AsyncEngine, workspace_id: str) -> None:
    """Remove only this fixture in the existing restrictive FK order."""
    async with AsyncSession(engine) as cleanup:
        context_ids = sa.select(RDBSessionAgentContext.id).where(
            RDBSessionAgentContext.workspace_id == workspace_id
        )
        await cleanup.execute(
            sa.update(RDBSessionAgentContext)
            .where(RDBSessionAgentContext.workspace_id == workspace_id)
            .values(root_session_agent_id=None)
        )
        await cleanup.execute(
            sa.delete(RDBSessionAgent).where(
                RDBSessionAgent.context_id.in_(context_ids)
            )
        )
        await cleanup.execute(
            sa.delete(RDBSessionAgentContext).where(
                RDBSessionAgentContext.workspace_id == workspace_id
            )
        )
        await cleanup.execute(
            sa.delete(RDBAgentSession).where(
                RDBAgentSession.workspace_id == workspace_id
            )
        )
        await cleanup.execute(
            sa.delete(RDBAgent).where(RDBAgent.workspace_id == workspace_id)
        )
        await cleanup.execute(
            sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
        )
        await cleanup.commit()


async def _wait_for_database_blocker(
    engine: AsyncEngine, *, blocked_pid: int, blocker_pid: int
) -> None:
    """Observe an actual lock dependency rather than scheduler timing."""
    async with AsyncSession(engine) as observer:
        while not await observer.scalar(
            sa.text("SELECT :blocker_pid = ANY(pg_blocking_pids(:blocked_pid))"),
            {"blocker_pid": blocker_pid, "blocked_pid": blocked_pid},
        ):
            pass


@pytest.mark.asyncio
async def test_idle_description_does_not_wait_for_held_owner_or_hierarchy_rows(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """A pre-hook eligibility view is independent of all prior execution gates."""
    del latest_db_schema
    suffix = uuid4().hex[:8]
    sessions = AgentSessionRepository()
    async with AsyncSession(rdb_engine, expire_on_commit=False) as raw_setup:
        setup = ReadWriteSession(raw_setup)
        workspace_id = await _create_workspace(setup, f"idle-read-{suffix}")
        agent_id = await _create_agent(
            setup,
            workspace_id,
            f"idle-read-{suffix}",
            runtime_capability=AgentRuntimeCapability.NONE,
        )
        root = await sessions.create(
            setup,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        await raw_setup.commit()

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            try:
                yield ReadWriteSession(raw)
                await raw.commit()
            except BaseException:
                await raw.rollback()
                raise

    repository = IdleContinuationRepository(
        manager,
        sessions,
        AgentRunRepository(),
        MailboxRepository(),
        ScheduledTaskCycleRepository(ToolkitStateRepository()),
    )
    try:
        async with AsyncSession(rdb_engine) as holder:
            await holder.execute(
                sa.select(RDBAgent).where(RDBAgent.id == agent_id).with_for_update()
            )
            await holder.execute(
                sa.select(RDBSessionAgent)
                .where(RDBSessionAgent.agent_session_id == root.id)
                .with_for_update()
            )
            await holder.execute(
                sa.select(RDBAgentSession)
                .where(RDBAgentSession.id == root.id)
                .with_for_update()
            )
            result = await asyncio.wait_for(
                repository.get_eligibility(
                    root.id,
                    "0" * 32,
                    owner_generation=root.owner_generation,
                ),
                timeout=5,
            )
            assert not result.eligible
            assert result.archived_cycle_id is None
    finally:
        await _cleanup_workspace_fixture(rdb_engine, workspace_id)


@pytest.mark.asyncio
async def test_idle_finalization_waits_for_exact_owner_handover_then_rejects(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """An obsolete finalizer cannot admit work after a concurrent owner commit."""
    del latest_db_schema
    suffix = uuid4().hex[:8]
    sessions = AgentSessionRepository()
    async with AsyncSession(rdb_engine, expire_on_commit=False) as raw_setup:
        setup = ReadWriteSession(raw_setup)
        workspace_id = await _create_workspace(setup, f"idle-fence-{suffix}")
        agent_id = await _create_agent(
            setup,
            workspace_id,
            f"idle-fence-{suffix}",
            runtime_capability=AgentRuntimeCapability.NONE,
        )
        root = await sessions.create(
            setup,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        await raw_setup.commit()

    finalizer_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            pid = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            finalizer_pid.set_result(pid)
            try:
                yield ReadWriteSession(raw)
                await raw.commit()
            except BaseException:
                await raw.rollback()
                raise

    repository = IdleContinuationRepository(
        manager,
        sessions,
        AgentRunRepository(),
        MailboxRepository(),
        ScheduledTaskCycleRepository(ToolkitStateRepository()),
    )
    task: asyncio.Task[object] | None = None
    try:
        async with AsyncSession(rdb_engine) as holder:
            await holder.execute(
                sa.update(RDBAgentSession)
                .where(RDBAgentSession.id == root.id)
                .values(owner_generation=RDBAgentSession.owner_generation + 1)
            )
            holder_pid = await holder.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(holder_pid, int)
            task = asyncio.create_task(
                repository.finalize(
                    session_id=root.id,
                    run_id="0" * 32,
                    owner_generation=root.owner_generation,
                    inputs=[],
                )
            )
            pid = await asyncio.wait_for(finalizer_pid, timeout=5)
            await asyncio.wait_for(
                _wait_for_database_blocker(
                    rdb_engine,
                    blocked_pid=pid,
                    blocker_pid=holder_pid,
                ),
                timeout=5,
            )
            await holder.commit()
            with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
                await asyncio.wait_for(task, timeout=5)
        async with AsyncSession(rdb_engine) as verifier:
            assert (
                await MailboxRepository().list_by_session_id(
                    ReadWriteSession(verifier), root.id
                )
                == []
            )
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await _cleanup_workspace_fixture(rdb_engine, workspace_id)
