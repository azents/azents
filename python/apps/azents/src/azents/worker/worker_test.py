"""Engine Worker tests."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import azents.worker.session.supervisor as session_runner_supervisor_module
import azents.worker.session.waiter as session_runner_waiter_module
from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.types import (
    SessionBroker,
    SessionStopSignal,
    SessionWakeUp,
)
from azents.core.enums import (
    AgentRunStatus,
    EventKind,
)
from azents.core.inference_profile import (
    RequestedInferenceProfile,
    SessionInferenceState,
)
from azents.core.tools import Toolkit, ToolkitState, ToolkitStatus, TurnContext
from azents.engine.events.builders import make_system_error_event
from azents.engine.events.engine_events import ContentDelta, ReasoningDelta
from azents.engine.events.types import (
    ActiveToolCall,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    NativeArtifact,
    ReasoningPayload,
    SystemErrorPayload,
)
from azents.engine.events.user_messages import make_run_user_message
from azents.engine.run.contracts import AgentEngineProtocol, ToolkitBinding
from azents.engine.run.emit import PublishedEvent
from azents.engine.run.errors import CompactionFailedError, UserVisibleRuntimeError
from azents.engine.run.model_transport import InMemoryModelTransportState
from azents.engine.run.types import (
    CheckStop,
    PollMessages,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_session.data import PendingSessionCommand
from azents.services.input_buffer import (
    InputBufferService,
    PendingInputInferenceProfile,
    PromotedInputBuffers,
    TurnEffect,
)
from azents.services.subagent_terminal_result import SubagentTerminalResultService
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.live.event_projector import LiveEventProjector
from azents.worker.run.executor import OperationActionProcessResult, RunExecutor
from azents.worker.run.helpers import (
    apply_active_tool_call_event,
    observed_terminal_run_event,
)
from azents.worker.run.results import RunExecutionResult
from azents.worker.session.contracts import PrepareToolkits
from azents.worker.session.idle_continuation import IdleContinuationService
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.runner import SessionRunner
from azents.worker.session.supervisor import RunStopController, ToolAdmissionBarrier
from azents.worker.session.user_stop_finalizer import UserStopFinalizer
from azents.worker.session.waiter import (
    HeartbeatResult,
    IdleTimeoutResult,
    MessageResult,
    RunnerWaitResult,
    SessionRunnerWaiter,
    ShutdownResult,
)


class _Broadcast:
    """WebSocketBroadcast test double."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    async def publish(self, session_id: str, event: dict[str, object]) -> None:
        """Record delivered broadcast payloads in order."""
        self.events.append((session_id, event))


