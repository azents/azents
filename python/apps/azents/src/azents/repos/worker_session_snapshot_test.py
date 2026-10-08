"""Bounded PostgreSQL proof for the completed unlocked canonical snapshot wrapper."""

import asyncio
import dataclasses
import datetime
from typing import Literal

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRunStatus,
    AgentSessionKind,
    AgentSessionRunState,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
    CanonicalExecutionSnapshotError,
    SessionExecutionRepository,
)
from azents.repos.session_execution.data import CanonicalExecutionSnapshot
from azents.repos.session_execution.repository_test import (
    _archive_with_scheduled_continuation,
    _create_execution_subject,
)
from azents.repos.worker_session_recovery_test import ObservedReadManager
from azents.repos.worker_session_snapshot import (
    WorkerSessionSnapshotOperationRepository,
)


class _ObservedProjection(SessionExecutionRepository):
    """Execute canonical SQL with a same-Session and unlocked-read witness."""

    def __init__(
        self, manager: ObservedReadManager, error: BaseException | None
    ) -> None:
        self.manager = manager
        self.error = error
        self.calls: list[tuple[WriteSession, str, int]] = []
        self.statements: list[str] = []
        self.returned: CanonicalExecutionSnapshot | None = None

    def _record_statement(self, state: ORMExecuteState) -> None:
        statement = str(state.statement)
        assert "FOR UPDATE" not in statement and "FOR SHARE" not in statement
        self.statements.append(statement)

    async def load_canonical_snapshot(
        self, session: ReadSession, *, session_id: str, owner_generation: int
    ) -> CanonicalExecutionSnapshot:
        assert self.manager.active and session is self.manager.sessions[-1]
        self.calls.append((session, session_id, owner_generation))
        event.listen(
            session.write_session.sync_session, "do_orm_execute", self._record_statement
        )
        try:
            result = await super().load_canonical_snapshot(
                session, session_id=session_id, owner_generation=owner_generation
            )
            assert session.read_session.in_transaction()
            self.returned = result
            if self.error is not None:
                raise self.error
            return result
        finally:
            event.remove(
                session.write_session.sync_session,
                "do_orm_execute",
                self._record_statement,
            )


@dataclasses.dataclass(frozen=True)
class _SnapshotSubject:
    session_id: str
    root_session_id: str
    agent_id: str
    workspace_id: str
    workspace_handle: str
    session_agent_id: str
    root_session_agent_id: str
    context_id: str
    generation: int


async def _subject(
    manager: SessionManager[WriteSession], handle: str, *, child: bool
) -> _SnapshotSubject:
    sessions = AgentSessionRepository()
    async with manager() as session:
        root, agent_id = await _create_execution_subject(session, handle=handle)
        root_node = await sessions.get_session_agent_by_session_id(session, root.id)
        assert root_node is not None
        current = root_node
        if child:
            current = await sessions.create_child_session_agent(
                session,
                parent_session_agent_id=root_node.id,
                name="snapshot-child",
                agent_type="default",
                title=None,
                last_task_message=None,
            )
            await sessions.mark_running(session, current.agent_session_id)
        generation = await sessions.claim_owner_generation(
            session, current.agent_session_id
        )
        return _SnapshotSubject(
            current.agent_session_id,
            root.id,
            agent_id,
            root.workspace_id,
            handle,
            current.id,
            root_node.id,
            root_node.context_id,
            generation,
        )


async def _assert_equivalent(
    manager: SessionManager[WriteSession],
    subject: _SnapshotSubject,
    wrapper: WorkerSessionSnapshotOperationRepository,
    projection: _ObservedProjection,
) -> CanonicalExecutionSnapshot:
    async with manager() as session:
        expected = await SessionExecutionRepository().load_canonical_snapshot(
            session, session_id=subject.session_id, owner_generation=subject.generation
        )
    result = await wrapper.load(subject.session_id, owner_generation=subject.generation)
    projection.manager.assert_closed()
    assert result == expected and result is projection.returned
    assert projection.calls[-1][1:] == (subject.session_id, subject.generation)
    assert projection.statements
    assert dataclasses.asdict(result) == dataclasses.asdict(expected)
    assert not any(
        isinstance(value, AsyncSession) for value in dataclasses.asdict(result).values()
    )
    return result


