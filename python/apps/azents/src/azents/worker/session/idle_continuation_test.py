"""IdleContinuationService tests."""

import dataclasses
import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from azents.broker.types import BrokerMessage, SessionWakeUp
from azents.core.enums import (
    AgentSessionKind,
    AgentSessionStatus,
    EventKind,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.tools import Toolkit, ToolkitState, ToolkitStatus, TurnContext
from azents.engine.events.types import Event
from azents.engine.hooks.types import (
    ExternalChannelSessionContinuationInput,
    GoalSessionContinuationInput,
    RuntimeHooks,
    ScheduledTaskSessionContinuationInput,
    SessionContinuationInput,
    SessionIdleHookContext,
    SessionIdleResult,
)
from azents.engine.run.contracts import ToolkitBinding
from azents.repos.idle_continuation import (
    IdleBoundaryEligibility,
    IdleContinuationAdmission,
    IdleContinuationFinalization,
    IdleContinuationInput,
)
from azents.repos.mailbox.data import (
    MailboxItem,
    ScheduledTaskContinuationMailboxPayload,
)
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
)
from azents.repos.session_execution.data import CanonicalExecutionSnapshot
from azents.worker.session.idle_continuation import IdleContinuationService


class _ContinuationRecorder:
    """Record canonical inputs accepted by a completed idle operation."""

    def __init__(self) -> None:
        self.enqueued_batches: list[list[IdleContinuationInput]] = []

    def record(
        self,
        inputs: list[IdleContinuationInput],
    ) -> list[IdleContinuationAdmission]:
        """Record completed admission outcomes without a service DB interface."""
        self.enqueued_batches.append(inputs)
        return [
            IdleContinuationAdmission(
                mailbox_item=MailboxItem(
                    id=f"{index + 1:032d}",
                    session_id=input.session_id,
                    kind=input.kind,
                    scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    requested_enabled_execution_options=[],
                    sender_user_id=None,
                    order_group=f"{index + 1:032d}",
                    order_sequence=0,
                    content=input.content,
                    idempotency_key=input.idempotency_key,
                    metadata=input.metadata,
                    attachments=[],
                    file_parts=[],
                    payload=input.payload,
                    created_at=datetime.datetime.now(datetime.UTC),
                ),
                created=True,
            )
            for index, input in enumerate(inputs)
        ]


class _SessionContext:
    """Async DB session context test double."""

    async def __aenter__(self) -> object:
        """Return a placeholder session."""
        return object()

    async def __aexit__(self, *args: object) -> None:
        """Exit context."""
        return None


class _SessionManager:
    """SessionManager test double."""

    def __call__(self) -> _SessionContext:
        """Return an async session context."""
        return _SessionContext()


@dataclasses.dataclass(frozen=True)
class _LockedSession:
    """Minimal locked AgentSession projection."""

    pending_idle_continuation_run_id: str | None
    pending_command_id: str | None
    workspace_id: str
    agent_id: str
    status: AgentSessionStatus
    owner_generation: int


class _AgentSessionRepository:
    """AgentSessionRepository test double."""

    def __init__(
        self,
        *,
        workspace_id: str = "workspace-001",
        owner_generation: int = 1,
        status: AgentSessionStatus = AgentSessionStatus.ACTIVE,
        consume_result: bool = True,
    ) -> None:
        self.boundary_run_id: str | None = "run-001"
        self.workspace_id = workspace_id
        self.status = status
        self.owner_generation = owner_generation
        self.consume_result = consume_result
        self.consumed: list[tuple[str, str, bool]] = []
        self.execution_admissions: list[str] = []

    async def wait_for_execution_lock_by_id(
        self,
        session: object,
        session_id: str,
    ) -> _LockedSession:
        """Record canonical admission before returning the locked Session."""
        del session
        self.execution_admissions.append(session_id)
        return _LockedSession(
            pending_idle_continuation_run_id=self.boundary_run_id,
            pending_command_id=None,
            workspace_id=self.workspace_id,
            agent_id="agent-001",
            status=self.status,
            owner_generation=self.owner_generation,
        )

    async def consume_pending_idle_continuation(
        self,
        session: object,
        *,
        session_id: str,
        run_id: str,
        continue_running: bool,
        allow_archived_scheduled_continuation: bool,
    ) -> bool:
        """Consume the matching durable boundary."""
        del session
        assert allow_archived_scheduled_continuation is (
            self.status is AgentSessionStatus.ARCHIVED
        )
        if not self.consume_result:
            return False
        if self.boundary_run_id != run_id:
            return False
        self.boundary_run_id = None
        self.consumed.append((session_id, run_id, continue_running))
        return True