class _SessionRunnerEventPublisher:
    """Event publisher for SessionRunner tests."""

    def __init__(self, host: "_Host") -> None:
        self.host = host

    async def dispatch_event(
        self,
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        """Replace event publishing with Host dispatch records."""
        await self.host.dispatch_event(session_id, event)


class _InputBufferService:
    """InputBufferService test double."""

    def __init__(self, promoted: PromotedInputBuffers) -> None:
        self.promoted = promoted
        self.calls: list[tuple[str, str | None]] = []
        self.consumed = False

    async def peek_pending_inference_profile(
        self,
        session_id: str,
    ) -> PendingInputInferenceProfile:
        """Project the configured result until it has been consumed."""
        del session_id
        return PendingInputInferenceProfile(
            input_buffer_id=None if self.consumed else "buffer-1",
            requires_inference=False,
            exists=not self.consumed,
            requested_inference_profile=(
                self.promoted.requested_inference_profile if not self.consumed else None
            ),
        )

    async def flush_session_input_buffers(
        self,
        *,
        session_id: str,
        model: str | None,
        required_inference_profile: RequestedInferenceProfile | None,
        expected_buffer_id: str | None,
        prepared_inference_state: SessionInferenceState | None,
        profile_resolution_failure: str | None,
        active_run_id: str | None,
        limit: int | None = None,
        include_action_messages: bool = True,
    ) -> PromotedInputBuffers:
        """Store flush call arguments and return specified result."""
        del (
            required_inference_profile,
            expected_buffer_id,
            prepared_inference_state,
            profile_resolution_failure,
            active_run_id,
            limit,
            include_action_messages,
        )
        self.calls.append((session_id, model))
        if self.consumed:
            return PromotedInputBuffers(
                worktree_action=None,
                turn_effect=TurnEffect.NEUTRAL,
                requested_inference_profile=None,
                user_messages=[],
                events=[],
                promoted_event_ids=[],
                deleted_buffer_ids=[],
                changed_session_agent_ids=[],
                claimed_count=0,
                inserted_count=0,
                deduped_count=0,
            )
        self.consumed = True
        return self.promoted


class _SessionScope(AbstractAsyncContextManager[AsyncSession]):
    """DB session context for tests."""

    async def __aenter__(self) -> AsyncSession:
        """Return test session."""
        return cast(AsyncSession, object())

    async def __aexit__(self, *exc_info: object) -> None:
        """No resources to clean up."""


class _SessionManager:
    """session manager for tests."""

    def __call__(self) -> _SessionScope:
        """Return new session scope."""
        return _SessionScope()


class _Broker:
    """SessionBroker test double."""

    def __init__(self) -> None:
        self.renewed_session_ids: list[str] = []
        self.owner_heartbeat_session_ids: list[str] = []
        self.published_events: list[tuple[str, PublishedEvent]] = []

    async def renew_session_ttl(self, session_id: str) -> None:
        """Record session for TTL refresh call."""
        self.renewed_session_ids.append(session_id)

    async def renew_session_owner_heartbeat(self, session_id: str) -> None:
        """Record session for Owner heartbeat refresh call."""
        self.owner_heartbeat_session_ids.append(session_id)

    async def publish_event(self, session_id: str, event: PublishedEvent) -> None:
        """Record Broker publish call."""
        self.published_events.append((session_id, event))


class _LiveEventStore:
    """LiveEventStore test double."""

    def __init__(
        self,
        before: list[Event],
        after: list[Event],
    ) -> None:
        self._before = before
        self._after = after
        self._listed = 0
        self.removed_counterparts: list[str] = []
        self.assistant_deltas: list[tuple[str, str, int]] = []
        self.reasoning_deltas: list[
            tuple[str, str, str | None, int | None, int | None]
        ] = []
        self.cleared_session_ids: list[str] = []
        self.removed_events: list[tuple[str, str]] = []

    async def list_by_session_id(self, session_id: str) -> list[Event]:
        """Return snapshots before/after removal according to call order."""
        del session_id
        self._listed += 1
        return self._before if self._listed == 1 else self._after

    async def remove_live_counterpart(self, event: Event) -> None:
        """Record removal request event id."""
        self.removed_counterparts.append(event.id)

    async def clear_session(self, session_id: str) -> None:
        """Record clear request Session ID."""
        self.cleared_session_ids.append(session_id)

    async def remove(self, session_id: str, event_id: str) -> None:
        """Record remove request event ID."""
        self.removed_events.append((session_id, event_id))

    async def append_assistant_delta(
        self,
        session_id: str,
        *,
        delta: str,
        content_index: int,
    ) -> Event:
        """Record Assistant delta append and return live event."""
        self.assistant_deltas.append((session_id, delta, content_index))
        return Event(
            id="2123456789abcdef0123456789abcdec",
            session_id=session_id,
            kind=EventKind.ASSISTANT_MESSAGE,
            payload=AssistantMessagePayload(
                content=delta,
                attachments=[],
                native_artifact=NativeArtifact(
                    compat_key="azents-live:live_projection:azents:live:1",
                    adapter="azents-live",
                    native_format="live_projection",
                    provider="azents",
                    model="live",
                    schema_version="1",
                    item={"live_projection": "assistant_message"},
                ),
            ),
            created_at=datetime.now(timezone.utc),
        )

    async def append_reasoning_delta(
        self,
        session_id: str,
        *,
        delta: str,
        item_id: str | None,
        output_index: int | None,
        summary_index: int | None,
    ) -> Event:
        """Record Reasoning delta append and return live event."""
        self.reasoning_deltas.append(
            (session_id, delta, item_id, output_index, summary_index)
        )
        return Event(
            id="3123456789abcdef0123456789abcded",
            session_id=session_id,
            kind=EventKind.REASONING,
            payload=ReasoningPayload(
                text=delta,
                summary=None,
                native_artifact=NativeArtifact(
                    compat_key="azents-live:live_projection:azents:live:1",
                    adapter="azents-live",
                    native_format="live_projection",
                    provider="azents",
                    model="live",
                    schema_version="1",
                    item={"live_projection": "reasoning"},
                ),
            ),
            created_at=datetime.now(timezone.utc),
        )


class _AgentSessionRepository:
    """AgentSessionRepository test double."""

    def __init__(self, host: "_Host") -> None:
        self.host = host
        self.queried_session_ids: list[str] = []

    async def get_pending_command_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> PendingSessionCommand | None:
        """Return pending command specified by test."""
        del session
        self.queried_session_ids.append(session_id)
        if not self.host.pending_command_result:
            return None
        return PendingSessionCommand(
            id="command-001",
            name="compact",
            payload={},
            requester_user_id="user-001",
            created_at=datetime.now(timezone.utc),
        )


class _RunExecutor:
    """RunExecutor test double."""

    def __init__(self, host: "_Host") -> None:
        self.host = host

    async def finalize_unhandled_active_run(
        self,
        session_id: str,
        exc: Exception,
        *,
        dispatch_event: Callable[[str, PublishedEvent], Awaitable[None]],
    ) -> str | None:
        """Report that command-only test failures have no active Run."""
        del session_id, exc, dispatch_event
        return None

    async def resolve_idle_continuation_toolkits(
        self,
        message: SessionWakeUp,
        *,
        run_id: str,
        prepare_toolkits: PrepareToolkits,
        dispatch_event: Callable[[str, PublishedEvent], Awaitable[None]],
    ) -> list[ToolkitBinding]:
        """Return the configured recovered idle hook toolkit snapshot."""
        del message, prepare_toolkits, dispatch_event
        self.host.idle_continuation_resolution_run_ids.append(run_id)
        return []

    async def execute(
        self,
        message: SessionWakeUp,
        *,
        poll_fn: PollMessages | None,
        check_stop: CheckStop | None,
        prepare_toolkits: PrepareToolkits | None,
        shutdown_event: asyncio.Event,
        dispatch_event: Callable[[str, PublishedEvent], Awaitable[None]],
        owner_generation: int,
        tool_admission_barrier: object,
        model_transport_state: object,
        command: PendingSessionCommand | None = None,
    ) -> RunExecutionResult:
        """Delegate to Host message handling fake."""
        del (
            shutdown_event,
            dispatch_event,
            owner_generation,
            tool_admission_barrier,
            model_transport_state,
        )
        if command is not None:
            self.host.commands.append(command)
            self.host.command_processed.set()
            if self.host.command_error is not None:
                raise self.host.command_error
            self.host.pending_command_result = False
            self.host.pending_idle_continuation_run_id = "run-001"
            return RunExecutionResult(
                toolkits=[],
                terminal_event_observed=True,
                no_actionable_work=False,
                run_id="run-001",
                terminal_run_status=AgentRunStatus.COMPLETED,
            )
        return await self.host.process_message(
            message,
            poll_fn=poll_fn,
            check_stop=check_stop,
            prepare_toolkits=prepare_toolkits,
        )


class _PendingInputBufferService:
    """InputBufferService test double."""

    def __init__(self, host: "_Host") -> None:
        self.host = host

    async def has_pending_session_input_buffers(self, session_id: str) -> bool:
        """Return pending buffer existence specified by test."""
        return session_id in self.host.pending_input_session_ids

    async def has_pending_wake_session_input_buffers(
        self,
        session_id: str,
    ) -> bool:
        """Return wake-producing pending buffer existence specified by test."""
        return session_id in self.host.pending_input_session_ids


class _SubagentTerminalResultService:
    """SubagentTerminalResultService test double."""

    def __init__(self, host: "_Host") -> None:
        self.host = host

    async def deliver_pending_for_source_session(
        self,
        source_session_id: str,
        *,
        repair_source: str,
    ) -> None:
        """Record terminal delivery repair requests."""
        self.host.terminal_result_delivery_calls.append(
            (source_session_id, repair_source)
        )


class _IdleContinuationService:
    """IdleContinuationService test double."""

    def __init__(self, host: "_Host") -> None:
        self.host = host
        self.calls: list[tuple[SessionWakeUp, list[ToolkitBinding]]] = []

    async def consume(
        self,
        message: SessionWakeUp,
        *,
        toolkits: Sequence[ToolkitBinding],
        run_id: str,
    ) -> bool:
        """Record one durable idle continuation outcome."""
        self.calls.append((message, list(toolkits)))
        self.host.idle_continuation_calls.append((message, list(toolkits)))
        if self.host.pending_idle_continuation_run_id != run_id:
            return False
        self.host.idle_mark_attempted.set()
        if not self.host.idle_transition_allowed:
            return False
        self.host.pending_idle_continuation_run_id = None
        self.host.idle_session_ids.append(message.session_id)
        self.host.lifecycle_events.append("idle_continuation")
        return True


class _UserStopFinalizer:
    """UserStopFinalizer test double."""

    def __init__(self, host: "_Host") -> None:
        self.host = host

    async def finalize(
        self,
        session_id: str,
        *,
        run_id: str | None,
        active_tool_calls: Sequence[ActiveToolCall],
    ) -> None:
        """Delegate to Host user stop finalization fake."""
        await self.host.finalize_user_stop(
            session_id,
            run_id=run_id,
            active_tool_calls=active_tool_calls,
        )


class _Host:
    """Host for SessionRunner tests."""

    def __init__(self) -> None:
        self._shutdown_event = asyncio.Event()
        self.command_processed = asyncio.Event()
        self.idle_mark_attempted = asyncio.Event()
        self.cleared_session_ids: list[str] = []
        self.finalized_user_stop_session_ids: list[str] = []
        self.idle_session_ids: list[str] = []
        self.idle_continuation_calls: list[
            tuple[SessionWakeUp, list[ToolkitBinding]]
        ] = []
        self.idle_continuation_result = False
        self.lifecycle_events: list[str] = []
        self.released_session_ids: list[str] = []
        self.heartbeat_session_ids: list[str] = []
        self.owner_heartbeat_session_ids: list[str] = []
        self.pending_input_session_ids: set[str] = set()
        self.pending_idle_continuation_run_id: str | None = None
        self.terminal_result_delivery_calls: list[tuple[str, str]] = []
        self.stop_request_session_ids: set[str] = set()
        self.processed_messages: list[SessionWakeUp] = []
        self.handover_messages: list[SessionWakeUp] = []
        self.pending_command_result = False
        self.message_started = asyncio.Event()
        self.message_release = asyncio.Event()
        self.message_cancelled = asyncio.Event()
        self.cancel_cleanup_release = asyncio.Event()
        self.stop_first_message = False
        self.block_message_until_release = False
        self.block_message_until_cancel = False
        self.block_after_cancel = False
        self.shutdown_before_message_returns = False
        self.idle_transition_allowed = True
        self.running_agent_run_exists = False
        self.terminal_event_observed = True
        self.no_actionable_message_numbers: set[int] = set()
        self.command_error: Exception | None = None
        self.commands: list[PendingSessionCommand] = []
        self.dispatched_events: list[tuple[str, PublishedEvent]] = []
        self.event_dispatched = asyncio.Event()
        self.owner_generation_claims = 0
        self.idle_continuation_resolution_run_ids: list[str] = []

    @property
    def shutdown_event(self) -> asyncio.Event:
        """Return global shutdown event."""
        return self._shutdown_event

    async def claim_owner_generation(self, session_id: str) -> int:
        """Return one durable ownership generation for the test runner."""
        del session_id
        self.owner_generation_claims += 1
        return self.owner_generation_claims

    async def process_message(
        self,
        message: SessionWakeUp,
        *,
        poll_fn: PollMessages | None,
        check_stop: CheckStop | None,
        prepare_toolkits: PrepareToolkits | None,
    ) -> RunExecutionResult:
        """This test does not handle normal messages."""
        _ = poll_fn, prepare_toolkits
        self.processed_messages.append(message)
        self.message_started.set()
        if self.block_message_until_release:
            await self.message_release.wait()
        if self.block_message_until_cancel:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.message_cancelled.set()
                if self.block_after_cancel:
                    await self.cancel_cleanup_release.wait()
                raise
        if self.stop_first_message and len(self.processed_messages) == 1:
            assert check_stop is not None
            while not await check_stop():
                await asyncio.sleep(0)
        if self.shutdown_before_message_returns:
            self.shutdown_event.set()
        message_number = len(self.processed_messages)
        terminal_event_observed = (
            self.terminal_event_observed
            and message_number not in self.no_actionable_message_numbers
        )
        if terminal_event_observed:
            self.pending_idle_continuation_run_id = "run-001"
        return RunExecutionResult(
            toolkits=[],
            terminal_event_observed=terminal_event_observed,
            no_actionable_work=message_number in self.no_actionable_message_numbers,
            run_id="run-001",
            terminal_run_status=AgentRunStatus.COMPLETED
            if terminal_event_observed
            else None,
        )

    async def dispatch_event(
        self,
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        """Record Dispatch event call."""
        self.dispatched_events.append((session_id, event))
        self.event_dispatched.set()

    async def save_error_message(
        self,
        session_id: str,
        error: str,
    ) -> Event:
        """This test does not store error messages."""
        return make_system_error_event(session_id=session_id, content=error)

    async def release_session_lock(self, session_id: str) -> None:
        """Store session for lock release call."""
        self.released_session_ids.append(session_id)

    async def clear_session_activity(self, session_id: str) -> None:
        """Store session for activity deletion call."""
        self.cleared_session_ids.append(session_id)
        self.lifecycle_events.append("clear_session_activity")

    async def send_session_wake_up(self, message: SessionWakeUp) -> None:
        """Store wake-up messages sent for handover."""
        self.handover_messages.append(message)

    async def finalize_user_stop(
        self,
        session_id: str,
        *,
        run_id: str | None,
        active_tool_calls: Sequence[ActiveToolCall],
    ) -> None:
        """Store session for user stop finalization call."""
        del run_id, active_tool_calls
        self.finalized_user_stop_session_ids.append(session_id)

    async def mark_session_running(self, session_id: str) -> None:
        """This test does not change run state."""
        _ = session_id

    async def mark_session_idle(self, session_id: str) -> bool:
        """Store session for idle transition call."""
        self.idle_mark_attempted.set()
        if not self.idle_transition_allowed:
            return False
        self.idle_session_ids.append(session_id)
        self.lifecycle_events.append("mark_session_idle")
        return True

    async def has_active_agent_run(self, session_id: str) -> bool:
        """Return test-specified active AgentRun existence."""
        del session_id
        return self.running_agent_run_exists

    async def get_pending_idle_continuation_run_id(
        self,
        session_id: str,
    ) -> str | None:
        """Return test-configured durable idle boundary."""
        del session_id
        return self.pending_idle_continuation_run_id

    async def has_pending_idle_continuation(self, session_id: str) -> bool:
        """Return whether the durable idle boundary remains."""
        del session_id
        return self.pending_idle_continuation_run_id is not None

    async def heartbeat_session(self, session_id: str) -> None:
        """Store session for active owner lease refresh calls."""
        self.heartbeat_session_ids.append(session_id)

    async def renew_session_owner_heartbeat(self, session_id: str) -> None:
        """Store session for owner heartbeat refresh call."""
        self.owner_heartbeat_session_ids.append(session_id)

    async def has_stop_request(self, session_id: str) -> bool:
        """Return stop intent existence specified by test."""
        return session_id in self.stop_request_session_ids


async def _wait_for_owner_heartbeat(host: _Host) -> None:
    """Wait until owner heartbeat call is recorded in test host."""
    while not host.owner_heartbeat_session_ids:
        await asyncio.sleep(0)


class _ScriptedSessionRunnerWaiter:
    """Return deterministic wait results and record idle baselines."""

    def __init__(self, results: Sequence[RunnerWaitResult]) -> None:
        self.results = list(results)
        self.idle_started_at: list[float] = []

    async def wait_next(
        self,
        *,
        inbox: object,
        runner_shutdown: asyncio.Event,
        running_session_id: str | None,
        idle_started_at: float,
    ) -> RunnerWaitResult:
        """Return the next scripted transition without real time."""
        del inbox, runner_shutdown, running_session_id
        self.idle_started_at.append(idle_started_at)
        if not self.results:
            raise AssertionError("No scripted SessionRunner wait result remains")
        return self.results.pop(0)


def _make_session_runner(host: _Host) -> SessionRunner:
    """Create session runner with event publisher injected for tests."""
    return SessionRunner(
        shutdown_event=host.shutdown_event,
        event_publisher=cast(
            WorkerEventPublisher,
            _SessionRunnerEventPublisher(host),
        ),
        session_lifecycle=cast(SessionLifecycleService, host),
        session_manager=cast(SessionManager[AsyncSession], _SessionManager()),
        agent_session_repository=_AgentSessionRepository(host),
        input_buffer_service=cast(
            InputBufferService,
            _PendingInputBufferService(host),
        ),
        subagent_terminal_result_service=cast(
            SubagentTerminalResultService,
            _SubagentTerminalResultService(host),
        ),
        idle_continuation_service=cast(
            IdleContinuationService,
            _IdleContinuationService(host),
        ),
        user_stop_finalizer=cast(UserStopFinalizer, _UserStopFinalizer(host)),
        run_executor=cast(RunExecutor, _RunExecutor(host)),
        engine=cast(AgentEngineProtocol, host),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )


def _start_session_runner(host: _Host) -> SessionRunner:
    """Explicitly start session runner loop in test."""
    runner = _make_session_runner(host)
    asyncio.create_task(runner.run())
    return runner


def _wake_up(
    *,
    session_id: str = "session-001",
    agent_id: str = "agent-001",
    user_id: str | None = "user-001",
) -> SessionWakeUp:
    """Create wake-up envelope for tests."""
    return SessionWakeUp(
        agent_id=agent_id,
        session_id=session_id,
        user_id=user_id,
        additional_system_prompt=None,
        interface=None,
        workspace_id="workspace-001",
        workspace_handle=None,
    )


def _make_worker_event_publisher(
    live_event_store: _LiveEventStore,
    *,
    broadcast: _Broadcast,
    broker: _Broker,
) -> WorkerEventPublisher:
    """Create event publisher for tests."""
    projector = LiveEventProjector(
        live_event_store=cast(Any, live_event_store),
        broadcast=cast(WebSocketBroadcast, broadcast),
        session_manager=cast(Any, _SessionManager()),
        agent_run_repository=cast(Any, object()),
    )
    return WorkerEventPublisher(
        broker=cast(SessionBroker, broker),
        broadcast=cast(WebSocketBroadcast, broadcast),
        live_event_projector=projector,
    )


class _DummyConfig(BaseModel):
    """toolkit config model for tests."""


class _TrackingToolkit(Toolkit[_DummyConfig]):
    """Test toolkit tracking whether ``__aenter__`` was called."""

    def __init__(self, events: list[str] | None = None, name: str = "toolkit") -> None:
        self.events = events
        self.name = name
        self.entered = False

    async def update_context(self, context: TurnContext) -> ToolkitState:
        del context
        if self.events is not None:
            self.events.append(f"update:{self.name}")
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])

    async def __aenter__(self) -> "_TrackingToolkit":
        if self.events is not None:
            self.events.append(f"enter:{self.name}")
        self.entered = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Record whether exit was called."""
        if self.events is not None:
            self.events.append(f"exit:{self.name}")


async def _noop_publish_event(event: PublishedEvent) -> None:
    """publish_event no-op for tests."""
    _ = event


async def _wait_until(predicate: Callable[[], bool]) -> None:
    """Wait with short yields until condition becomes true."""
    while not predicate():
        await asyncio.sleep(0)


def test_observed_terminal_run_event_requires_terminal_event() -> None:
    """Run ended without Terminal event is not target of idle cleanup."""

    assert observed_terminal_run_event(
        run_completed=True,
        terminal_run_status=AgentRunStatus.COMPLETED,
    )
    assert observed_terminal_run_event(
        run_completed=False,
        terminal_run_status=AgentRunStatus.STOPPED,
    )
    assert not observed_terminal_run_event(
        run_completed=False,
        terminal_run_status=None,
    )
    assert not observed_terminal_run_event(
        run_completed=False,
        terminal_run_status=AgentRunStatus.CANCELLED,
    )


@pytest.mark.asyncio
async def test_tool_admission_barrier_orders_admission_before_close() -> None:
    """Close waits for admitted persistence and rejects later admission."""
    barrier = ToolAdmissionBarrier()
    action_started = asyncio.Event()
    release_action = asyncio.Event()

    async def action() -> None:
        action_started.set()
        await release_action.wait()

    admission_task = asyncio.create_task(barrier.run_if_open(action))
    await action_started.wait()
    close_task = asyncio.create_task(barrier.close())
    await asyncio.sleep(0)
    assert not close_task.done()

    release_action.set()
    assert await admission_task is True
    await close_task
    assert await barrier.run_if_open(action) is False


@pytest.mark.asyncio
async def test_run_stop_controller_user_stop_cancels_active_task_once() -> None:
    """RunStopController delivers user stop as cancel idempotently."""
    controller = RunStopController()
    cancelled = asyncio.Event()

    async def wait_forever() -> RunExecutionResult:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return RunExecutionResult(
            toolkits=[],
            terminal_event_observed=False,
            no_actionable_work=False,
        )

    task = asyncio.create_task(wait_forever())
    controller.register_active_task(task)
    await asyncio.sleep(0)

    try:
        assert controller.request_user_stop()
        assert not controller.request_user_stop()
        await asyncio.wait_for(cancelled.wait(), timeout=1)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    controller.clear_active_task(task)
    assert controller.user_stop_requested


@pytest.mark.asyncio
async def test_idle_stop_does_not_latch_next_run() -> None:
    """Idle stop does not remain as latch that immediately stops next run."""
    host = _Host()
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(SessionStopSignal(session_id="session-001", user_id="user-001"))
        await asyncio.sleep(0)
        runner.enqueue(message)
        await asyncio.wait_for(host.message_started.wait(), timeout=1)
    finally:
        await runner.shutdown()

    assert host.processed_messages == [message]
    assert not host.message_cancelled.is_set()


@pytest.mark.asyncio
async def test_terminal_run_marks_idle_before_idle_continuation() -> None:
    """Terminal run moves idle before collecting continuation input."""
    host = _Host()
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await _wait_until(lambda: bool(host.idle_continuation_calls))
    finally:
        await runner.shutdown()

    assert host.idle_session_ids == ["session-001"]
    assert host.idle_continuation_calls == [(message, [])]
    assert host.terminal_result_delivery_calls == [
        ("session-001", "source_session_reuse"),
        ("session-001", "terminal_boundary"),
    ]
    assert host.lifecycle_events == [
        "idle_continuation",
        "clear_session_activity",
    ]


@pytest.mark.asyncio
async def test_shutdown_after_completed_run_hands_over_durable_idle_boundary() -> None:
    """Shutdown after completion leaves the durable boundary for another owner."""
    host = _Host()
    host.shutdown_before_message_returns = True
    runner = _start_session_runner(host)
    message = _wake_up()

    runner.enqueue(message)
    await asyncio.wait_for(runner.terminated_event.wait(), timeout=1)

    assert host.pending_idle_continuation_run_id == "run-001"
    assert host.idle_continuation_calls == []
    assert host.released_session_ids == ["session-001"]
    assert host.handover_messages == [message]


@pytest.mark.asyncio
async def test_recovered_no_actionable_wake_up_consumes_durable_idle_boundary() -> None:
    """A new owner resolves hooks and consumes the completed durable boundary."""
    host = _Host()
    host.pending_idle_continuation_run_id = "run-001"
    host.no_actionable_message_numbers.add(1)
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await _wait_until(lambda: bool(host.idle_continuation_calls))
    finally:
        await runner.shutdown()

    assert host.idle_continuation_resolution_run_ids == ["run-001"]
    assert host.idle_continuation_calls == [(message, [])]
    assert host.pending_idle_continuation_run_id is None
    assert host.idle_session_ids == ["session-001"]


@pytest.mark.asyncio
async def test_failed_terminal_run_marks_idle_without_goal_continuation() -> None:
    """Failed terminal runs become idle but do not enqueue Goal continuation."""
    host = _Host()

    async def failed_run(
        message: SessionWakeUp,
        *,
        poll_fn: PollMessages | None,
        check_stop: CheckStop | None,
        prepare_toolkits: PrepareToolkits | None,
    ) -> RunExecutionResult:
        del poll_fn, check_stop, prepare_toolkits
        host.processed_messages.append(message)
        host.message_started.set()
        return RunExecutionResult(
            toolkits=[],
            terminal_event_observed=True,
            no_actionable_work=False,
            run_id="run-001",
            terminal_run_status=AgentRunStatus.FAILED,
        )

    host.process_message = failed_run
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await _wait_until(lambda: bool(host.idle_session_ids))
    finally:
        await runner.shutdown()

    assert host.idle_session_ids == ["session-001"]
    assert host.idle_continuation_calls == []
    assert host.lifecycle_events == [
        "mark_session_idle",
        "clear_session_activity",
    ]


@pytest.mark.asyncio
async def test_no_actionable_wake_up_marks_session_idle_without_continuation() -> None:
    """No-actionable wake-ups clear RUNNING state without idle continuation."""
    host = _Host()
    host.no_actionable_message_numbers.add(1)
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await _wait_until(lambda: bool(host.idle_session_ids))
    finally:
        await runner.shutdown()

    assert host.processed_messages == [message]
    assert host.idle_session_ids == ["session-001"]
    assert host.idle_continuation_calls == []
    assert host.lifecycle_events == [
        "mark_session_idle",
        "clear_session_activity",
    ]


@pytest.mark.asyncio
async def test_noop_wake_up_after_terminal_run_finishes_delayed_idle() -> None:
    """Stale wake-ups finish delayed idle continuation after terminal runs."""
    host = _Host()
    host.no_actionable_message_numbers.add(2)
    runner = _start_session_runner(host)
    first = _wake_up(user_id="user-001")
    stale = _wake_up(user_id="user-002")

    try:
        runner.enqueue(first)
        runner.enqueue(stale)
        await _wait_until(lambda: len(host.processed_messages) == 2)
        await _wait_until(lambda: bool(host.idle_continuation_calls))
    finally:
        await runner.shutdown()

    assert host.processed_messages == [first, stale]
    assert host.owner_generation_claims == 1
    assert host.idle_session_ids == ["session-001"]
    assert host.idle_continuation_calls == [(stale, [])]
    assert host.lifecycle_events == [
        "idle_continuation",
        "clear_session_activity",
    ]


@pytest.mark.asyncio
async def test_session_runner_carries_idle_baseline_across_explicit_transitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completed messages reset idle time while heartbeats preserve the baseline."""
    host = _Host()
    runner = _make_session_runner(host)
    first = _wake_up(user_id="user-001")
    follow_up = _wake_up(user_id="user-002")
    waiter = _ScriptedSessionRunnerWaiter(
        [
            MessageResult(first),
            HeartbeatResult(),
            MessageResult(follow_up),
            ShutdownResult(),
        ]
    )
    runner.waiter = cast(SessionRunnerWaiter, waiter)
    now = 0.0
    completion_times = iter([1801.0, 5402.0])

    async def process_message(
        message: SessionWakeUp,
        *,
        poll_fn: PollMessages | None,
        check_stop: CheckStop | None,
        prepare_toolkits: PrepareToolkits | None,
    ) -> RunExecutionResult:
        del poll_fn, check_stop, prepare_toolkits
        nonlocal now
        host.processed_messages.append(message)
        now = next(completion_times)
        return RunExecutionResult(
            toolkits=[],
            terminal_event_observed=False,
            no_actionable_work=False,
        )

    monkeypatch.setattr(host, "process_message", process_message)
    monkeypatch.setattr(
        runner,
        "_monotonic_time",
        lambda: now,
    )

    await runner.run()

    assert host.processed_messages == [first, follow_up]
    assert waiter.idle_started_at == [0.0, 1801.0, 1801.0, 5402.0]
    assert host.owner_heartbeat_session_ids == ["session-001"]
    assert host.released_session_ids == ["session-001"]


