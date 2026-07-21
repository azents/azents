"""IdleContinuationService tests."""

import dataclasses
import datetime
from typing import Any, cast

import pytest

from azents.broker.types import BrokerMessage, SessionBroker, SessionWakeUp
from azents.core.enums import EventKind, InputBufferKind, InputBufferSchedulingMode
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

    def __init__(self) -> None:
        self.enqueued_batches: list[list[InputBufferEnqueue]] = []

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
                    scheduling_mode=input.scheduling_mode,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
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


@dataclasses.dataclass(frozen=True)
class _LockedSession:
    """Minimal locked AgentSession projection."""

    pending_idle_continuation_run_id: str | None
    pending_command_id: str | None


class _AgentSessionRepository:
    """AgentSessionRepository test double."""

    def __init__(self) -> None:
        self.boundary_run_id: str | None = "run-001"
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
        )

    async def consume_pending_idle_continuation(
        self,
        session: object,
        *,
        session_id: str,
        run_id: str,
        continue_running: bool,
    ) -> bool:
        """Consume the matching durable boundary."""
        del session
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


class _InputBufferRepository:
    """InputBufferRepository test double."""

    def __init__(self, *, pending: bool) -> None:
        self.pending = pending
        self.checked_session_ids: list[str] = []

    async def has_by_session_id_and_scheduling_mode(
        self,
        session: object,
        *,
        session_id: str,
        scheduling_mode: InputBufferSchedulingMode,
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
    input_buffer_repository: _InputBufferRepository | None = None,
) -> IdleContinuationService:
    """Create IdleContinuationService under test."""
    return IdleContinuationService(
        input_buffer_service=cast(InputBufferService, input_buffer_service),
        agent_session_repository=cast(
            Any,
            agent_session_repository or _AgentSessionRepository(),
        ),
        agent_run_repository=cast(Any, _AgentRunRepository()),
        input_buffer_repository=cast(
            Any,
            input_buffer_repository or _InputBufferRepository(pending=False),
        ),
        event_publisher=cast(WorkerEventPublisher, event_publisher),
        broker=cast(SessionBroker, broker),
        session_manager=cast(Any, _SessionManager()),
    )


@pytest.mark.asyncio
async def test_consume_defers_when_new_pending_input_exists() -> None:
    """Known pending input prevents idle hook evaluation and its outcome."""
    input_buffer_service = _InputBufferService()
    event_publisher = _EventPublisher()
    broker = _Broker()
    input_buffer_repository = _InputBufferRepository(pending=True)
    toolkit = _IdleToolkit(
        [SessionContinuationInput(content="", metadata={"source": "goal"})]
    )

    result = await _service(
        input_buffer_service=input_buffer_service,
        event_publisher=event_publisher,
        broker=broker,
        input_buffer_repository=input_buffer_repository,
    ).consume(
        _message(),
        toolkits=[ToolkitBinding(toolkit, "goal", False)],
        run_id="run-001",
    )

    assert result is False
    assert toolkit.contexts == []
    assert input_buffer_service.enqueued_batches == []
    assert event_publisher.dispatched == []
    assert broker.sent_messages == []
    assert input_buffer_repository.checked_session_ids == ["session-001"]


@pytest.mark.asyncio
async def test_consume_stores_continuation_and_sends_wake_up() -> None:
    """Idle continuation is buffered before sending the wake-up signal."""
    input_buffer_service = _InputBufferService()
    event_publisher = _EventPublisher()
    broker = _Broker()
    repository = _AgentSessionRepository()
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
        agent_session_repository=repository,
    ).consume(
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
    assert enqueue.scheduling_mode == InputBufferSchedulingMode.WAKE_SESSION
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
    assert broker.sent_messages == [message]