class _AgentRunRepository:
    """AgentRunRepository test double."""

    async def get_active_by_session_id(
        self,
        session: object,
        *,
        session_id: str,
    ) -> None:
        """Report no active Run."""
        del session, session_id
        return None

    async def get_by_id(
        self,
        session: object,
        run_id: str,
    ) -> SimpleNamespace:
        """Return one Scheduled-bound completed Run."""
        del session
        return SimpleNamespace(
            id=run_id,
            scheduled_task_cycle_id="c" * 32,
        )


class _CycleRepository:
    """Started-cycle lookup used by archived idle admission."""

    async def get_started(
        self,
        session: object,
        *,
        agent_id: str,
        session_id: str,
        cycle_id: str,
    ) -> SimpleNamespace:
        """Return the exact started cycle."""
        del session, agent_id, session_id
        assert cycle_id == "c" * 32
        return SimpleNamespace(state=SimpleNamespace(current_run_id="run-001"))


class _MailboxRepository:
    """MailboxRepository test double."""

    def __init__(self, *, pending: bool) -> None:
        self.pending = pending
        self.checked_session_ids: list[str] = []

    async def has_by_session_id_and_scheduling_mode(
        self,
        session: object,
        *,
        session_id: str,
        scheduling_mode: MailboxSchedulingMode,
    ) -> bool:
        """Return configured pending wake-producing input state."""
        del session, scheduling_mode
        self.checked_session_ids.append(session_id)
        return self.pending


class _IdleContinuationRepository:
    """Completed idle-operation test double backed by existing narrow fakes."""

    def __init__(
        self,
        *,
        continuation_recorder: _ContinuationRecorder,
        agent_session_repository: _AgentSessionRepository,
        agent_run_repository: _AgentRunRepository,
        mailbox_item_repository: _MailboxRepository,
        scheduled_task_cycle_repository: _CycleRepository,
    ) -> None:
        self.continuation_recorder = continuation_recorder
        self.agent_session_repository = agent_session_repository
        self.agent_run_repository = agent_run_repository
        self.mailbox_item_repository = mailbox_item_repository
        self.scheduled_task_cycle_repository = scheduled_task_cycle_repository

    async def get_eligibility(
        self,
        session_id: str,
        run_id: str,
        *,
        owner_generation: int,
    ) -> IdleBoundaryEligibility:
        """Return one completed eligibility result."""
        return await self._eligibility(
            object(),
            session_id,
            run_id,
            owner_generation=owner_generation,
        )

    async def finalize(
        self,
        *,
        session_id: str,
        run_id: str,
        owner_generation: int,
        inputs: list[IdleContinuationInput],
    ) -> IdleContinuationFinalization:
        """Revalidate, record enqueues, and consume the boundary."""
        session = object()
        eligibility = await self._eligibility(
            session,
            session_id,
            run_id,
            owner_generation=owner_generation,
        )
        if not eligibility.eligible:
            return IdleContinuationFinalization(False, [], 0)
        accepted = inputs
        if eligibility.archived_cycle_id is not None:
            accepted = [
                input
                for input in inputs
                if input.scheduled_cycle_id == eligibility.archived_cycle_id
            ]
        consumed = (
            await self.agent_session_repository.consume_pending_idle_continuation(
                session,
                session_id=session_id,
                run_id=run_id,
                continue_running=bool(accepted),
                allow_archived_scheduled_continuation=(
                    eligibility.archived_cycle_id is not None
                ),
            )
        )
        if not consumed:
            return IdleContinuationFinalization(False, [], 0)
        results = self.continuation_recorder.record(accepted)
        return IdleContinuationFinalization(
            consumed=consumed,
            admissions=results,
            continuation_count=len(accepted),
        )

    async def _eligibility(
        self,
        session: object,
        session_id: str,
        run_id: str,
        *,
        owner_generation: int,
    ) -> IdleBoundaryEligibility:
        """Evaluate the same durable predicates as the production repository."""
        locked = await self.agent_session_repository.wait_for_execution_lock_by_id(
            session,
            session_id,
        )
        if locked.owner_generation != owner_generation:
            raise CanonicalExecutionOwnerGenerationStaleError(
                "Session owner generation is stale during idle continuation"
            )
        archived_cycle_id = None
        if locked.status is not AgentSessionStatus.ACTIVE:
            if locked.status is not AgentSessionStatus.ARCHIVED:
                return IdleBoundaryEligibility(False, None)
            run = await self.agent_run_repository.get_by_id(session, run_id)
            cycle_id = run.scheduled_task_cycle_id
            cycle = await self.scheduled_task_cycle_repository.get_started(
                session,
                agent_id=locked.agent_id,
                session_id=session_id,
                cycle_id=cycle_id,
            )
            if cycle is None or cycle.state.current_run_id != run_id:
                return IdleBoundaryEligibility(False, None)
            archived_cycle_id = cycle_id
        if locked.pending_idle_continuation_run_id != run_id:
            return IdleBoundaryEligibility(False, None)
        if locked.pending_command_id is not None:
            return IdleBoundaryEligibility(False, None)
        if await self.mailbox_item_repository.has_by_session_id_and_scheduling_mode(
            session,
            session_id=session_id,
            scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
        ):
            return IdleBoundaryEligibility(False, None)
        if (
            await self.agent_run_repository.get_active_by_session_id(
                session,
                session_id=session_id,
            )
            is not None
        ):
            return IdleBoundaryEligibility(False, None)
        return IdleBoundaryEligibility(True, archived_cycle_id)