@pytest.mark.asyncio
async def test_session_runner_idle_timeout_releases_lock_once() -> None:
    """Idle timeout exits the runner and releases its owner lock once."""
    host = _Host()
    runner = _make_session_runner(host)
    waiter = _ScriptedSessionRunnerWaiter(
        [MessageResult(_wake_up()), IdleTimeoutResult()]
    )
    runner.waiter = cast(SessionRunnerWaiter, waiter)

    await runner.run()

    assert host.released_session_ids == ["session-001"]


@pytest.mark.asyncio
async def test_session_runner_graceful_shutdown_releases_lock_once() -> None:
    """Explicit graceful shutdown releases the current owner lock once."""
    host = _Host()
    runner = _start_session_runner(host)
    runner.enqueue(_wake_up())
    await host.idle_mark_attempted.wait()

    await runner.shutdown()

    assert host.released_session_ids == ["session-001"]


@pytest.mark.asyncio
async def test_session_runner_renews_owner_heartbeat_while_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Idle runner preserves sticky ownership and refreshes owner heartbeat."""
    monkeypatch.setattr(
        session_runner_waiter_module,
        "_OWNER_HEARTBEAT_INTERVAL",
        0.01,
    )
    monkeypatch.setattr(session_runner_waiter_module, "_IDLE_TIMEOUT", 1.0)
    host = _Host()
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(_wait_for_owner_heartbeat(host), timeout=1)
        assert host.owner_heartbeat_session_ids == ["session-001"]
        assert host.heartbeat_session_ids == []
        assert host.released_session_ids == []
    finally:
        await runner.shutdown()

    assert host.released_session_ids == ["session-001"]


@pytest.mark.asyncio
async def test_session_command_runs_without_event_adapter() -> None:
    """Handle command-only input without separate adapter."""
    host = _Host()
    host.pending_command_result = True
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(host.command_processed.wait(), timeout=1)
    finally:
        await runner.shutdown()

    assert host.cleared_session_ids == ["session-001"]
    assert host.idle_session_ids == ["session-001"]
    assert host.idle_continuation_calls == [(message, [])]
    assert host.lifecycle_events == [
        "idle_continuation",
        "clear_session_activity",
    ]
    assert host.released_session_ids == ["session-001"]


@pytest.mark.asyncio
async def test_session_command_reports_user_visible_error() -> None:
    """Command user-visible error is not overwritten by generic message."""
    host = _Host()
    host.pending_command_result = True
    host.command_error = UserVisibleRuntimeError(
        "Compaction failed: summary model returned no text."
    )
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(host.event_dispatched.wait(), timeout=1)
    finally:
        await runner.shutdown()

    assert len(host.dispatched_events) == 1
    session_id, event = host.dispatched_events[0]
    assert session_id == "session-001"
    assert isinstance(event, Event)
    assert event.kind == EventKind.SYSTEM_ERROR
    assert isinstance(event.payload, SystemErrorPayload)
    assert event.payload.content == "Compaction failed: summary model returned no text."


@pytest.mark.asyncio
async def test_session_command_reports_compaction_error_as_internal_error() -> None:
    """Compaction failure is internal error exposing only generic message."""
    host = _Host()
    host.pending_command_result = True
    host.command_error = CompactionFailedError(
        "Compaction failed: summary model returned no text."
    )
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(host.event_dispatched.wait(), timeout=1)
    finally:
        await runner.shutdown()

    assert len(host.dispatched_events) == 1
    session_id, event = host.dispatched_events[0]
    assert session_id == "session-001"
    assert isinstance(event, Event)
    assert event.kind == EventKind.SYSTEM_ERROR
    assert isinstance(event.payload, SystemErrorPayload)
    assert event.payload.content == "An internal error occurred."


def test_apply_active_tool_call_event_tracks_until_output() -> None:
    """tool call activity is maintained only from call start until output arrives."""
    native_artifact = NativeArtifact(
        compat_key="test:responses:test:gpt-test:1",
        adapter="test",
        native_format="responses",
        provider="test",
        model="gpt-test",
        schema_version="1",
        item={},
    )
    tool_call = Event(
        id="0123456789abcdef0123456789abcdef",
        session_id="session-1",
        kind=EventKind.CLIENT_TOOL_CALL,
        payload=ClientToolCallPayload(
            call_id="call-1",
            name="shell",
            arguments='{"cmd":"pwd"}',
            native_artifact=native_artifact,
            wire_dialect="json_function",
        ),
        created_at=datetime.now(timezone.utc),
    )
    output = Event(
        id="1123456789abcdef0123456789abcdef",
        session_id="session-1",
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload=ClientToolResultPayload(
            call_id="call-1",
            status="completed",
            output="/tmp",
            wire_dialect="json_function",
        ),
        created_at=datetime.now(timezone.utc),
    )

    active = apply_active_tool_call_event([], tool_call, owner_generation=1)
    assert len(active) == 1
    assert active[0].call_id == "call-1"
    assert active[0].name == "shell"
    assert active[0].arguments == '{"cmd":"pwd"}'

    active = apply_active_tool_call_event(active, output, owner_generation=1)
    assert active == []


@pytest.mark.asyncio
async def test_replace_live_active_tool_calls_broadcasts_without_redis() -> None:
    """Running tool calls broadcast without entering the Redis live store."""
    live_store = _LiveEventStore(before=[], after=[])
    broadcast = _Broadcast()
    projector = LiveEventProjector(
        live_event_store=cast(Any, live_store),
        broadcast=cast(WebSocketBroadcast, broadcast),
        session_manager=cast(Any, _SessionManager()),
        agent_run_repository=cast(Any, object()),
    )
    active_tool_call = ActiveToolCall(
        call_id="call-1",
        name="bash",
        arguments='{"command":"sleep 60"}',
        started_at=datetime.now(timezone.utc),
        owner_generation=1,
        wire_dialect="json_function",
    )

    await projector.replace_active_tool_calls(
        "session-1",
        [active_tool_call],
        removed_call_ids=set(),
    )

    assert live_store.removed_events == []
    assert len(broadcast.events) == 1
    assert broadcast.events[0][1]["type"] == "live_event_upserted"


@pytest.mark.asyncio
async def test_dispatch_event_publishes_history_before_live_removal() -> None:
    """Event broadcasts live removal after history append."""
    broadcast = _Broadcast()
    broker = _Broker()
    live_event = Event(
        id="0123456789abcdef0123456789abcdea",
        session_id="session-1",
        kind=EventKind.CLIENT_TOOL_CALL,
        payload=ClientToolCallPayload(
            call_id="call-1",
            name="shell",
            arguments='{"cmd":"pwd"}',
            native_artifact=NativeArtifact(
                compat_key="azents-live:live_projection:azents:live:1",
                adapter="azents-live",
                native_format="live_projection",
                provider="azents",
                model="live",
                schema_version="1",
                item={"live_projection": "client_tool_call"},
            ),
            wire_dialect="json_function",
        ),
        created_at=datetime.now(timezone.utc),
    )
    live_store = _LiveEventStore(before=[live_event], after=[])
    event_publisher = _make_worker_event_publisher(
        live_store,
        broadcast=broadcast,
        broker=broker,
    )
    durable_result = Event(
        id="1123456789abcdef0123456789abcdeb",
        session_id="session-1",
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload=ClientToolResultPayload(
            call_id="call-1",
            status="completed",
            output="done",
            wire_dialect="json_function",
        ),
        created_at=datetime.now(timezone.utc),
    )

    await event_publisher.dispatch_event("session-1", durable_result)

    event_types = [
        event.get("kind") or event.get("type") for _, event in broadcast.events
    ]
    assert event_types == [
        "history_event_appended",
        "live_event_removed",
    ]
    appended = cast(dict[str, object], broadcast.events[0][1]["event"])
    assert appended["id"] == "1123456789abcdef0123456789abcdeb"
    assert broadcast.events[1][1]["event_id"] == "0123456789abcdef0123456789abcdea"
    assert broker.renewed_session_ids == ["session-1"]


@pytest.mark.asyncio
async def test_boundary_poll_broadcasts_input_buffer_taxonomy_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """InputBuffer flush broadcasts history append and live removal actions."""
    broadcast = _Broadcast()
    executor = object.__new__(RunExecutor)
    executor.broadcast = cast(WebSocketBroadcast, broadcast)
    scheduled_title_events: list[str] = []

    def schedule_title(session_id: str, event: Event) -> None:
        scheduled_title_events.append(f"{session_id}:{event.id}")

    monkeypatch.setattr(
        executor,
        "_schedule_initial_prompt_title_generation",
        schedule_title,
    )
    user_message = make_run_user_message(
        sender_user_id=None,
        content="buffered input",
        metadata={"source": "chat"},
        attachments=[],
        external_id="buffer-1",
        attachment_source="input_buffer",
        requested_inference_profile=None,
    )
    event = Event(
        id="1123456789abcdef0123456789abcdeb",
        session_id="session-1",
        kind=EventKind.USER_MESSAGE,
        payload=user_message.payload,
        external_id="buffer-1",
        created_at=datetime.now(timezone.utc),
    )
    promotion = _InputBufferService(
        PromotedInputBuffers(
            worktree_action=None,
            turn_effect=TurnEffect.ELIGIBLE,
            requested_inference_profile=RequestedInferenceProfile(
                model_target_label="default",
                reasoning_effort=None,
            ),
            promoted_event_ids=[],
            user_messages=[user_message],
            events=[event],
            deleted_buffer_ids=["buffer-1"],
            changed_session_agent_ids=[],
            claimed_count=1,
            inserted_count=1,
            deduped_count=0,
        )
    )
    executor.input_buffer_service = cast(
        InputBufferService,
        promotion,
    )

    async def has_actionable_model_input(session_id: str) -> bool:
        del session_id
        return False

    monkeypatch.setattr(
        executor,
        "_has_actionable_model_input",
        has_actionable_model_input,
    )

    async def process_operation_actions(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return OperationActionProcessResult(context_invalidated=False)

    monkeypatch.setattr(
        executor,
        "_process_operation_actions",
        process_operation_actions,
    )

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id, event

    poll = executor.make_boundary_poll(
        message=_wake_up(session_id="session-1", agent_id="agent-1"),
        model="gpt-test",
        requested_inference_profile=RequestedInferenceProfile(
            model_target_label="default",
            reasoning_effort=None,
        ),
        run_id="run-001",
        poll_fn=None,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        mark_context_invalidated=lambda: None,
        dispatch_event=dispatch_event,
    )

    poll_result = await poll()

    assert poll_result.user_messages == [user_message]
    assert poll_result.context_invalidated is False
    assert promotion.calls == [
        ("session-1", "gpt-test"),
        ("session-1", "gpt-test"),
    ]
    assert scheduled_title_events == ["session-1:1123456789abcdef0123456789abcdeb"]
    event_types = [event.get("type") for _, event in broadcast.events]
    assert event_types == ["history_event_appended", "live_event_removed"]
    appended = cast(dict[str, object], broadcast.events[0][1]["event"])
    assert appended["id"] == "1123456789abcdef0123456789abcdeb"
    assert appended["external_id"] == "buffer-1"
    assert broadcast.events[1][1]["event_id"] == "buffer-1"


@pytest.mark.asyncio
async def test_dispatch_flushes_live_partial_batch_during_event_update() -> None:
    """Event update flushes pending content delta batch."""
    broadcast = _Broadcast()
    broker = _Broker()
    live_store = _LiveEventStore(before=[], after=[])
    event_publisher = _make_worker_event_publisher(
        live_store,
        broadcast=broadcast,
        broker=broker,
    )
    durable_result = Event(
        id="1123456789abcdef0123456789abcdeb",
        session_id="session-1",
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload=ClientToolResultPayload(
            call_id="call-1",
            status="completed",
            output="done",
            wire_dialect="json_function",
        ),
        created_at=datetime.now(timezone.utc),
    )

    await event_publisher.dispatch_event(
        "session-1",
        ContentDelta(delta="hel", content_index=0),
    )
    await event_publisher.dispatch_event(
        "session-1",
        ContentDelta(delta="lo", content_index=0),
    )
    await event_publisher.dispatch_event("session-1", durable_result)

    assert live_store.assistant_deltas == [("session-1", "hello", 0)]
    event_types = [
        event.get("kind") or event.get("type") for _, event in broadcast.events
    ]
    assert event_types == [
        "live_event_upserted",
        "history_event_appended",
    ]


@pytest.mark.asyncio
async def test_dispatch_flushes_reasoning_batch_during_event_update() -> None:
    """Event update flushes pending reasoning delta batch."""
    broadcast = _Broadcast()
    broker = _Broker()
    live_store = _LiveEventStore(before=[], after=[])
    event_publisher = _make_worker_event_publisher(
        live_store,
        broadcast=broadcast,
        broker=broker,
    )
    durable_reasoning = Event(
        id="1123456789abcdef0123456789abcdeb",
        session_id="session-1",
        kind=EventKind.REASONING,
        payload=ReasoningPayload(
            text="thinking",
            summary=None,
            native_artifact=NativeArtifact(
                compat_key="test:responses:test:gpt-test:1",
                adapter="test",
                native_format="responses",
                provider="test",
                model="gpt-test",
                schema_version="1",
                item={},
            ),
        ),
        created_at=datetime.now(timezone.utc),
    )

    await event_publisher.dispatch_event(
        "session-1",
        ReasoningDelta(
            delta="think",
            item_id="rs_1",
            output_index=0,
            summary_index=0,
        ),
    )
    await event_publisher.dispatch_event(
        "session-1",
        ReasoningDelta(
            delta="ing",
            item_id="rs_1",
            output_index=0,
            summary_index=0,
        ),
    )
    await event_publisher.dispatch_event("session-1", durable_reasoning)

    assert live_store.reasoning_deltas == [("session-1", "thinking", "rs_1", 0, 0)]
    event_types = [
        event.get("kind") or event.get("type") for _, event in broadcast.events
    ]
    assert event_types == [
        "live_event_upserted",
        "history_event_appended",
    ]


@pytest.mark.asyncio
async def test_prepare_toolkits_enters_before_update_context() -> None:
    """session toolkit preparation calls ``__aenter__`` before update_context."""
    host = _Host()
    runner = _make_session_runner(host)
    events: list[str] = []
    toolkit = _TrackingToolkit(events, "dummy")

    try:
        prepared = await runner.prepare_toolkits(
            [
                ToolkitBinding(
                    toolkit=toolkit,
                    slug="dummy",
                    use_prefix=False,
                    toolkit_type=None,
                )
            ],
            "user-001",
        )
        await prepared[0].toolkit.update_context(
            TurnContext(
                user_id="user-001",
                workspace_id="workspace-001",
                model="test-model",
                run_id="run-001",
                publish_event=_noop_publish_event,
            )
        )
    finally:
        await runner.shutdown()

    assert events == ["enter:dummy", "update:dummy", "exit:dummy"]


@pytest.mark.asyncio
async def test_prepare_toolkits_reuses_same_session_key() -> None:
    """Same session key reuses existing entered toolkit in next run."""
    host = _Host()
    runner = _make_session_runner(host)
    events: list[str] = []
    first = _TrackingToolkit(events, "first")
    second = _TrackingToolkit(events, "second")

    try:
        first_prepared = await runner.prepare_toolkits(
            [
                ToolkitBinding(
                    toolkit=first,
                    slug="same",
                    use_prefix=False,
                    toolkit_type="mcp",
                )
            ],
            "user-001",
        )
        second_prepared = await runner.prepare_toolkits(
            [
                ToolkitBinding(
                    toolkit=second,
                    slug="same",
                    use_prefix=True,
                    toolkit_type="mcp",
                )
            ],
            "user-001",
        )
    finally:
        await runner.shutdown()

    assert first_prepared[0].toolkit is first
    assert second_prepared[0].toolkit is first
    assert second_prepared[0].use_prefix is True
    assert events == ["enter:first", "exit:first"]


@pytest.mark.asyncio
async def test_prepare_toolkits_replaces_auto_toolkit_on_context_change() -> None:
    """Context-derived revision replaces a handover-era auto Toolkit instance."""
    host = _Host()
    runner = _make_session_runner(host)
    events: list[str] = []
    stale = _TrackingToolkit(events, "stale")
    current = _TrackingToolkit(events, "current")

    try:
        first_prepared = await runner.prepare_toolkits(
            [
                ToolkitBinding(
                    toolkit=stale,
                    slug="skill",
                    use_prefix=False,
                    toolkit_type=None,
                    source_revision="idle-workspace",
                )
            ],
            "user-001",
        )
        second_prepared = await runner.prepare_toolkits(
            [
                ToolkitBinding(
                    toolkit=current,
                    slug="skill",
                    use_prefix=False,
                    toolkit_type=None,
                    source_revision="run-workspace",
                )
            ],
            "user-001",
        )
    finally:
        await runner.shutdown()

    assert first_prepared[0].toolkit is stale
    assert second_prepared[0].toolkit is current
    assert events == [
        "enter:stale",
        "enter:current",
        "exit:stale",
        "exit:current",
    ]


@pytest.mark.asyncio
async def test_prepare_toolkits_rekeys_registered_toolkit_by_actor() -> None:
    """DB-registered toolkit does not reuse previous instance when actor changes."""
    host = _Host()
    runner = _make_session_runner(host)
    events: list[str] = []
    first = _TrackingToolkit(events, "first-user")
    second = _TrackingToolkit(events, "second-user")

    try:
        first_prepared = await runner.prepare_toolkits(
            [
                ToolkitBinding(
                    toolkit=first,
                    slug="github",
                    use_prefix=True,
                    toolkit_type="github",
                )
            ],
            "user-001",
        )
        second_prepared = await runner.prepare_toolkits(
            [
                ToolkitBinding(
                    toolkit=second,
                    slug="github",
                    use_prefix=True,
                    toolkit_type="github",
                )
            ],
            "user-002",
        )
    finally:
        await runner.shutdown()

    assert first_prepared[0].toolkit is first
    assert second_prepared[0].toolkit is second
    assert events == [
        "enter:first-user",
        "enter:second-user",
        "exit:first-user",
        "exit:second-user",
    ]


@pytest.mark.asyncio
async def test_stop_restarts_turn_when_pending_buffer_remains() -> None:
    """If pending buffer remains after Stop, start next turn with wake-up."""
    host = _Host()
    host.stop_first_message = True
    host.pending_input_session_ids.add("session-001")
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(host.message_started.wait(), timeout=1)
        runner.enqueue(SessionStopSignal(session_id="session-001", user_id="user-001"))
        while len(host.processed_messages) < 2:
            await asyncio.sleep(0)
    finally:
        await runner.shutdown()

    assert host.processed_messages == [message, message]


@pytest.mark.asyncio
async def test_stop_does_not_duplicate_existing_resume_wake_up() -> None:
    """Do not create duplicate wake-up after stop when wake-up is already queued."""
    host = _Host()
    host.stop_first_message = True
    host.pending_input_session_ids.add("session-001")
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(host.message_started.wait(), timeout=1)
        runner.enqueue(message)
        runner.enqueue(SessionStopSignal(session_id="session-001", user_id="user-001"))
        while len(host.processed_messages) < 2:
            await asyncio.sleep(0)
        await asyncio.sleep(0)
    finally:
        await runner.shutdown()

    assert host.processed_messages == [message, message]


@pytest.mark.asyncio
async def test_stop_discards_existing_wake_up_when_no_pending_buffer() -> None:
    """If no pending buffer remains after Stop, queued wake-up is not resumed."""
    host = _Host()
    host.stop_first_message = True
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(host.message_started.wait(), timeout=1)
        runner.enqueue(message)
        runner.enqueue(SessionStopSignal(session_id="session-001", user_id="user-001"))
        await asyncio.wait_for(
            _wait_until(lambda: host.idle_session_ids == ["session-001"]),
            timeout=2,
        )
        await asyncio.sleep(0)
    finally:
        await runner.shutdown()

    assert host.processed_messages == [message]


@pytest.mark.asyncio
async def test_session_stop_signal_cancels_blocked_engine_task() -> None:
    """SessionStopSignal cancels execution task without check_stop polling."""
    host = _Host()
    host.block_message_until_cancel = True
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(host.message_started.wait(), timeout=1)
        runner.enqueue(SessionStopSignal(session_id="session-001", user_id="user-001"))
        await asyncio.wait_for(host.message_cancelled.wait(), timeout=2)
    finally:
        await runner.shutdown()


@pytest.mark.asyncio
async def test_durable_stop_request_cancels_blocked_engine_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """durable stop intent cancels execution task even without Broker signal."""
    monkeypatch.setattr(
        session_runner_supervisor_module,
        "_EXPLICIT_STOP_POLL_INTERVAL",
        0.01,
    )
    host = _Host()
    host.block_message_until_cancel = True
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(host.message_started.wait(), timeout=1)
        host.stop_request_session_ids.add("session-001")
        await asyncio.wait_for(host.message_cancelled.wait(), timeout=2)
    finally:
        await runner.shutdown()


@pytest.mark.asyncio
async def test_user_stop_waits_for_engine_cleanup_before_session_boundary() -> None:
    """User stop keeps the Session boundary until cancellation cleanup finishes."""
    host = _Host()
    host.block_message_until_cancel = True
    host.block_after_cancel = True
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(host.message_started.wait(), timeout=1)
        runner.enqueue(SessionStopSignal(session_id="session-001", user_id="user-001"))
        await asyncio.wait_for(host.message_cancelled.wait(), timeout=2)
        await asyncio.wait_for(
            _wait_until(
                lambda: host.finalized_user_stop_session_ids == ["session-001"]
            ),
            timeout=2,
        )
        await asyncio.sleep(0)
        assert host.idle_session_ids == []
        assert host.released_session_ids == []

        host.cancel_cleanup_release.set()
        await asyncio.wait_for(
            _wait_until(lambda: host.idle_session_ids == ["session-001"]),
            timeout=2,
        )
    finally:
        host.cancel_cleanup_release.set()
        await runner.shutdown()


@pytest.mark.asyncio
async def test_runtime_shutdown_does_not_finalize_user_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime shutdown does not perform user stop finalization."""
    monkeypatch.setattr(session_runner_supervisor_module, "_SHUTDOWN_TIMEOUT", 0.05)
    host = _Host()
    host.block_message_until_cancel = True
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(host.message_started.wait(), timeout=1)
        host.shutdown_event.set()
        await asyncio.wait_for(host.message_cancelled.wait(), timeout=1)
    finally:
        await runner.shutdown()

    assert host.finalized_user_stop_session_ids == []
    assert host.idle_session_ids == []


