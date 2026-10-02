"""Genuine PostgreSQL Worker lifecycle predicates, rollback and fencing tests."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.broker.types import SessionBroker
from azents.core.enums import (
    AgentRunParentResultDeliveryState,
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionProductMode,
    AgentSessionRunState,
    EventKind,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.engine.events.types import AgentRunState
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunCreate, EventCreate
from azents.repos.agent_mailbox import AgentMailboxRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, AgentSessionCreate
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.mailbox.data import MailboxItemCreate
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.session_execution.data import PendingCommandSnapshot
from azents.repos.terminal_finalization import TerminalRunFinalizationRepository
from azents.repos.terminal_finalization_data import TerminalFinalizationOutcome
from azents.repos.worker_session import WorkerSessionOperationRepository
from azents.repos.worker_session_data import (
    CanonicalExecutionWorkDriftError,
    WorkerIdleDisposition,
)
from azents.worker.session.lifecycle import SessionLifecycleService


class ObservedManager:
    """Track actual SQLAlchemy sessions and require completion on every return."""

    def __init__(self, manager: SessionManager[AsyncSession]) -> None:
        self.manager = manager
        self.sessions: list[AsyncSession] = []
        self.active = False

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        assert not self.active, "Completed operations cannot nest transactions"
        self.active = True
        try:
            async with self.manager() as session:
                self.sessions.append(session)
                yield session
        finally:
            self.active = False

    def assert_closed(self) -> None:
        assert not self.active
        assert all(not session.in_transaction() for session in self.sessions)


@dataclasses.dataclass(frozen=True)
class WorkerFixture:
    session_id: str
    generation: int
    workspace_id: str
    agent_id: str
    root_session_id: str
    manager: ObservedManager
    repository: WorkerSessionOperationRepository


def worker_repository(
    manager: SessionManager[AsyncSession],
    *,
    sessions: AgentSessionRepository | None = None,
    runs: AgentRunRepository | None = None,
    terminal: TerminalRunFinalizationRepository | None = None,
) -> WorkerSessionOperationRepository:
    """Wire only production DB repositories, optionally with fault injection."""
    sessions = sessions if sessions is not None else AgentSessionRepository()
    runs = runs if runs is not None else AgentRunRepository()
    mailbox = MailboxRepository()
    if terminal is None:
        terminal = TerminalRunFinalizationRepository(
            manager,
            runs,
            sessions,
            AgentMailboxRepository(
                MailboxAdmissionRepository(manager, mailbox, sessions), sessions
            ),
        )
    return WorkerSessionOperationRepository(manager, sessions, runs, mailbox, terminal)


async def worker_fixture(
    manager: SessionManager[AsyncSession],
    name: str,
    *,
    child: bool = False,
) -> WorkerFixture:
    """Create authority through the real Session repositories."""
    observed = ObservedManager(manager)
    sessions = AgentSessionRepository()
    async with manager() as session:
        workspace_id = await _create_workspace(session, name)
        agent_id = await _create_agent(session, workspace_id, name)
        root = await sessions.create(
            session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                title=None,
            ),
        )
        session_id = root.id
        if child:
            parent = await sessions.get_session_agent_by_session_id(session, root.id)
            assert parent is not None
            node = await sessions.create_child_session_agent(
                session,
                parent_session_agent_id=parent.id,
                name="worker-child",
                agent_type="default",
                title=None,
                last_task_message=None,
            )
            session_id = node.agent_session_id
        generation = await sessions.claim_owner_generation(session, session_id)
        await sessions.mark_running(session, session_id)
    return WorkerFixture(
        session_id,
        generation,
        workspace_id,
        agent_id,
        root.id,
        observed,
        worker_repository(observed),
    )


async def create_run(
    manager: SessionManager[AsyncSession],
    session_id: str,
    status: AgentRunStatus = AgentRunStatus.RUNNING,
) -> AgentRunState:
    async with manager() as session:
        return await AgentRunRepository().create(
            session,
            AgentRunCreate(
                session_id=session_id,
                parent_agent_run_id=None,
                scheduled_task_cycle_id=None,
                status=status,
            ),
        )


async def current_session(
    manager: SessionManager[AsyncSession],
    session_id: str,
) -> AgentSession:
    async with manager() as session:
        result = await AgentSessionRepository().get_by_id(session, session_id)
        assert result is not None
        return result


async def current_run(
    manager: SessionManager[AsyncSession],
    run_id: str,
) -> AgentRunState:
    async with manager() as session:
        result = await AgentRunRepository().get_by_id(session, run_id)
        assert result is not None
        return result


async def test_missing_and_stale_worker_authority_are_distinct(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await worker_fixture(rdb_session_manager, "worker-authority")
    with pytest.raises(ValueError, match="^AgentSession not found$") as missing:
        await fixture.repository.assert_current_owner_generation(
            "f" * 32, owner_generation=0
        )
    assert type(missing.value) is ValueError
    newer = await fixture.repository.claim_owner_generation(fixture.session_id)
    assert newer == fixture.generation + 1
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await fixture.repository.assert_current_owner_generation(
            fixture.session_id,
            owner_generation=fixture.generation,
        )
    fixture.manager.assert_closed()


@pytest.mark.parametrize("case", ["command", "wake", "queue", "active", "empty"])
async def test_idle_predicates_preserve_durable_running_state(
    rdb_session_manager: SessionManager[AsyncSession],
    case: str,
) -> None:
    fixture = await worker_fixture(rdb_session_manager, f"worker-idle-{case}")
    expected = WorkerIdleDisposition.IDLE
    run_id: str | None = None
    command_id: str | None = None
    if case == "command":
        async with rdb_session_manager() as session:
            await AgentSessionRepository().mark_idle(session, fixture.session_id)
            command = await AgentSessionRepository().enqueue_pending_command(
                session,
                session_id=fixture.session_id,
                command_id="command",
                command_name="compact",
                payload={},
                requester_user_id=None,
            )
            assert command is not None
        expected = WorkerIdleDisposition.COMMAND_PENDING
        command_id = "command"
    elif case in {"wake", "queue"}:
        mode = (
            MailboxSchedulingMode.WAKE_SESSION
            if case == "wake"
            else MailboxSchedulingMode.QUEUE_ONLY
        )
        async with rdb_session_manager() as session:
            await MailboxRepository().create(
                session,
                MailboxItemCreate(
                    session_id=fixture.session_id,
                    kind=MailboxItemKind.USER_MESSAGE,
                    scheduling_mode=mode,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    requested_enabled_execution_options=[],
                    sender_user_id=None,
                    order_group=None,
                    order_sequence=0,
                    content="Pending input",
                    idempotency_key=None,
                    metadata={},
                    attachments=[],
                    file_parts=[],
                ),
            )
        if case == "wake":
            expected = WorkerIdleDisposition.WAKE_INPUT_PENDING
    elif case == "active":
        run = await create_run(rdb_session_manager, fixture.session_id)
        run_id = run.id
        expected = WorkerIdleDisposition.RUN_ACTIVE
    result = await fixture.repository.mark_session_idle(
        fixture.session_id,
        owner_generation=fixture.generation,
    )
    assert result.disposition is expected
    assert result.run_id == run_id
    assert result.command_id == command_id
    state = await current_session(rdb_session_manager, fixture.session_id)
    assert state.run_state is (
        AgentSessionRunState.IDLE
        if expected is WorkerIdleDisposition.IDLE
        else AgentSessionRunState.RUNNING
    )
    fixture.manager.assert_closed()


@pytest.mark.parametrize("field", ["id", "name", "payload", "requester", "created_at"])
async def test_pending_command_validates_every_snapshot_field(
    rdb_session_manager: SessionManager[AsyncSession],
    field: str,
) -> None:
    fixture = await worker_fixture(rdb_session_manager, f"worker-command-{field}")
    async with rdb_session_manager() as session:
        await AgentSessionRepository().mark_idle(session, fixture.session_id)
        await AgentSessionRepository().enqueue_pending_command(
            session,
            session_id=fixture.session_id,
            command_id="command",
            command_name="compact",
            payload={"force": True},
            requester_user_id=None,
        )
        command = await AgentSessionRepository().get_pending_command_by_session_id(
            session, fixture.session_id
        )
        assert command is not None
    snapshot = PendingCommandSnapshot(
        id=command.id,
        name=command.name,
        payload=command.payload,
        requester_user_id=command.requester_user_id,
        created_at=command.created_at,
    )
    await fixture.repository.validate_pending_command(
        fixture.session_id,
        owner_generation=fixture.generation,
        command=snapshot,
    )
    changes: dict[str, object] = {
        "id": "other",
        "name": "other",
        "payload": {},
        "requester_user_id": "user",
        "created_at": command.created_at + timedelta(seconds=1),
    }
    key = "requester_user_id" if field == "requester" else field
    with pytest.raises(CanonicalExecutionWorkDriftError):
        await fixture.repository.validate_pending_command(
            fixture.session_id,
            owner_generation=fixture.generation,
            command=dataclasses.replace(snapshot, **{key: changes[key]}),
        )
    with pytest.raises(CanonicalExecutionWorkDriftError):
        await fixture.repository.clear_pending_command(
            fixture.session_id,
            owner_generation=fixture.generation,
            command_id="other",
        )
    assert await fixture.repository.has_pending_command(fixture.session_id)
    await fixture.repository.clear_pending_command(
        fixture.session_id,
        owner_generation=fixture.generation,
        command_id=command.id,
    )
    assert not await fixture.repository.has_pending_command(fixture.session_id)
    fixture.manager.assert_closed()


class FailingAssociation(AgentRunRepository):
    async def associate_input_events(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        event_ids: Sequence[str],
    ) -> None:
        await super().associate_input_events(
            session, run_id=run_id, event_ids=event_ids
        )
        raise RuntimeError("after input association")


async def test_pending_creation_association_rollback_and_drift(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await worker_fixture(rdb_session_manager, "worker-input-rollback")
    async with rdb_session_manager() as session:
        event = await EventTranscriptRepository().append(
            session,
            EventCreate(
                session_id=fixture.session_id,
                kind=EventKind.USER_MESSAGE,
                payload={"sender_user_id": None, "content": "input"},
            ),
        )
    failing = worker_repository(fixture.manager, runs=FailingAssociation())
    with pytest.raises(RuntimeError, match="after input association"):
        await failing.create_pending_agent_run(
            fixture.session_id,
            owner_generation=fixture.generation,
            input_event_ids=[event.id],
        )
    assert not await fixture.repository.has_active_agent_run(fixture.session_id)
    async with rdb_session_manager() as session:
        assert (
            await AgentRunRepository().list_by_input_event_id(
                session, event_id=event.id
            )
            == []
        )
    pending = await fixture.repository.create_pending_agent_run(
        fixture.session_id,
        owner_generation=fixture.generation,
        input_event_ids=[event.id],
    )
    async with rdb_session_manager() as session:
        assert await AgentRunRepository().list_input_event_ids(
            session, run_id=pending.id
        ) == [event.id]
    with pytest.raises(CanonicalExecutionWorkDriftError):
        await fixture.repository.create_pending_agent_run(
            fixture.session_id,
            owner_generation=fixture.generation,
            input_event_ids=[event.id],
        )
    recovered = await fixture.repository.claim_recoverable_agent_run(
        fixture.session_id,
        owner_generation=fixture.generation,
    )
    assert recovered is not None and recovered.id == pending.id
    fixture.manager.assert_closed()


async def test_activation_foreign_session_rolls_back_profile_status_and_phase(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await worker_fixture(rdb_session_manager, "worker-activation-current")
    foreign = await worker_fixture(rdb_session_manager, "worker-activation-foreign")
    pending = await create_run(
        rdb_session_manager, foreign.session_id, AgentRunStatus.PENDING
    )
    profile = RequestedInferenceProfile(
        model_target_label="default",
        reasoning_effort=None,
        enabled_execution_options=[],
    )
    with pytest.raises(ValueError, match="AgentRun session mismatch"):
        await fixture.repository.activate_pending_agent_run(
            fixture.session_id,
            owner_generation=fixture.generation,
            run_id=pending.id,
            initial_phase=AgentRunPhase.COMPACTING,
            requested_profile=profile,
        )
    unchanged = await current_run(rdb_session_manager, pending.id)
    assert unchanged == pending
    activated = await foreign.repository.activate_pending_agent_run(
        foreign.session_id,
        owner_generation=foreign.generation,
        run_id=pending.id,
        initial_phase=AgentRunPhase.COMPACTING,
        requested_profile=profile,
    )
    assert activated.phase is AgentRunPhase.COMPACTING
    assert activated.status is AgentRunStatus.RUNNING
    assert activated.requested_model_target_label == "default"
    fixture.manager.assert_closed()
    foreign.manager.assert_closed()


@dataclasses.dataclass(frozen=True)
class FailingFinalization(TerminalRunFinalizationRepository):
    async def finalize_run_in_session(
        self,
        session: AsyncSession,
        *,
        run_id: str,
    ) -> TerminalFinalizationOutcome:
        await super().finalize_run_in_session(session, run_id=run_id)
        raise RuntimeError("after terminal finalization")


@pytest.mark.parametrize("operation", ["cancel", "terminal", "stop", "bulk"])
async def test_terminal_and_parent_finalization_roll_back_together(
    rdb_session_manager: SessionManager[AsyncSession],
    operation: str,
) -> None:
    fixture = await worker_fixture(
        rdb_session_manager, f"worker-terminal-{operation}", child=True
    )
    status = AgentRunStatus.PENDING if operation == "cancel" else AgentRunStatus.RUNNING
    run = await create_run(rdb_session_manager, fixture.session_id, status)
    terminal = FailingFinalization(
        fixture.repository.terminal_finalization_repository.session_manager,
        fixture.repository.agent_run_repository,
        fixture.repository.agent_session_repository,
        fixture.repository.terminal_finalization_repository.agent_mailbox_repository,
    )
    failing = worker_repository(fixture.manager, terminal=terminal)
    with pytest.raises(RuntimeError, match="after terminal finalization"):
        match operation:
            case "cancel":
                await failing.cancel_pending_agent_run(
                    fixture.session_id,
                    owner_generation=fixture.generation,
                    run_id=run.id,
                )
            case "terminal":
                await failing.mark_agent_run_terminal_if_running(
                    fixture.session_id,
                    owner_generation=fixture.generation,
                    run_id=run.id,
                    status=AgentRunStatus.FAILED,
                )
            case "stop":
                await failing.mark_agent_run_stopped_for_user_stop(
                    fixture.session_id,
                    owner_generation=fixture.generation,
                    run_id=run.id,
                )
            case "bulk":
                await failing.mark_session_agent_runs_terminal(
                    fixture.session_id,
                    owner_generation=fixture.generation,
                    status=AgentRunStatus.FAILED,
                )
    unchanged = await current_run(rdb_session_manager, run.id)
    assert unchanged == run
    async with rdb_session_manager() as session:
        assert not await MailboxRepository().has_by_session_id_and_scheduling_mode(
            session,
            session_id=fixture.root_session_id,
            scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
        )
    if operation == "cancel":
        await fixture.repository.cancel_pending_agent_run(
            fixture.session_id, owner_generation=fixture.generation, run_id=run.id
        )
    else:
        await fixture.repository.mark_agent_run_terminal_if_running(
            fixture.session_id,
            owner_generation=fixture.generation,
            run_id=run.id,
            status=AgentRunStatus.FAILED,
        )
    finalized = await current_run(rdb_session_manager, run.id)
    assert (
        finalized.parent_result_delivery_state
        is AgentRunParentResultDeliveryState.ENQUEUED
    )
    fixture.manager.assert_closed()


class FailingSuppression(AgentRunRepository):
    async def mark_parent_result_suppressed(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        finalized_at: datetime,
    ) -> AgentRunState:
        await super().mark_parent_result_suppressed(
            session, run_id=run_id, finalized_at=finalized_at
        )
        raise RuntimeError("after bridge suppression")


@pytest.mark.parametrize("status", [AgentRunStatus.PENDING, AgentRunStatus.RUNNING])
async def test_bridge_terminal_and_suppression_share_atomic_commit(
    rdb_session_manager: SessionManager[AsyncSession],
    status: AgentRunStatus,
) -> None:
    fixture = await worker_fixture(rdb_session_manager, f"worker-bridge-{status.value}")
    run = await create_run(rdb_session_manager, fixture.session_id, status)
    failing = worker_repository(fixture.manager, runs=FailingSuppression())
    with pytest.raises(RuntimeError, match="after bridge suppression"):
        await failing.complete_bridge_predecessor_run(
            fixture.session_id, owner_generation=fixture.generation, run_id=run.id
        )
    assert await current_run(rdb_session_manager, run.id) == run
    expected = (
        AgentRunStatus.CANCELLED
        if status is AgentRunStatus.PENDING
        else AgentRunStatus.COMPLETED
    )
    assert (
        await fixture.repository.complete_bridge_predecessor_run(
            fixture.session_id,
            owner_generation=fixture.generation,
            run_id=run.id,
        )
        is expected
    )
    settled = await current_run(rdb_session_manager, run.id)
    assert settled.status is expected
    assert (
        settled.parent_result_delivery_state
        is AgentRunParentResultDeliveryState.SUPPRESSED
    )
    fixture.manager.assert_closed()


@pytest.mark.parametrize(
    "operation", ["heartbeat", "idle", "pending", "terminal", "retry", "lifecycle"]
)
async def test_takeover_rejects_old_owner_before_any_mutation(
    rdb_session_manager: SessionManager[AsyncSession],
    operation: str,
) -> None:
    fixture = await worker_fixture(rdb_session_manager, f"worker-stale-{operation}")
    run = await create_run(rdb_session_manager, fixture.session_id)
    await fixture.repository.claim_owner_generation(fixture.session_id)
    before = await current_session(rdb_session_manager, fixture.session_id)
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        match operation:
            case "heartbeat":
                await fixture.repository.heartbeat_session(
                    fixture.session_id, owner_generation=fixture.generation
                )
            case "idle":
                await fixture.repository.mark_session_idle(
                    fixture.session_id, owner_generation=fixture.generation
                )
            case "pending":
                await fixture.repository.create_pending_agent_run(
                    fixture.session_id,
                    owner_generation=fixture.generation,
                    input_event_ids=[],
                )
            case "terminal":
                await fixture.repository.mark_agent_run_terminal_if_running(
                    fixture.session_id,
                    owner_generation=fixture.generation,
                    run_id=run.id,
                    status=AgentRunStatus.FAILED,
                )
            case "retry":
                await fixture.repository.update_agent_run_retry_state(
                    fixture.session_id,
                    owner_generation=fixture.generation,
                    run_id=run.id,
                    retry_state=None,
                )
            case "lifecycle":
                await fixture.repository.claim_lifecycle_start(
                    fixture.session_id,
                    owner_generation=fixture.generation,
                    now=datetime.now(UTC),
                )
    assert await current_session(rdb_session_manager, fixture.session_id) == before
    assert await current_run(rdb_session_manager, run.id) == run
    fixture.manager.assert_closed()


async def test_foreign_terminal_run_is_not_mutated(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await worker_fixture(rdb_session_manager, "worker-terminal-current")
    foreign = await worker_fixture(rdb_session_manager, "worker-terminal-foreign")
    run = await create_run(rdb_session_manager, foreign.session_id)
    with pytest.raises(ValueError, match="AgentRun session mismatch"):
        await fixture.repository.mark_agent_run_terminal_if_running(
            fixture.session_id,
            owner_generation=fixture.generation,
            run_id=run.id,
            status=AgentRunStatus.FAILED,
        )
    assert await current_run(rdb_session_manager, run.id) == run
    fixture.manager.assert_closed()


async def test_worker_tree_lock_order_precedes_run_lock(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Capture actual SQL: root gate, ordered Agent/Session set, then Run."""
    fixture = await worker_fixture(rdb_session_manager, "worker-lock-order", child=True)
    run = await create_run(rdb_session_manager, fixture.session_id)
    statements: list[str] = []

    def observe(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and "for " in normalized:
            statements.append(normalized)

    @asynccontextmanager
    async def traced_manager() -> AsyncIterator[AsyncSession]:
        async with fixture.manager() as session:
            connection = await session.connection()
            event.listen(connection.sync_connection, "before_cursor_execute", observe)
            try:
                yield session
            finally:
                event.remove(
                    connection.sync_connection, "before_cursor_execute", observe
                )

    repository = dataclasses.replace(fixture.repository, session_manager=traced_manager)
    await repository.complete_bridge_predecessor_run(
        fixture.session_id, owner_generation=fixture.generation, run_id=run.id
    )
    # The bridge explicitly locks its predecessor, and mark_terminal retains
    # its existing second lock of the same Run. Both follow Session admission.
    assert len(statements) == 5
    root, agents, sessions, runs, terminal_run = statements
    assert "from session_agents" in root and "for update nowait" in root
    assert "from agents" in agents
    assert "order by agents.id for key share nowait" in agents
    assert "from agent_sessions" in sessions
    assert "order by agent_sessions.id for no key update nowait" in sessions
    assert "from agent_runs" in runs and "for update" in runs
    assert terminal_run == runs
    fixture.manager.assert_closed()


async def test_heartbeat_external_lease_runs_after_real_transaction_closure(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Verify actual closure and persisted heartbeat inside the broker callback."""
    fixture = await worker_fixture(rdb_session_manager, "worker-heartbeat-closure")
    before = await current_session(rdb_session_manager, fixture.session_id)
    assert before.run_heartbeat_at is not None
    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == fixture.session_id)
            .values(run_heartbeat_at=before.run_heartbeat_at - timedelta(days=1))
        )
    mock = create_autospec(SessionBroker, instance=True)
    broker: SessionBroker = mock

    async def renew(session_id: str) -> None:
        fixture.manager.assert_closed()
        current = await current_session(rdb_session_manager, session_id)
        assert current.run_heartbeat_at is not None
        assert current.run_heartbeat_at >= before.run_heartbeat_at

    mock.renew_session_ttl.side_effect = renew
    service = SessionLifecycleService(broker=broker, repository=fixture.repository)
    await service.heartbeat_session(
        fixture.session_id, owner_generation=fixture.generation
    )
    mock.renew_session_ttl.assert_awaited_once_with(fixture.session_id)


async def test_recovery_reads_running_before_pending_without_mutation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await worker_fixture(rdb_session_manager, "worker-recover-running")
    running = await create_run(rdb_session_manager, fixture.session_id)
    async with rdb_session_manager() as session:
        pending = await AgentRunRepository().create_pending(
            session,
            session_id=fixture.session_id,
            parent_agent_run_id=None,
            scheduled_task_cycle_id=None,
        )
    recovered = await fixture.repository.claim_recoverable_agent_run(
        fixture.session_id, owner_generation=fixture.generation
    )
    assert recovered is not None and recovered.id == running.id
    assert await current_run(rdb_session_manager, pending.id) == pending
    assert await fixture.repository.has_active_agent_run(fixture.session_id)
    assert (
        await fixture.repository.get_running_agent_run(
            fixture.session_id, owner_generation=fixture.generation
        )
        == running
    )
    fixture.manager.assert_closed()


async def test_lifecycle_start_is_idempotent_and_guarded(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await worker_fixture(rdb_session_manager, "worker-lifecycle-start")
    now = datetime.now(UTC)
    assert await fixture.repository.claim_lifecycle_start(
        fixture.session_id, owner_generation=fixture.generation, now=now
    )
    assert not await fixture.repository.claim_lifecycle_start(
        fixture.session_id,
        owner_generation=fixture.generation,
        now=now + timedelta(seconds=1),
    )
    current = await current_session(rdb_session_manager, fixture.session_id)
    assert current.lifecycle_started_at == now
    fixture.manager.assert_closed()


async def test_idle_continuation_read_preserves_missing_error(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await worker_fixture(rdb_session_manager, "worker-idle-continuation")
    assert (
        await fixture.repository.get_pending_idle_continuation_run_id(
            fixture.session_id
        )
        is None
    )
    run = await create_run(rdb_session_manager, fixture.session_id)
    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == fixture.session_id)
            .values(pending_idle_continuation_run_id=run.id)
        )
    assert (
        await fixture.repository.get_pending_idle_continuation_run_id(
            fixture.session_id
        )
        == run.id
    )
    with pytest.raises(ValueError, match="^AgentSession not found$"):
        await fixture.repository.get_pending_idle_continuation_run_id("f" * 32)
    fixture.manager.assert_closed()


async def cleanup_committed_fixture(
    manager: SessionManager[AsyncSession], fixture: WorkerFixture
) -> None:
    """Remove only the independently committed race fixture, never shared rows."""
    async with manager() as session:
        context_ids = sa.select(RDBSessionAgentContext.id).where(
            RDBSessionAgentContext.agent_id == fixture.agent_id
        )
        await session.execute(
            sa.update(RDBSessionAgentContext)
            .where(RDBSessionAgentContext.agent_id == fixture.agent_id)
            .values(root_session_agent_id=None)
        )
        await session.execute(
            sa.delete(RDBSessionAgent).where(
                RDBSessionAgent.context_id.in_(context_ids)
            )
        )
        await session.execute(
            sa.delete(RDBAgentSession).where(
                RDBAgentSession.agent_id == fixture.agent_id
            )
        )
        await session.execute(
            sa.delete(RDBSessionAgentContext).where(
                RDBSessionAgentContext.agent_id == fixture.agent_id
            )
        )
        await session.execute(
            sa.delete(RDBAgentRuntime).where(
                RDBAgentRuntime.agent_id == fixture.agent_id
            )
        )
        await session.execute(
            sa.delete(RDBAgent).where(RDBAgent.id == fixture.agent_id)
        )
        await session.execute(
            sa.delete(RDBLLMProviderIntegration).where(
                RDBLLMProviderIntegration.workspace_id == fixture.workspace_id
            )
        )
        await session.execute(
            sa.delete(RDBWorkspace).where(RDBWorkspace.id == fixture.workspace_id)
        )


@pytest.mark.parametrize("first", ["takeover", "worker"])
async def test_independent_transactions_serialize_owner_fence(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    first: Literal["takeover", "worker"],
) -> None:
    """Two real connections/barriers prove both legal guard/claim orderings."""
    del latest_db_schema

    @asynccontextmanager
    async def manager() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            try:
                yield session
            except BaseException:
                await session.rollback()
                raise
            else:
                await session.commit()

    fixture = await worker_fixture(
        manager, f"worker-race-{uuid4().hex[:12]}", child=True
    )
    locked = asyncio.Event()
    release = asyncio.Event()
    retry_seen = asyncio.Event()
    second_started = asyncio.Event()
    connection_ids: list[int] = []

    class BarrierSessions(AgentSessionRepository):
        async def lock_execution_by_id(
            self, session: AsyncSession, agent_session_id: str
        ) -> AgentSession | None:
            try:
                return await super().lock_execution_by_id(session, agent_session_id)
            except OperationalError:
                retry_seen.set()
                raise

    async def first_transaction() -> None:
        async with manager() as session:
            connection_ids.append(
                await session.scalar(sa.text("SELECT pg_backend_pid()"))
            )
            if first == "takeover":
                await AgentSessionRepository().claim_owner_generation(
                    session, fixture.session_id
                )
            else:
                await fixture.repository.assert_owner_generation_in_session(
                    session,
                    session_id=fixture.session_id,
                    owner_generation=fixture.generation,
                )
                await AgentSessionRepository().heartbeat_running(
                    session, fixture.session_id
                )
            locked.set()
            await release.wait()

    async def second_transaction() -> None:
        await locked.wait()

        @asynccontextmanager
        async def second_manager() -> AsyncIterator[AsyncSession]:
            async with manager() as session:
                connection_ids.append(
                    await session.scalar(sa.text("SELECT pg_backend_pid()"))
                )
                second_started.set()
                yield session

        sessions = BarrierSessions()
        if first == "takeover":
            repository = worker_repository(second_manager, sessions=sessions)
            with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
                await repository.mark_session_idle(
                    fixture.session_id, owner_generation=fixture.generation
                )
        else:
            repository = worker_repository(second_manager)
            assert (
                await repository.claim_owner_generation(fixture.session_id)
                == fixture.generation + 1
            )

    tasks: list[asyncio.Task[None]] = []
    try:
        tasks = [
            asyncio.create_task(first_transaction()),
            asyncio.create_task(second_transaction()),
        ]
        if first == "takeover":
            await asyncio.wait_for(retry_seen.wait(), timeout=10)
        else:
            await asyncio.wait_for(second_started.wait(), timeout=10)
            # The existing claim blocks on the root gate, before its NOWAIT
            # Session attempt. Observe PostgreSQL rather than changing policy.
            async with asyncio.timeout(10):
                async with manager() as observer:
                    while True:
                        blockers = await observer.scalar(
                            sa.text("SELECT pg_blocking_pids(:pid)"),
                            {"pid": connection_ids[1]},
                        )
                        if connection_ids[0] in blockers:
                            break
                        await asyncio.sleep(0.01)
        assert not tasks[1].done(), "Contender cannot pass an uncommitted owner fence"
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
        assert len(connection_ids) == 2 and connection_ids[0] != connection_ids[1]
        state = await current_session(manager, fixture.session_id)
        assert state.owner_generation == fixture.generation + 1
        assert state.run_state is AgentSessionRunState.RUNNING
        fixture.manager.assert_closed()
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await cleanup_committed_fixture(manager, fixture)
