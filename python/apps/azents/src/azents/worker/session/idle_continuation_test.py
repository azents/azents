"""IdleContinuationService tests."""

import dataclasses
import datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from azents.broker.types import BrokerMessage, SessionBroker, SessionWakeUp
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
from azents.repos.mailbox.data import (
    MailboxItem,
    ScheduledTaskContinuationMailboxPayload,
)
from azents.services.mailbox import (
    MailboxAdmissionResult,
    MailboxEnqueue,
    MailboxService,
)
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.session.execution_snapshot import (
    CanonicalExecutionOwnerGenerationStaleError,
    CanonicalExecutionSnapshot,
)
from azents.worker.session.idle_continuation import IdleContinuationService


class _MailboxService:
    """MailboxService test double."""

    def __init__(self) -> None:
        self.enqueued_batches: list[list[MailboxEnqueue]] = []

    async def enqueue_idle_continuations(
        self,
        session: object,
        inputs: list[MailboxEnqueue],
    ) -> list[MailboxAdmissionResult]:
        """Record the transaction-level enqueue request."""
        del session
        self.enqueued_batches.append(inputs)
        return [
            MailboxAdmissionResult(
                mailbox_item=MailboxItem(
                    id=f"{index + 1:032d}",
                    session_id=input.session_id,
                    kind=input.kind,
                    scheduling_mode=input.scheduling_mode,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    sender_user_id=input.sender_user_id,
                    order_group=f"{index + 1:032d}",
                    order_sequence=0,
                    content=input.content,
                    idempotency_key=input.idempotency_key,
                    metadata=input.metadata,
                    attachments=input.attachments,
                    file_parts=input.file_parts,
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
    ) -> None:
        self.boundary_run_id: str | None = "run-001"
        self.workspace_id = workspace_id
        self.status = status
        self.owner_generation = owner_generation
        self.consumed: list[tuple[str, str, bool]] = []

    async def lock_by_id(
        self,
        session: object,
        session_id: str,
    ) -> _LockedSession:
        """Return a locked Session fixture."""
        del session, session_id
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


class _EventPublisher:
    """WorkerEventPublisher test double."""

    def __init__(self) -> None:
        self.dispatched: list[tuple[str, Event]] = []

    async def dispatch_event(self, session_id: str, event: Event) -> None:
        """Record publish request."""
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


def _service(
    *,
    mailbox_item_service: _MailboxService,
    event_publisher: _EventPublisher,
    broker: _Broker,
    agent_session_repository: _AgentSessionRepository | None = None,
    mailbox_item_repository: _MailboxRepository | None = None,
) -> IdleContinuationService:
    """Create IdleContinuationService under test."""
    return IdleContinuationService(
        mailbox_item_service=cast(MailboxService, mailbox_item_service),
        agent_session_repository=cast(
            Any,
            agent_session_repository or _AgentSessionRepository(),
        ),
        agent_run_repository=cast(Any, _AgentRunRepository()),
        mailbox_item_repository=cast(
            Any,
            mailbox_item_repository or _MailboxRepository(pending=False),
        ),
        scheduled_task_cycle_repository=cast(Any, _CycleRepository()),
        event_publisher=cast(WorkerEventPublisher, event_publisher),
        broker=cast(SessionBroker, broker),
        session_manager=cast(Any, _SessionManager()),
    )


@pytest.mark.asyncio
async def test_consume_defers_when_new_pending_input_exists() -> None:
    """Known pending input prevents idle hook evaluation and its outcome."""
    mailbox_item_service = _MailboxService()
    event_publisher = _EventPublisher()
    broker = _Broker()
    mailbox_item_repository = _MailboxRepository(pending=True)
    toolkit = _IdleToolkit(
        [GoalSessionContinuationInput(content="", metadata={"source": "goal"})]
    )

    result = await _service(
        mailbox_item_service=mailbox_item_service,
        event_publisher=event_publisher,
        broker=broker,
        mailbox_item_repository=mailbox_item_repository,
    ).consume(
        _snapshot(),
        toolkits=[ToolkitBinding(toolkit, "goal", False)],
        run_id="run-001",
    )

    assert result is False
    assert toolkit.contexts == []
    assert mailbox_item_service.enqueued_batches == []
    assert event_publisher.dispatched == []
    assert broker.sent_messages == []
    assert mailbox_item_repository.checked_session_ids == ["session-001"]


@pytest.mark.asyncio
async def test_consume_rejects_owner_generation_takeover() -> None:
    """A stale owner hands the idle continuation boundary to a fresh Worker."""
    mailbox_item_service = _MailboxService()
    event_publisher = _EventPublisher()
    broker = _Broker()
    toolkit = _IdleToolkit(
        [GoalSessionContinuationInput(content="", metadata={"source": "goal"})]
    )

    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await _service(
            mailbox_item_service=mailbox_item_service,
            event_publisher=event_publisher,
            broker=broker,
            agent_session_repository=_AgentSessionRepository(owner_generation=2),
        ).consume(
            _snapshot(),
            toolkits=[ToolkitBinding(toolkit, "goal", False)],
            run_id="run-001",
        )

    assert toolkit.contexts == []
    assert mailbox_item_service.enqueued_batches == []
    assert event_publisher.dispatched == []
    assert broker.sent_messages == []


@pytest.mark.asyncio
async def test_consume_stores_continuation_and_sends_wake_up() -> None:
    """Idle continuation is buffered before sending the wake-up signal."""
    mailbox_item_service = _MailboxService()
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
        mailbox_item_service=mailbox_item_service,
        event_publisher=event_publisher,
        broker=broker,
        agent_session_repository=repository,
    ).consume(
        snapshot := _snapshot(),
        toolkits=[ToolkitBinding(toolkit, "goal", False)],
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

    assert len(mailbox_item_service.enqueued_batches) == 1
    [enqueue] = mailbox_item_service.enqueued_batches[0]
    assert enqueue.session_id == "session-001"
    assert enqueue.kind == MailboxItemKind.GOAL_CONTINUATION
    assert enqueue.scheduling_mode == MailboxSchedulingMode.WAKE_SESSION
    assert enqueue.metadata == {
        "source": "goal",
        "goal_objective": "Ship",
        "provider_slug": "goal",
    }
    assert enqueue.content == "ignored"
    assert enqueue.idempotency_key == "idle_continuation:run-001:goal:0"
    assert enqueue.attachments == []
    assert repository.consumed == [("session-001", "run-001", True)]
    assert len(event_publisher.dispatched) == 1
    assert event_publisher.dispatched[0][0] == "session-001"
    assert event_publisher.dispatched[0][1].kind == EventKind.GOAL_CONTINUATION
    assert broker.sent_messages == [SessionWakeUp(session_id=snapshot.session_id)]


@pytest.mark.asyncio
async def test_consume_stores_external_channel_continuation_separately() -> None:
    """External Channel continuation never becomes a Goal continuation."""
    mailbox_item_service = _MailboxService()
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
        mailbox_item_service=mailbox_item_service,
        event_publisher=event_publisher,
        broker=broker,
        agent_session_repository=repository,
    ).consume(
        snapshot := _snapshot(),
        toolkits=[ToolkitBinding(toolkit, "external_channel", False)],
        run_id="run-001",
    )

    assert result is True
    [enqueue] = mailbox_item_service.enqueued_batches[0]
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
    mailbox_item_service = _MailboxService()
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
        mailbox_item_service=mailbox_item_service,
        event_publisher=event_publisher,
        broker=broker,
        agent_session_repository=repository,
    ).consume(
        snapshot := _snapshot(),
        toolkits=[ToolkitBinding(toolkit, "scheduled", False)],
        run_id="run-001",
    )

    assert result is True
    [enqueue] = mailbox_item_service.enqueued_batches[0]
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
    mailbox_item_service = _MailboxService()
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
        mailbox_item_service=mailbox_item_service,
        event_publisher=event_publisher,
        broker=broker,
        agent_session_repository=repository,
    ).consume(
        snapshot := _snapshot(),
        toolkits=[ToolkitBinding(toolkit, "scheduled", False)],
        run_id="run-001",
    )

    assert result is True
    [enqueue] = mailbox_item_service.enqueued_batches[0]
    assert enqueue.kind is MailboxItemKind.SCHEDULED_TASK_CONTINUATION
    assert isinstance(enqueue.payload, ScheduledTaskContinuationMailboxPayload)
    assert enqueue.payload.cycle_id == "c" * 32
    assert repository.consumed == [("session-001", "run-001", True)]
    assert broker.sent_messages == [SessionWakeUp(session_id=snapshot.session_id)]


@pytest.mark.asyncio
async def test_consume_uses_snapshot_workspace_for_idle_hook() -> None:
    """Idle hook context uses the canonical execution snapshot workspace."""
    mailbox_item_service = _MailboxService()
    event_publisher = _EventPublisher()
    broker = _Broker()
    repository = _AgentSessionRepository(workspace_id="workspace-authoritative")
    toolkit = _IdleToolkit([])

    result = await _service(
        mailbox_item_service=mailbox_item_service,
        event_publisher=event_publisher,
        broker=broker,
        agent_session_repository=repository,
    ).consume(
        _snapshot(workspace_id="workspace-snapshot"),
        toolkits=[ToolkitBinding(toolkit, "goal", False)],
        run_id="run-001",
    )

    assert result is True
    assert toolkit.contexts[0].workspace_id == "workspace-snapshot"