@pytest.mark.asyncio
async def test_runtime_shutdown_hands_over_active_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime shutdown preserves active run state and re-enqueues wake-up."""
    monkeypatch.setattr(session_runner_supervisor_module, "_SHUTDOWN_TIMEOUT", 0.05)
    host = _Host()
    host.block_message_until_cancel = True
    host.running_agent_run_exists = True
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(host.message_started.wait(), timeout=1)
        host.shutdown_event.set()
        await asyncio.wait_for(host.message_cancelled.wait(), timeout=1)
        await asyncio.wait_for(
            _wait_until(lambda: host.handover_messages == [message]),
            timeout=1,
        )
    finally:
        await runner.shutdown()

    assert host.finalized_user_stop_session_ids == []
    assert host.idle_session_ids == []
    assert host.cleared_session_ids == []
    assert host.released_session_ids == ["session-001"]
    assert host.handover_messages == [message]


@pytest.mark.asyncio
async def test_runner_shutdown_does_not_mark_active_run_idle() -> None:
    """A runner-local shutdown must leave unterminated active runs RUNNING."""
    host = _Host()
    host.block_message_until_release = True
    host.terminal_event_observed = False
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(
            host.message_started.wait(),
            timeout=1,
        )
        runner.request_shutdown()
        host.message_release.set()
        await asyncio.wait_for(
            _wait_until(lambda: runner.terminated),
            timeout=1,
        )
    finally:
        await runner.shutdown()

    assert host.processed_messages == [message]
    assert host.idle_session_ids == []
    assert host.released_session_ids == ["session-001"]


@pytest.mark.asyncio
async def test_runner_keeps_activity_when_idle_transition_is_rejected() -> None:
    """Running AgentRun blocks idle transition and preserves recovery activity."""
    host = _Host()
    host.idle_transition_allowed = False
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(host.message_started.wait(), timeout=1)
        await asyncio.wait_for(host.idle_mark_attempted.wait(), timeout=1)

        assert host.idle_session_ids == []
        assert host.cleared_session_ids == []
    finally:
        await runner.shutdown()


@pytest.mark.asyncio
async def test_shutdown_waits_before_canceling_blocked_engine_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker shutdown, unlike explicit stop, waits gracefully until timeout."""
    monkeypatch.setattr(session_runner_supervisor_module, "_SHUTDOWN_TIMEOUT", 0.2)
    host = _Host()
    host.block_message_until_cancel = True
    runner = _start_session_runner(host)
    message = _wake_up()

    try:
        runner.enqueue(message)
        await asyncio.wait_for(host.message_started.wait(), timeout=1)
        host.shutdown_event.set()
        await asyncio.sleep(0.05)
        assert not host.message_cancelled.is_set()
        await asyncio.wait_for(host.message_cancelled.wait(), timeout=1)
    finally:
        await runner.shutdown()
