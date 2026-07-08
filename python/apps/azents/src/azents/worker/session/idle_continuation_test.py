"""IdleContinuationService tests."""

import datetime
from typing import Any, cast

import pytest

from azents.broker.types import BrokerMessage, SessionBroker, SessionWakeUp
from azents.core.enums import EventKind, InputBufferKind
from azents.core.tools import Toolkit, ToolkitState, ToolkitStatus, TurnContext
from azents.engine.events.types import Event
from azents.engine.hooks.types import (
    RuntimeHooks,
    SessionContinuationInput,
    SessionIdleHookContext,
    SessionIdleResult,
)
from azents.engine.run.contracts import ToolkitBinding
from azents.repos.input_buffer.data import InputBuffer
from azents.services.input_buffer import (
    InputBufferEnqueue,
    InputBufferEnqueueResult,
    InputBufferService,
)
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.session.idle_continuation import IdleContinuationService


class _InputBufferService:
    """InputBufferService test double."""

    def __init__(self, *, pending: bool) -> None:
        self.pending = pending
        self.checked_session_ids: list[str] = []
        self.enqueued_batches: list[list[InputBufferEnqueue]] = []

    async def has_pending_session_input_buffers(self, session_id: str) -> bool:
        """Record and return whether pending input buffer exists."""
        self.checked_session_ids.append(session_id)
        return self.pending

    async def enqueue_many(
        self,
        session: object,
        inputs: list[InputBufferEnqueue],
    ) -> list[InputBufferEnqueueResult]:
        """Record the transaction-level enqueue request."""
        del session
        self.enqueued_batches.append(inputs)
        return [
            InputBufferEnqueueResult(
                input_buffer=InputBuffer(
                    id=f"{index + 1:032d}",
                    session_id=input.session_id,
                    kind=input.kind,
                    actor_user_id=input.actor_user_id,
                    content=input.content,
                    idempotency_key=input.idempotency_key,
                    metadata=input.metadata,
                    attachments=input.attachments,
                    file_parts=input.file_parts,
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


class _AgentSessionRepository:
    """AgentSessionRepository test double."""

    def __init__(self) -> None:
        self.marked_running: list[str] = []

    async def mark_running_for_input_wakeup(
        self,
        session: object,
        session_id: str,
    ) -> None:
        """Record wake transition."""
        del session
        self.marked_running.append(session_id)


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


def _message() -> SessionWakeUp:
    """Create wake-up message for tests."""
    return SessionWakeUp(
        agent_id="agent-001",
        session_id="session-001",
        user_id="user-001",
        additional_system_prompt=None,
        interface=None,
        workspace_id="workspace-001",
        workspace_handle=None,
    )


def _service(
    *,
    input_buffer_service: _InputBufferService,
    event_publisher: _EventPublisher,
    broker: _Broker,
    agent_session_repository: _AgentSessionRepository | None = None,
) -> IdleContinuationService:
    """Create IdleContinuationService under test."""
    return IdleContinuationService(
        input_buffer_service=cast(InputBufferService, input_buffer_service),
        agent_session_repository=cast(
            Any,
            agent_session_repository or _AgentSessionRepository(),
        ),
        event_publisher=cast(WorkerEventPublisher, event_publisher),
        broker=cast(SessionBroker, broker),
        session_manager=cast(Any, _SessionManager()),
    )


@pytest.mark.asyncio
async def test_enqueue_uses_single_runner_boundary_for_pending_input_check() -> None:
    """Idle continuation does not repeat the runner's pending-input check."""
    input_buffer_service = _InputBufferService(pending=True)
    event_publisher = _EventPublisher()
    broker = _Broker()
    toolkit = _IdleToolkit(
        [SessionContinuationInput(content="", metadata={"source": "goal"})]
    )

    result = await _service(
        input_buffer_service=input_buffer_service,
        event_publisher=event_publisher,
        broker=broker,
    ).enqueue(
        _message(),
        toolkits=[ToolkitBinding(toolkit, "goal", False)],
        run_id="run-001",
    )

    assert result is True
    assert input_buffer_service.checked_session_ids == []
    assert len(toolkit.contexts) == 1
    assert len(input_buffer_service.enqueued_batches) == 1
    assert len(event_publisher.dispatched) == 1
    assert broker.sent_messages == [_message()]


@pytest.mark.asyncio
async def test_enqueue_stores_continuation_and_sends_wake_up() -> None:
    """Idle continuation is buffered before sending the wake-up signal."""
    input_buffer_service = _InputBufferService(pending=False)
    event_publisher = _EventPublisher()
    broker = _Broker()
    toolkit = _IdleToolkit(
        [
            SessionContinuationInput(
                content="ignored",
                metadata={"source": "goal", "goal_objective": "Ship"},
            )
        ]
    )

    result = await _service(
        input_buffer_service=input_buffer_service,
        event_publisher=event_publisher,
        broker=broker,
    ).enqueue(
        message := _message(),
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

    assert len(input_buffer_service.enqueued_batches) == 1
    [enqueue] = input_buffer_service.enqueued_batches[0]
    assert enqueue.session_id == "session-001"
    assert enqueue.kind == InputBufferKind.GOAL_CONTINUATION
    assert enqueue.metadata == {
        "source": "goal",
        "goal_objective": "Ship",
        "provider_slug": "goal",
    }
    assert enqueue.content == "ignored"
    assert enqueue.attachments == []
    assert len(event_publisher.dispatched) == 1
    assert event_publisher.dispatched[0][0] == "session-001"
    assert event_publisher.dispatched[0][1].kind == EventKind.GOAL_CONTINUATION
    assert broker.sent_messages == [message]