class _EventPublisher:
    """WorkerEventPublisher test double."""

    def __init__(self) -> None:
        self.dispatched: list[tuple[str, Event]] = []

    async def dispatch_event(
        self,
        session_id: str,
        event: Event,
        *,
        owner_generation: int,
    ) -> None:
        """Record publish request."""
        del owner_generation
        self.dispatched.append((session_id, event))


class _Broker:
    """SessionBroker test double."""

    def __init__(self) -> None:
        self.sent_messages: list[BrokerMessage] = []

    async def send_message(self, message: BrokerMessage) -> None:
        """Record wake-up messages sent by the service."""
        self.sent_messages.append(message)


class _IdleToolkit(Toolkit[Any]):
    """Test toolkit that provides Session idle hook."""

    def __init__(
        self,
        continuations: list[SessionContinuationInput],
    ) -> None:
        self.continuations = continuations
        self.contexts: list[SessionIdleHookContext] = []

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Always return active empty state."""
        del context
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])

    def hooks(self) -> RuntimeHooks:
        """Provide only session idle hook."""
        return {"on_session_idle": self.on_session_idle}

    async def on_session_idle(
        self,
        context: SessionIdleHookContext,
    ) -> SessionIdleResult:
        """Return specified continuation."""
        self.contexts.append(context)
        return SessionIdleResult(continuations=self.continuations)


def _snapshot(
    *,
    workspace_id: str = "workspace-001",
    agent_id: str = "agent-001",
) -> CanonicalExecutionSnapshot:
    """Create a canonical execution snapshot for tests."""
    return CanonicalExecutionSnapshot(
        session_id="session-001",
        root_session_id="session-001",
        workspace_id=workspace_id,
        workspace_handle="workspace",
        agent_id=agent_id,
        session_agent_id="session-agent-001",
        root_session_agent_id="session-agent-001",
        session_agent_context_id="context-001",
        execution_mode=AgentSessionKind.ROOT,
        owner_generation=1,
        pending_command=None,
        recoverable_run_id=None,
        recoverable_run_status=None,
        pending_idle_continuation_run_id="run-001",
    )


def _construct_service(**kwargs: Any) -> IdleContinuationService:  # noqa: ANN401
    """Construct service with test-owned dependency doubles."""
    return IdleContinuationService(**kwargs)


def _service(
    *,
    continuation_recorder: Any,  # noqa: ANN401
    event_publisher: Any,  # noqa: ANN401
    broker: Any,  # noqa: ANN401
    agent_session_repository: Any | None = None,  # noqa: ANN401
    mailbox_item_repository: Any | None = None,  # noqa: ANN401
) -> IdleContinuationService:
    """Create IdleContinuationService under test."""
    agent_session = agent_session_repository or _AgentSessionRepository()
    mailbox_repository = mailbox_item_repository or _MailboxRepository(pending=False)
    return _construct_service(
        repository=_IdleContinuationRepository(
            continuation_recorder=continuation_recorder,
            agent_session_repository=agent_session,
            agent_run_repository=_AgentRunRepository(),
            mailbox_item_repository=mailbox_repository,
            scheduled_task_cycle_repository=_CycleRepository(),
        ),
        event_publisher=event_publisher,
        broker=broker,
    )


@pytest.mark.asyncio
async def test_consume_admits_both_idle_transactions_through_execution_tree() -> None:
    """Initial eligibility and final outcome share the canonical admission gate."""
    repository = _AgentSessionRepository()
    result = await _service(
        continuation_recorder=_ContinuationRecorder(),
        event_publisher=_EventPublisher(),
        broker=_Broker(),
        agent_session_repository=repository,
    ).consume(
        _snapshot(),
        toolkits=[],
        run_id="run-001",
    )

    assert result is True
    assert repository.execution_admissions == ["session-001", "session-001"]
    assert repository.consumed == [("session-001", "run-001", False)]


@pytest.mark.asyncio
async def test_consume_failure_publishes_no_event_or_wakeup() -> None:
    """A failed final boundary consume produces no external effects."""
    repository = _AgentSessionRepository(consume_result=False)
    continuation_recorder = _ContinuationRecorder()
    event_publisher = _EventPublisher()
    broker = _Broker()
    toolkit = _IdleToolkit(
        [GoalSessionContinuationInput(content="continue", metadata={})]
    )

    result = await _service(
        continuation_recorder=continuation_recorder,
        event_publisher=event_publisher,
        broker=broker,
        agent_session_repository=repository,
    ).consume(
        _snapshot(),
        toolkits=[ToolkitBinding(toolkit, "goal", "goal", False)],
        run_id="run-001",
    )

    assert result is False
    assert event_publisher.dispatched == []
    assert broker.sent_messages == []


@pytest.mark.asyncio
async def test_consume_defers_when_new_pending_input_exists() -> None:
    """Known pending input prevents idle hook evaluation and its outcome."""
    continuation_recorder = _ContinuationRecorder()
    event_publisher = _EventPublisher()
    broker = _Broker()
    mailbox_item_repository = _MailboxRepository(pending=True)
    toolkit = _IdleToolkit(
        [GoalSessionContinuationInput(content="", metadata={"source": "goal"})]
    )

    result = await _service(
        continuation_recorder=continuation_recorder,
        event_publisher=event_publisher,
        broker=broker,
        mailbox_item_repository=mailbox_item_repository,
    ).consume(
        _snapshot(),
        toolkits=[ToolkitBinding(toolkit, "goal", "goal", False)],
        run_id="run-001",
    )

    assert result is False
    assert toolkit.contexts == []
    assert continuation_recorder.enqueued_batches == []
    assert event_publisher.dispatched == []
    assert broker.sent_messages == []
    assert mailbox_item_repository.checked_session_ids == ["session-001"]


@pytest.mark.asyncio
async def test_consume_rejects_owner_generation_takeover() -> None:
    """A stale owner hands the idle continuation boundary to a fresh Worker."""
    continuation_recorder = _ContinuationRecorder()
    event_publisher = _EventPublisher()
    broker = _Broker()
    toolkit = _IdleToolkit(
        [GoalSessionContinuationInput(content="", metadata={"source": "goal"})]
    )

    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await _service(
            continuation_recorder=continuation_recorder,
            event_publisher=event_publisher,
            broker=broker,
            agent_session_repository=_AgentSessionRepository(owner_generation=2),
        ).consume(
            _snapshot(),
            toolkits=[ToolkitBinding(toolkit, "goal", "goal", False)],
            run_id="run-001",
        )

    assert toolkit.contexts == []
    assert continuation_recorder.enqueued_batches == []
    assert event_publisher.dispatched == []
    assert broker.sent_messages == []


@pytest.mark.asyncio
async def test_consume_stores_continuation_and_sends_wake_up() -> None:
    """Idle continuation is buffered before sending the wake-up signal."""
    continuation_recorder = _ContinuationRecorder()
    event_publisher = _EventPublisher()
    broker = _Broker()
    repository = _AgentSessionRepository()
    toolkit = _IdleToolkit(
        [
            GoalSessionContinuationInput(
                content="ignored",
                metadata={"source": "goal", "goal_objective": "Ship"},
            )
        ]
    )

    result = await _service(
        continuation_recorder=continuation_recorder,
        event_publisher=event_publisher,
        broker=broker,
        agent_session_repository=repository,
    ).consume(
        snapshot := _snapshot(),
        toolkits=[ToolkitBinding(toolkit, "goal", "goal", False)],
        run_id="run-001",
    )

    assert result is True
    assert len(toolkit.contexts) == 1
    context = toolkit.contexts[0]
    assert context.workspace_id == "workspace-001"
    assert context.agent_id == "agent-001"
    assert context.session_id == "session-001"
    assert context.run_id == "run-001"
    assert context.reason == "completed"

    assert len(continuation_recorder.enqueued_batches) == 1
    [enqueue] = continuation_recorder.enqueued_batches[0]
    assert enqueue.session_id == "session-001"
    assert enqueue.kind == MailboxItemKind.GOAL_CONTINUATION
    assert enqueue.metadata == {
        "source": "goal",
        "goal_objective": "Ship",
        "provider_slug": "goal",
    }
    assert enqueue.content == "ignored"
    assert enqueue.idempotency_key == "idle_continuation:run-001:goal:0"
    assert repository.consumed == [("session-001", "run-001", True)]
    assert len(event_publisher.dispatched) == 1
    assert event_publisher.dispatched[0][0] == "session-001"
    assert event_publisher.dispatched[0][1].kind == EventKind.GOAL_CONTINUATION
    assert broker.sent_messages == [SessionWakeUp(session_id=snapshot.session_id)]


@pytest.mark.asyncio
async def test_consume_stores_external_channel_continuation_separately() -> None:
    """External Channel continuation never becomes a Goal continuation."""
    continuation_recorder = _ContinuationRecorder()
    event_publisher = _EventPublisher()
    broker = _Broker()
    repository = _AgentSessionRepository()
    toolkit = _IdleToolkit(
        [
            ExternalChannelSessionContinuationInput(
                content="",
                metadata={
                    "source": "external_channel",
                    "active_bindings": "binding-handle",
                },
            )
        ]
    )

    result = await _service(
        continuation_recorder=continuation_recorder,
        event_publisher=event_publisher,
        broker=broker,
        agent_session_repository=repository,
    ).consume(
        snapshot := _snapshot(),
        toolkits=[
            ToolkitBinding(
                toolkit,
                "external_channel",
                "external_channel",
                False,
            )
        ],
        run_id="run-001",
    )

    assert result is True
    [enqueue] = continuation_recorder.enqueued_batches[0]
    assert enqueue.kind == MailboxItemKind.EXTERNAL_CHANNEL_CONTINUATION
    assert enqueue.metadata == {
        "source": "external_channel",
        "active_bindings": "binding-handle",
        "provider_slug": "external_channel",
    }
    assert enqueue.idempotency_key == ("idle_continuation:run-001:external_channel:0")
    assert event_publisher.dispatched[0][1].kind == (
        EventKind.EXTERNAL_CHANNEL_CONTINUATION
    )
    assert repository.consumed == [("session-001", "run-001", True)]
    assert broker.sent_messages == [SessionWakeUp(session_id=snapshot.session_id)]


@pytest.mark.asyncio
async def test_consume_stores_typed_scheduled_task_continuation() -> None:
    """Scheduled continuation preserves its internal cycle binding and presentation."""
    continuation_recorder = _ContinuationRecorder()
    event_publisher = _EventPublisher()
    broker = _Broker()
    repository = _AgentSessionRepository()
    toolkit = _IdleToolkit(
        [
            ScheduledTaskSessionContinuationInput(
                cycle_id="c" * 32,
                title="Daily report",
                content="Continue the Scheduled Task.",
                metadata={"source": "scheduled_task"},
            )
        ]
    )

    result = await _service(
        continuation_recorder=continuation_recorder,
        event_publisher=event_publisher,
        broker=broker,
        agent_session_repository=repository,
    ).consume(
        snapshot := _snapshot(),
        toolkits=[ToolkitBinding(toolkit, "scheduled", "scheduled", False)],
        run_id="run-001",
    )

    assert result is True
    [enqueue] = continuation_recorder.enqueued_batches[0]
    assert enqueue.kind is MailboxItemKind.SCHEDULED_TASK_CONTINUATION
    assert enqueue.metadata == {
        "source": "scheduled_task",
        "provider_slug": "scheduled",
        "cycle_id": "c" * 32,
        "title": "Daily report",
    }
    assert enqueue.idempotency_key == "idle_continuation:run-001:scheduled:0"
    assert isinstance(enqueue.payload, ScheduledTaskContinuationMailboxPayload)
    assert enqueue.payload.cycle_id == "c" * 32
    assert enqueue.payload.items[0].content == "Continue the Scheduled Task."
    event = event_publisher.dispatched[0][1]
    assert event.kind is EventKind.SCHEDULED_TASK_CONTINUATION
    assert broker.sent_messages == [SessionWakeUp(session_id=snapshot.session_id)]


@pytest.mark.asyncio
async def test_archived_session_keeps_only_matching_scheduled_continuation() -> None:
    """Archived Sessions reject unrelated idle continuations without reopening."""
    continuation_recorder = _ContinuationRecorder()
    event_publisher = _EventPublisher()
    broker = _Broker()
    repository = _AgentSessionRepository(status=AgentSessionStatus.ARCHIVED)
    toolkit = _IdleToolkit(
        [
            GoalSessionContinuationInput(
                content="unrelated",
                metadata={"source": "goal"},
            ),
            ScheduledTaskSessionContinuationInput(
                cycle_id="d" * 32,
                title="Wrong cycle",
                content="unrelated",
                metadata={"source": "scheduled_task"},
            ),
            ScheduledTaskSessionContinuationInput(
                cycle_id="c" * 32,
                title="Daily report",
                content="Continue the preserved cycle.",
                metadata={"source": "scheduled_task"},
            ),
        ]
    )

    result = await _service(
        continuation_recorder=continuation_recorder,
        event_publisher=event_publisher,
        broker=broker,
        agent_session_repository=repository,
    ).consume(
        snapshot := _snapshot(),
        toolkits=[ToolkitBinding(toolkit, "scheduled", "scheduled", False)],
        run_id="run-001",
    )

    assert result is True
    [enqueue] = continuation_recorder.enqueued_batches[0]
    assert enqueue.kind is MailboxItemKind.SCHEDULED_TASK_CONTINUATION
    assert isinstance(enqueue.payload, ScheduledTaskContinuationMailboxPayload)
    assert enqueue.payload.cycle_id == "c" * 32
    assert repository.consumed == [("session-001", "run-001", True)]
    assert broker.sent_messages == [SessionWakeUp(session_id=snapshot.session_id)]


@pytest.mark.asyncio
async def test_consume_uses_snapshot_workspace_for_idle_hook() -> None:
    """Idle hook context uses the canonical execution snapshot workspace."""
    continuation_recorder = _ContinuationRecorder()
    event_publisher = _EventPublisher()
    broker = _Broker()
    repository = _AgentSessionRepository(workspace_id="workspace-authoritative")
    toolkit = _IdleToolkit([])

    result = await _service(
        continuation_recorder=continuation_recorder,
        event_publisher=event_publisher,
        broker=broker,
        agent_session_repository=repository,
    ).consume(
        _snapshot(workspace_id="workspace-snapshot"),
        toolkits=[ToolkitBinding(toolkit, "goal", "goal", False)],
        run_id="run-001",
    )

    assert result is True
    assert toolkit.contexts[0].workspace_id == "workspace-snapshot"
