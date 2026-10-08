"""PostgreSQL proofs for independent descriptions and critical hierarchy groups."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import sqlalchemy as sa
from psycopg.errors import DeadlockDetected
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.agent_session_data import (
    AgentSession,
    AgentSessionCreate,
    SessionAgent,
)
from azents.core.enums import (
    AgentRunStatus,
    AgentRuntimeCapability,
    AgentSessionProductMode,
)
from azents.core.session_execution_data import SessionExecutionRecord
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_mailbox import AgentMailboxRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task.tool_operations import (
    ScheduledTaskToolOperationRepository,
)
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.repos.subagent_coordination.repository import SubagentCoordinationRepository
from azents.repos.subagent_tool_operations import SubagentToolOperationRepository
from azents.repos.terminal_finalization import TerminalRunFinalizationRepository
from azents.repos.terminal_finalization_data import TerminalDeliveryDisposition
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.worker_session import WorkerSessionOperationRepository
from azents.worker.session.idle_continuation_lock_test import (
    _cleanup_workspace_fixture,
    _wait_for_database_blocker,
)


class _PausedChildLocks(AgentSessionRepository):
    """Release one real blocking child acquisition at an observed test boundary."""

    def __init__(self, child_session_id: str) -> None:
        self.child_session_id = child_session_id
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    async def lock_by_id(
        self,
        session: WriteSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        if agent_session_id == self.child_session_id:
            self.reached.set()
            await self.release.wait()
        return await super().lock_by_id(session, agent_session_id)


@dataclasses.dataclass(frozen=True)
class _PausedTerminalOwner(WorkerSessionOperationRepository):
    """Observe the actual owned terminal method before dependent parent delivery."""

    fenced: asyncio.Event
    release: asyncio.Event

    async def _lock_owned_session(
        self,
        session: WriteSession,
        *,
        session_id: str,
        owner_generation: int,
    ) -> SessionExecutionRecord:
        current = await super()._lock_owned_session(
            session, session_id=session_id, owner_generation=owner_generation
        )
        self.fenced.set()
        await self.release.wait()
        return current


@dataclasses.dataclass(frozen=True)
class _HierarchyFixture:
    workspace_id: str
    agent_id: str
    root: AgentSession
    root_node: SessionAgent
    child: SessionAgent
    manager: SessionManager[WriteSession]
    sessions: AgentSessionRepository
    backend_pid: asyncio.Future[int]

    def subagent_operations(self) -> SubagentToolOperationRepository:
        return SubagentToolOperationRepository(
            session_manager=self.manager,
            agent_repository=AgentRepository(),
            agent_session_repository=self.sessions,
            agent_run_repository=AgentRunRepository(),
            event_transcript_repository=EventTranscriptRepository(),
            mailbox_repository=MailboxRepository(),
            source_repository=ModelMetadataSourceRepository(),
            coordination_repository=SubagentCoordinationRepository(),
            owner=SessionExecutionOwner(self.root.id, self.root.owner_generation),
        )

    def scheduled_operations(
        self, *, owned: bool
    ) -> ScheduledTaskToolOperationRepository:
        return ScheduledTaskToolOperationRepository(
            session_manager=self.manager,
            task_repository=ScheduledTaskRepository(),
            cycle_repository=ScheduledTaskCycleRepository(ToolkitStateRepository()),
            mailbox_repository=MailboxRepository(),
            run_repository=AgentRunRepository(),
            owner=(
                SessionExecutionOwner(self.root.id, self.root.owner_generation)
                if owned
                else None
            ),
        )


@pytest.fixture
async def hierarchy(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> AsyncIterator[_HierarchyFixture]:
    del latest_db_schema
    suffix = uuid4().hex[:8]
    sessions = AgentSessionRepository()
    async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
        scope = ReadWriteSession(raw)
        workspace_id = await _create_workspace(scope, f"hierarchy-fences-{suffix}")
        agent_id = await _create_agent(
            scope,
            workspace_id,
            f"hierarchy-fences-{suffix}",
            runtime_capability=AgentRuntimeCapability.NONE,
        )
        root = await sessions.create(
            scope,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        root_node = await sessions.get_session_agent_by_session_id(scope, root.id)
        assert root_node is not None
        child = await sessions.create_child_session_agent(
            scope,
            parent_session_agent_id=root_node.id,
            name="child",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        await raw.commit()
    backend_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            pid = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            if not backend_pid.done():
                backend_pid.set_result(pid)
            try:
                yield ReadWriteSession(raw)
                await raw.commit()
            except BaseException:
                await raw.rollback()
                raise

    try:
        yield _HierarchyFixture(
            workspace_id,
            agent_id,
            root,
            root_node,
            child,
            manager,
            sessions,
            backend_pid,
        )
    finally:
        await _cleanup_workspace_fixture(rdb_engine, workspace_id)


async def test_tool_descriptions_do_not_wait_for_owner_agent_or_root_gate(
    rdb_engine: AsyncEngine,
    hierarchy: _HierarchyFixture,
) -> None:
    async with AsyncSession(rdb_engine) as holder:
        await holder.execute(
            sa.select(RDBAgent)
            .where(RDBAgent.id == hierarchy.agent_id)
            .with_for_update()
        )
        await holder.execute(
            sa.select(RDBSessionAgent)
            .where(RDBSessionAgent.id == hierarchy.root_node.id)
            .with_for_update()
        )
        await holder.execute(
            sa.select(RDBAgentSession)
            .where(RDBAgentSession.id == hierarchy.root.id)
            .with_for_update()
        )
        snapshot = await asyncio.wait_for(
            hierarchy.subagent_operations().list_agents(
                session_id=hierarchy.root.id,
                configured_capacity=3,
            ),
            timeout=5,
        )
        assert snapshot is not None
        tasks = await asyncio.wait_for(
            hierarchy.scheduled_operations(owned=True).list_tasks(
                agent_id=hierarchy.agent_id,
                session_id=hierarchy.root.id,
            ),
            timeout=5,
        )
        assert tasks == []
        async with hierarchy.manager() as scope:
            ids = await asyncio.wait_for(
                hierarchy.sessions.list_session_agent_subtree_session_ids(
                    scope,
                    agent_session_id=hierarchy.root.id,
                ),
                timeout=5,
            )
            assert set(ids) == {hierarchy.root.id, hierarchy.child.agent_session_id}


@pytest.mark.parametrize("victim", ["parent", "terminal"])
async def test_real_deadlock_retries_whole_parent_or_terminal_operation_once(
    rdb_engine: AsyncEngine,
    hierarchy: _HierarchyFixture,
    victim: str,
) -> None:
    """Either real DB victim rolls back its owning method, not external execution."""
    runs = AgentRunRepository()
    async with hierarchy.manager() as scope:
        pending = await runs.create_pending(
            scope,
            session_id=hierarchy.child.agent_session_id,
            parent_agent_run_id=None,
            scheduled_task_cycle_id=None,
        )
    pids: dict[str, int] = {}
    attempts: dict[str, int] = {}
    aborts: list[str] = []

    @asynccontextmanager
    async def tracked_manager() -> AsyncIterator[WriteSession]:
        task = asyncio.current_task()
        assert task is not None
        role = task.get_name()
        assert role in {"parent", "terminal"}
        attempts[role] = attempts.get(role, 0) + 1
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            pid = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            pids[role] = pid
            # Select the detector in this isolated test, not a product lock timeout.
            # The actual cycle, rollback and both completed operations remain real.
            detector = "100ms" if role == victim else "5s"
            await raw.execute(
                sa.text("SELECT set_config('deadlock_timeout', :value, true)"),
                {"value": detector},
            )
            try:
                yield ReadWriteSession(raw)
                await raw.commit()
            except BaseException as error:
                await raw.rollback()
                if isinstance(error, OperationalError) and isinstance(
                    error.orig, DeadlockDetected
                ):
                    aborts.append(role)
                raise

    sessions = _PausedChildLocks(hierarchy.child.agent_session_id)
    operations = dataclasses.replace(
        hierarchy.subagent_operations(),
        session_manager=tracked_manager,
        agent_session_repository=sessions,
    )
    admission = MailboxAdmissionRepository(
        tracked_manager, MailboxRepository(), sessions
    )
    terminal = TerminalRunFinalizationRepository(
        tracked_manager,
        runs,
        sessions,
        AgentMailboxRepository(admission, sessions),
    )
    child_fenced = asyncio.Event()
    child_release = asyncio.Event()
    worker = _PausedTerminalOwner(
        tracked_manager,
        sessions,
        runs,
        MailboxRepository(),
        terminal,
        SessionExecutionRecordRepository(),
        child_fenced,
        child_release,
    )
    parent_task: asyncio.Task[object] | None = None
    terminal_task: asyncio.Task[object] | None = None
    try:
        terminal_task = asyncio.create_task(
            worker.cancel_pending_agent_run(
                hierarchy.child.agent_session_id, owner_generation=0, run_id=pending.id
            ),
            name="terminal",
        )
        await asyncio.wait_for(child_fenced.wait(), timeout=5)
        parent_task = asyncio.create_task(
            operations.send_message(
                session_id=hierarchy.root.id, agent_name="child", content="next message"
            ),
            name="parent",
        )
        await asyncio.wait_for(sessions.reached.wait(), timeout=5)
        if victim == "parent":
            sessions.release.set()
            await asyncio.wait_for(
                _wait_for_database_blocker(
                    rdb_engine, blocked_pid=pids["parent"], blocker_pid=pids["terminal"]
                ),
                timeout=5,
            )
            child_release.set()
        else:
            child_release.set()
            await asyncio.wait_for(
                _wait_for_database_blocker(
                    rdb_engine, blocked_pid=pids["terminal"], blocker_pid=pids["parent"]
                ),
                timeout=5,
            )
            sessions.release.set()
        results = await asyncio.wait_for(
            asyncio.gather(parent_task, terminal_task), timeout=10
        )
        assert results[0].target is not None
        assert results[1].status is AgentRunStatus.CANCELLED
        assert aborts == [victim]
        assert attempts == {
            "parent": 2 if victim == "parent" else 1,
            "terminal": 2 if victim == "terminal" else 1,
        }
        async with hierarchy.manager() as scope:
            parent_messages = await MailboxRepository().list_by_session_id(
                scope, hierarchy.root.id
            )
            child_messages = await MailboxRepository().list_by_session_id(
                scope, hierarchy.child.agent_session_id
            )
            assert len(parent_messages) == 1
            assert len(child_messages) == 1
            committed = await runs.get_by_id(scope, pending.id)
            assert committed is not None
            assert committed.status is AgentRunStatus.CANCELLED
            assert committed.session_id == hierarchy.child.agent_session_id
            repeated = await terminal.finalize_run_in_session(scope, run_id=pending.id)
            assert repeated.disposition is TerminalDeliveryDisposition.ALREADY_FINALIZED
    finally:
        tasks = [task for task in (parent_task, terminal_task) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("cancelled", [False, True])
async def test_waiting_message_commits_once_or_cancel_releases_partial_parent(
    rdb_engine: AsyncEngine,
    hierarchy: _HierarchyFixture,
    cancelled: bool,
) -> None:
    """Waiting is ordinary admission; cancellation rolls back earlier parent locks."""
    task: asyncio.Task[object] | None = None
    try:
        async with AsyncSession(rdb_engine) as holder:
            await holder.execute(
                sa.select(RDBAgentSession)
                .where(RDBAgentSession.id == hierarchy.child.agent_session_id)
                .with_for_update()
            )
            holder_pid = await holder.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(holder_pid, int)
            task = asyncio.create_task(
                hierarchy.subagent_operations().send_message(
                    session_id=hierarchy.root.id,
                    agent_name="child",
                    content="waited message",
                )
            )
            pid = await asyncio.wait_for(hierarchy.backend_pid, timeout=5)
            await asyncio.wait_for(
                _wait_for_database_blocker(
                    rdb_engine, blocked_pid=pid, blocker_pid=holder_pid
                ),
                timeout=5,
            )
            if cancelled:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=5)
                # The child remains held; acquiring the earlier parent proves
                # cancellation released the complete owning transaction.
                async with AsyncSession(rdb_engine) as verifier:
                    locked = await asyncio.wait_for(
                        hierarchy.sessions.lock_by_id(
                            ReadWriteSession(verifier), hierarchy.root.id
                        ),
                        timeout=5,
                    )
                    assert locked is not None
            else:
                await holder.commit()
                assert (await asyncio.wait_for(task, timeout=5)).target is not None
        async with hierarchy.manager() as scope:
            messages = await MailboxRepository().list_by_session_id(
                scope, hierarchy.child.agent_session_id
            )
            assert len(messages) == (0 if cancelled else 1)
            root = await hierarchy.sessions.get_by_id(scope, hierarchy.root.id)
            assert root is not None
            assert root.owner_generation == hierarchy.root.owner_generation
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_obsolete_parent_tool_cannot_commit_after_owner_handover(
    rdb_engine: AsyncEngine,
    hierarchy: _HierarchyFixture,
) -> None:
    task: asyncio.Task[object] | None = None
    try:
        async with AsyncSession(rdb_engine) as holder:
            await holder.execute(
                sa.update(RDBAgentSession)
                .where(RDBAgentSession.id == hierarchy.root.id)
                .values(owner_generation=RDBAgentSession.owner_generation + 1)
            )
            holder_pid = await holder.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(holder_pid, int)
            task = asyncio.create_task(
                hierarchy.subagent_operations().send_message(
                    session_id=hierarchy.root.id,
                    agent_name="child",
                    content="obsolete",
                )
            )
            pid = await asyncio.wait_for(hierarchy.backend_pid, timeout=5)
            await asyncio.wait_for(
                _wait_for_database_blocker(
                    rdb_engine, blocked_pid=pid, blocker_pid=holder_pid
                ),
                timeout=5,
            )
            await holder.commit()
            with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
                await asyncio.wait_for(task, timeout=5)
        async with hierarchy.manager() as scope:
            assert (
                await MailboxRepository().list_by_session_id(
                    scope, hierarchy.child.agent_session_id
                )
                == []
            )
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("owned", [True, False])
async def test_task_creation_waits_for_archive_then_rejects_archived_target(
    rdb_engine: AsyncEngine,
    hierarchy: _HierarchyFixture,
    owned: bool,
) -> None:
    task: asyncio.Task[object] | None = None
    try:
        async with AsyncSession(rdb_engine) as holder:
            scope = ReadWriteSession(holder)
            tree = await hierarchy.sessions.lock_root_tree_sessions(
                scope, root_session_id=hierarchy.root.id
            )
            now = datetime.datetime.now(datetime.UTC)
            await hierarchy.sessions.archive_tree(
                scope,
                root_session_id=hierarchy.root.id,
                session_ids=[item.id for item in tree],
                archived_at=now,
                purge_after=None,
                policy_revision=1,
                retention_days=None,
            )
            holder_pid = await holder.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(holder_pid, int)
            task = asyncio.create_task(
                hierarchy.scheduled_operations(owned=owned).create(
                    workspace_id=hierarchy.workspace_id,
                    agent_id=hierarchy.agent_id,
                    session_id=hierarchy.root.id,
                    title="late task",
                    objective="too late",
                    at=(now + datetime.timedelta(days=1)).isoformat(),
                    cron=None,
                    timezone=None,
                    binding_id=None,
                    now=now,
                )
            )
            pid = await asyncio.wait_for(hierarchy.backend_pid, timeout=5)
            await asyncio.wait_for(
                _wait_for_database_blocker(
                    rdb_engine,
                    blocked_pid=pid,
                    blocker_pid=holder_pid,
                ),
                timeout=5,
            )
            await holder.commit()
            with pytest.raises(ValueError, match="target Session is not active"):
                await asyncio.wait_for(task, timeout=5)
        async with hierarchy.manager() as scope:
            assert (
                await ScheduledTaskRepository().list_by_session_id(
                    scope, hierarchy.root.id
                )
                == []
            )
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