@pytest.mark.parametrize("child", [False, True])
async def test_snapshot_after_claim_preserves_root_agent_workspace_and_lineage(
    rdb_session_manager: SessionManager[WriteSession], child: bool
) -> None:
    """Claim completes first; the exact canonical DTO returns after unlocked SQL."""
    observed = ObservedReadManager(rdb_session_manager)
    subject = await _subject(observed, f"snapshot-identity-{child}", child=child)
    observed.assert_closed()
    assert len(observed.sessions) == 1
    projection = _ObservedProjection(observed, None)
    wrapper = WorkerSessionSnapshotOperationRepository(observed, projection)
    result = await _assert_equivalent(rdb_session_manager, subject, wrapper, projection)
    assert len(observed.sessions) == 2
    assert projection.calls[0][0] is observed.sessions[1]
    assert result.session_id == subject.session_id
    assert result.root_session_id == subject.root_session_id
    assert result.workspace_id == subject.workspace_id
    assert result.workspace_handle == subject.workspace_handle
    assert result.agent_id == subject.agent_id
    assert result.session_agent_id == subject.session_agent_id
    assert result.root_session_agent_id == subject.root_session_agent_id
    assert result.session_agent_context_id == subject.context_id
    assert result.execution_mode is (
        AgentSessionKind.SUBAGENT if child else AgentSessionKind.ROOT
    )
    assert result.owner_generation == subject.generation == 1
    assert result.pending_command is None
    assert result.recoverable_run_id is None
    assert result.pending_idle_continuation_run_id is None


def _run(session_id: str, index: int, status: AgentRunStatus) -> RDBAgentRun:
    return RDBAgentRun(
        session_id=session_id,
        run_index=index,
        status=status,
        scheduled_task_cycle_id=None,
        parent_agent_run_id=None,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        requested_enabled_execution_options=[],
    )


@pytest.mark.parametrize("status", [AgentRunStatus.PENDING, AgentRunStatus.RUNNING])
async def test_snapshot_preserves_command_recoverable_run_and_completed_idle_state(
    rdb_session_manager: SessionManager[WriteSession], status: AgentRunStatus
) -> None:
    subject = await _subject(rdb_session_manager, "snapshot-work-state", child=True)
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        row = await session.read_session.get(RDBAgentSession, subject.session_id)
        assert row is not None
        conversation = row.conversation
        assert conversation is not None
        conversation.pending_command_id = "command-001"
        conversation.pending_command_name = "compact"
        payload: dict[str, object] = {"reason": "manual", "requested": True}
        conversation.pending_command_payload = payload
        conversation.pending_command_requester_user_id = None
        conversation.pending_command_created_at = now
        recoverable = _run(subject.session_id, 1, status)
        completed = _run(subject.session_id, 2, AgentRunStatus.COMPLETED)
        other_root_run = _run(subject.root_session_id, 1, AgentRunStatus.PENDING)
        session.write_session.add_all([recoverable, completed, other_root_run])
        await session.write_session.flush()
        conversation.pending_idle_continuation_run_id = completed.id
        await session.write_session.flush()
        recoverable_id, completed_id = recoverable.id, completed.id
    observed = ObservedReadManager(rdb_session_manager)
    projection = _ObservedProjection(observed, None)
    wrapper = WorkerSessionSnapshotOperationRepository(observed, projection)
    result = await _assert_equivalent(rdb_session_manager, subject, wrapper, projection)
    assert result.pending_command is not None
    assert result.pending_command.id == "command-001"
    assert result.pending_command.name == "compact"
    assert result.pending_command.payload == {"reason": "manual", "requested": True}
    assert result.pending_command.requester_user_id is None
    assert result.pending_command.created_at == now
    assert result.recoverable_run_id == recoverable_id
    assert result.recoverable_run_status is status
    assert result.pending_idle_continuation_run_id == completed_id
    assert len(observed.sessions) == 1


@pytest.mark.parametrize("phase", ["started", "admitted"])
@pytest.mark.parametrize("decommissioning", [False, True])
async def test_snapshot_keeps_archived_started_continuation_exception_unchanged(
    rdb_session_manager: SessionManager[WriteSession],
    phase: Literal["started", "admitted"],
    decommissioning: bool,
) -> None:
    subject = await _subject(
        rdb_session_manager, "snapshot-archived-cycle", child=False
    )
    async with rdb_session_manager() as session:
        row = await session.read_session.get(RDBAgentSession, subject.session_id)
        assert row is not None
        await _archive_with_scheduled_continuation(
            session, agent_session=row, phase=phase
        )
        if decommissioning:
            agent = await session.read_session.get(RDBAgent, subject.agent_id)
            assert agent is not None
            agent.lifecycle_status = AgentLifecycleStatus.DECOMMISSIONING
        await session.write_session.flush()
    observed = ObservedReadManager(rdb_session_manager)
    projection = _ObservedProjection(observed, None)
    wrapper = WorkerSessionSnapshotOperationRepository(observed, projection)
    if phase == "started":
        result = await _assert_equivalent(
            rdb_session_manager, subject, wrapper, projection
        )
        assert result.session_id == result.root_session_id == subject.session_id
        assert result.recoverable_run_id is None
    else:
        with pytest.raises(
            CanonicalExecutionSnapshotError, match="AgentSession is not active"
        ):
            await wrapper.load(subject.session_id, owner_generation=subject.generation)
        observed.assert_closed()
    assert len(observed.sessions) == 1


SnapshotFailure = Literal["missing", "stale", "idle", "command", "idle-run", "lineage"]


@pytest.mark.parametrize(
    "failure", ["missing", "stale", "idle", "command", "idle-run", "lineage"]
)
async def test_snapshot_wrapper_preserves_bounded_canonical_errors_and_read_cleanup(
    rdb_session_manager: SessionManager[WriteSession], failure: SnapshotFailure
) -> None:
    """Representative validations remain the core repository's authority."""
    subject = await _subject(
        rdb_session_manager, f"snapshot-invalid-{failure}", child=True
    )
    session_id, generation = subject.session_id, subject.generation
    async with rdb_session_manager() as session:
        row = await session.read_session.get(RDBAgentSession, session_id)
        assert row is not None
        if failure == "missing":
            session_id = "0" * 32
        elif failure == "stale":
            await AgentSessionRepository().claim_owner_generation(session, session_id)
        elif failure == "idle":
            row.run_state = AgentSessionRunState.IDLE
        elif failure == "command":
            assert row.conversation is not None
            row.conversation.pending_command_id = "incomplete-command"
        elif failure == "idle-run":
            run = _run(session_id, 1, AgentRunStatus.RUNNING)
            session.write_session.add(run)
            await session.write_session.flush()
            assert row.conversation is not None
            row.conversation.pending_idle_continuation_run_id = run.id
        else:
            node = await session.read_session.get(
                RDBSessionAgent, subject.session_agent_id
            )
            assert node is not None
            node.parent_session_agent_id = node.id
        await session.write_session.flush()
    observed = ObservedReadManager(rdb_session_manager)
    projection = _ObservedProjection(observed, None)
    wrapper = WorkerSessionSnapshotOperationRepository(observed, projection)
    async with rdb_session_manager() as session:
        with pytest.raises(CanonicalExecutionSnapshotError) as primitive:
            await SessionExecutionRepository().load_canonical_snapshot(
                session, session_id=session_id, owner_generation=generation
            )
    with pytest.raises(type(primitive.value), match=str(primitive.value)) as wrapped:
        await wrapper.load(session_id, owner_generation=generation)
    assert type(wrapped.value) is type(primitive.value)
    if failure == "stale":
        assert type(wrapped.value) is CanonicalExecutionOwnerGenerationStaleError
    else:
        assert type(wrapped.value) is CanonicalExecutionSnapshotError
    observed.assert_closed()
    assert len(observed.sessions) == 1
    assert projection.returned is None


@pytest.mark.parametrize("cancel", [False, True])
async def test_snapshot_read_failure_or_cancellation_propagates_after_real_projection(
    rdb_session_manager: SessionManager[WriteSession], cancel: bool
) -> None:
    subject = await _subject(rdb_session_manager, "snapshot-read-failure", child=False)
    observed = ObservedReadManager(rdb_session_manager)
    error = (
        asyncio.CancelledError() if cancel else RuntimeError("read projection failure")
    )
    projection = _ObservedProjection(observed, error)
    wrapper = WorkerSessionSnapshotOperationRepository(observed, projection)
    with pytest.raises(type(error)):
        await wrapper.load(subject.session_id, owner_generation=subject.generation)
    assert projection.returned is not None
    observed.assert_closed()


class _PausedProjection(_ObservedProjection):
    def __init__(self, manager: ObservedReadManager) -> None:
        super().__init__(manager, None)
        self.read = asyncio.Event()
        self.release = asyncio.Event()

    async def load_canonical_snapshot(
        self, session: ReadSession, *, session_id: str, owner_generation: int
    ) -> CanonicalExecutionSnapshot:
        result = await super().load_canonical_snapshot(
            session, session_id=session_id, owner_generation=owner_generation
        )
        self.read.set()
        await self.release.wait()
        return result


async def test_task_cancellation_after_canonical_sql_abandons_snapshot_read_scope(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    subject = await _subject(rdb_session_manager, "snapshot-task-cancel", child=False)
    observed = ObservedReadManager(rdb_session_manager)
    projection = _PausedProjection(observed)
    wrapper = WorkerSessionSnapshotOperationRepository(observed, projection)
    task = asyncio.create_task(
        wrapper.load(subject.session_id, owner_generation=subject.generation)
    )
    try:
        await asyncio.wait_for(projection.read.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert task.cancelled()
    assert projection.returned is not None
    observed.assert_closed()
