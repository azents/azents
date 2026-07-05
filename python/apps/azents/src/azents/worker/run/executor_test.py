"""RunExecutor tests."""

import asyncio
import contextlib
import datetime
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Any, cast

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

import azents.worker.run.executor as run_executor_module
from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.types import PublishedEvent, SessionBroker, SessionWakeUp
from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.core.tools import ToolkitProvider
from azents.engine.events.engine_events import RunComplete, RunPhaseChanged
from azents.engine.events.types import (
    Event,
    RunMarkerPayload,
    SystemErrorPayload,
    UserMessagePayload,
)
from azents.engine.run.background import BackgroundTaskRegistry
from azents.engine.run.commands import CommandHandler
from azents.engine.run.contracts import AgentEngineProtocol, RunContext, RunRequest
from azents.engine.run.emit import Emit, ephemeral
from azents.engine.run.errors import ModelCallError, UserVisibleRuntimeError
from azents.engine.run.failure import FailedRunRetryState
from azents.engine.run.input import AgentNotFound
from azents.engine.tools.builtin import BuiltinToolkitProvider
from azents.engine.tools.claude_rules import ClaudeRulesToolkitProvider
from azents.engine.tools.goal import GoalToolkitProvider
from azents.engine.tools.skill import SkillToolkitProvider
from azents.engine.tools.todo import TodoToolkitProvider
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import PendingSessionCommand
from azents.repos.agent_subagent import AgentSubagentRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.toolkit import AgentToolkitRepository, ToolkitRepository
from azents.services.chat.data import ChatLiveRunState
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import InputBufferService
from azents.services.model_file import ModelFileService
from azents.services.session_git_worktree import SessionGitWorktreeService
from azents.services.session_title import SessionTitleService
from azents.worker.config import AgentWorkerConfig
from azents.worker.live.event_projector import LiveEventProjector
from azents.worker.run.executor import (
    RunExecutor,
    RunInputPollResult,
    has_actionable_tail,
)
from azents.worker.run.finalizer import FailedRunFinalizationInput
from azents.worker.run.results import RunExecutionResult
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.user_stop_finalizer import UserStopFinalizer


class _SessionScope(AbstractAsyncContextManager[AsyncSession]):
    """DB session scope test double."""

    async def __aenter__(self) -> AsyncSession:
        """Return a dummy DB session."""
        return cast(AsyncSession, object())

    async def __aexit__(self, *exc_info: object) -> None:
        """No resources to clean up."""


class _SessionManager:
    """SessionManager test double."""

    def __call__(self) -> _SessionScope:
        """Return a new session scope."""
        return _SessionScope()


class _SessionLifecycle:
    """SessionLifecycleService test double."""

    def __init__(self, order: list[str] | None = None) -> None:
        self.order = order
        self.heartbeat_session_ids: list[str] = []
        self.retry_states: list[FailedRunRetryState | None] = []
        self.activities: list[tuple[str, str, object]] = []
        self.cleared_session_ids: list[str] = []
        self.terminal_runs: list[tuple[str, AgentRunStatus]] = []
        self.idle_session_ids: list[str] = []
        self.wake_ups: list[SessionWakeUp] = []

    async def set_session_activity(
        self,
        session_id: str,
        *,
        run_id: str,
        phase: object,
        active_tool_calls: object = None,
    ) -> None:
        """Record session activity updates."""
        del active_tool_calls
        self.activities.append((session_id, run_id, phase))

    async def clear_session_activity(self, session_id: str) -> None:
        """Record session activity cleanup."""
        self.cleared_session_ids.append(session_id)
        if self.order is not None:
            self.order.append("clear_session_activity")

    async def mark_session_idle(self, session_id: str) -> bool:
        """Record session idle transitions."""
        self.idle_session_ids.append(session_id)
        return True

    async def send_session_wake_up(self, message: SessionWakeUp) -> None:
        """Record follow-up wake-ups."""
        self.wake_ups.append(message)

    async def mark_agent_run_terminal_if_running(
        self,
        session_id: str,
        *,
        run_id: str,
        status: object,
    ) -> None:
        """Record terminal run updates."""
        del session_id
        self.terminal_runs.append((run_id, cast(AgentRunStatus, status)))

    async def update_agent_run_retry_state(
        self,
        session_id: str,
        *,
        run_id: str,
        retry_state: FailedRunRetryState | None,
    ) -> None:
        """Record retry-state updates."""
        del session_id, run_id
        self.retry_states.append(retry_state)

    async def heartbeat_session(self, session_id: str) -> None:
        """Record the session id passed to heartbeat."""
        self.heartbeat_session_ids.append(session_id)


class _AgentRepository:
    """AgentRepository test double."""

    async def get_by_id(self, session: AsyncSession, agent_id: str) -> object | None:
        """Return no persisted agent settings."""
        del session, agent_id
        return None


class _AgentSessionRepository:
    """AgentSessionRepository test double."""

    def __init__(self) -> None:
        self.cleared_commands: list[tuple[str, str]] = []

    async def clear_pending_command(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        command_id: str,
    ) -> None:
        """Record pending command cleanup."""
        del session
        self.cleared_commands.append((session_id, command_id))

    async def claim_lifecycle_start(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        now: object,
    ) -> bool:
        """Pretend the session start hook was already claimed."""
        del session, session_id, now
        return False


class _SessionTitleService:
    """SessionTitleService test double."""

    async def generate_from_initial_prompt(
        self,
        session_id: str,
        event: Event,
    ) -> None:
        """Do not generate titles in executor tests."""
        del session_id, event


class _LiveEventProjector:
    """LiveEventProjector test double."""

    def __init__(self) -> None:
        self.flushed_session_ids: list[str] = []
        self.active_tool_calls: list[tuple[str, object]] = []
        self.live_run_updates: list[tuple[str, ChatLiveRunState]] = []
        self.live_run_cleared_session_ids: list[str] = []

    async def publish_live_run_updated(
        self,
        session_id: str,
        run: ChatLiveRunState,
    ) -> None:
        """Record live run update broadcasts."""
        self.live_run_updates.append((session_id, run))

    async def publish_live_run_cleared(self, session_id: str) -> None:
        """Record live run clear broadcasts."""
        self.live_run_cleared_session_ids.append(session_id)

    async def replace_active_tool_calls(
        self,
        session_id: str,
        active_tool_calls: object,
    ) -> None:
        """Record active tool call projection replacements."""
        self.active_tool_calls.append((session_id, active_tool_calls))

    async def flush_session(self, session_id: str) -> None:
        """Record flushed sessions."""
        self.flushed_session_ids.append(session_id)


class _Engine:
    """AgentEngineProtocol test double."""

    async def save_error_message(self, session_id: str, content: str) -> Event:
        """This test engine should not save errors."""
        del session_id, content
        raise AssertionError("save_error_message should not be called")

    def compact(self, request: RunRequest, context: object) -> AsyncIterator[Emit]:
        """Manual compaction is not used by these tests."""
        del request, context
        raise AssertionError("compact should not be called")

    def run(
        self,
        request: RunRequest,
        context: object,
        *,
        poll_messages: object = None,
        check_stop: object = None,
    ) -> AsyncIterator[Emit]:
        """Emit RunComplete immediately."""
        del request, context, poll_messages, check_stop

        async def iterator() -> AsyncIterator[Emit]:
            yield ephemeral(RunComplete())

        return iterator()


class _FlakyEngine(_Engine):
    """Engine that fails once and then completes."""

    def __init__(self) -> None:
        self.calls = 0

    def run(
        self,
        request: RunRequest,
        context: object,
        *,
        poll_messages: object = None,
        check_stop: object = None,
    ) -> AsyncIterator[Emit]:
        """Fail the first attempt and complete the second."""
        del request, context, poll_messages, check_stop

        async def iterator() -> AsyncIterator[Emit]:
            self.calls += 1
            if self.calls == 1:
                raise ModelCallError("model temporarily unavailable")
            yield ephemeral(RunComplete())

        return iterator()


class _InternalFlakyEngine(_Engine):
    """Engine that raises an internal error once and then completes."""

    def __init__(self) -> None:
        self.calls = 0

    def run(
        self,
        request: RunRequest,
        context: object,
        *,
        poll_messages: object = None,
        check_stop: object = None,
    ) -> AsyncIterator[Emit]:
        """Fail the first attempt with a generic exception and complete the second."""
        del request, context, poll_messages, check_stop

        async def iterator() -> AsyncIterator[Emit]:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("database temporarily unavailable")
            yield ephemeral(RunComplete())

        return iterator()


class _AlwaysFailingEngine(_Engine):
    """Engine that always raises a user-visible model error."""

    def __init__(self, message: str = "model still unavailable") -> None:
        self.calls = 0
        self.message = message

    def run(
        self,
        request: RunRequest,
        context: object,
        *,
        poll_messages: object = None,
        check_stop: object = None,
    ) -> AsyncIterator[Emit]:
        """Always fail the attempt."""
        del request, context, poll_messages, check_stop

        async def iterator() -> AsyncIterator[Emit]:
            self.calls += 1
            raise ModelCallError(self.message)
            yield  # pragma: no cover

        return iterator()


class _CommandHandler:
    """Command handler test double."""

    def __init__(self, emits: list[Emit]) -> None:
        self.emits = emits
        self.requests: list[RunRequest] = []
        self.contexts: list[RunContext] = []

    async def execute(
        self,
        engine: AgentEngineProtocol,
        request: RunRequest,
        context: RunContext,
    ) -> AsyncIterator[Emit]:
        """Record the command run and yield configured emits."""
        del engine
        self.requests.append(request)
        self.contexts.append(context)
        for item in self.emits:
            yield item


class _FailingCommandHandler:
    """Command handler that raises a user-visible failure."""

    async def execute(
        self,
        engine: AgentEngineProtocol,
        request: RunRequest,
        context: RunContext,
    ) -> AsyncIterator[Emit]:
        """Fail command execution."""
        del engine, request, context
        raise UserVisibleRuntimeError("command failed")
        yield  # pragma: no cover


class _FailedRunFinalizer:
    """Failed-run finalizer test double."""

    def __init__(self) -> None:
        self.inputs: list[FailedRunFinalizationInput] = []

    async def finalize(
        self,
        input: FailedRunFinalizationInput,
        *,
        dispatch_event: object,
    ) -> object:
        """Record finalization input."""
        del dispatch_event
        self.inputs.append(input)
        return object()


def _executor(
    session_lifecycle: _SessionLifecycle | None = None,
    *,
    engine: AgentEngineProtocol | None = None,
    failed_run_finalizer: object | None = None,
    command_registry: dict[str, CommandHandler] | None = None,
    agent_session_repository: _AgentSessionRepository | None = None,
    live_event_projector: _LiveEventProjector | None = None,
    failed_run_max_retries: int = 10,
) -> RunExecutor:
    """Create a RunExecutor for resolve-failure tests."""
    if session_lifecycle is None:
        session_lifecycle = _SessionLifecycle()
    if engine is None:
        engine = cast(AgentEngineProtocol, _Engine())
    if failed_run_finalizer is None:
        failed_run_finalizer = _FailedRunFinalizer()
    if command_registry is None:
        command_registry = {}
    if agent_session_repository is None:
        agent_session_repository = _AgentSessionRepository()
    if live_event_projector is None:
        live_event_projector = _LiveEventProjector()
    return RunExecutor(
        broker=cast(SessionBroker, object()),
        session_manager=cast(SessionManager[AsyncSession], _SessionManager()),
        engine=engine,
        agent_repository=cast(AgentRepository, _AgentRepository()),
        command_registry=command_registry,
        integration_repository=cast(LLMProviderIntegrationRepository, object()),
        toolkit_registry=cast(dict[str, ToolkitProvider[Any]], {}),
        agent_toolkit_repository=cast(AgentToolkitRepository, object()),
        toolkit_repository=cast(ToolkitRepository, object()),
        agent_subagent_repository=cast(AgentSubagentRepository, object()),
        agent_runtime_repository=cast(AgentRuntimeRepository, object()),
        agent_session_repository=cast(
            AgentSessionRepository,
            agent_session_repository,
        ),
        event_transcript_repository=cast(Any, object()),
        session_lifecycle=cast(SessionLifecycleService, session_lifecycle),
        worker_config=AgentWorkerConfig(
            web_url="http://localhost:3000",
            oauth_secret_key="test-secret",
            mcp_proxy_url=None,
            failed_run_max_retries=failed_run_max_retries,
            failed_run_base_backoff_seconds=1,
            failed_run_backoff_multiplier=2,
            failed_run_max_backoff_seconds=60,
        ),
        exchange_file_service=cast(ExchangeFileService, object()),
        model_file_service=cast(ModelFileService, object()),
        input_buffer_service=cast(InputBufferService, object()),
        session_git_worktree_service=cast(SessionGitWorktreeService, object()),
        session_title_service=cast(SessionTitleService, _SessionTitleService()),
        live_event_projector=cast(LiveEventProjector, live_event_projector),
        user_stop_finalizer=cast(UserStopFinalizer, object()),
        failed_run_finalizer=cast(Any, failed_run_finalizer),
        background_registry=cast(BackgroundTaskRegistry, object()),
        builtin_toolkit_provider=cast(BuiltinToolkitProvider, object()),
        claude_rules_toolkit_provider=cast(ClaudeRulesToolkitProvider, object()),
        todo_toolkit_provider=cast(TodoToolkitProvider, object()),
        goal_toolkit_provider=cast(GoalToolkitProvider, object()),
        skill_toolkit_provider=cast(SkillToolkitProvider, object()),
        broadcast=cast(WebSocketBroadcast, object()),
    )


def _message() -> SessionWakeUp:
    """Create a standard session wake-up for executor tests."""
    return SessionWakeUp(
        agent_id="agent-001",
        session_id="session-001",
        user_id="user-001",
        additional_system_prompt=None,
        interface=None,
        workspace_id="workspace-001",
        workspace_handle=None,
    )


def _pending_command(name: str = "compact") -> PendingSessionCommand:
    """Create a pending command for executor tests."""
    return PendingSessionCommand(
        id="command-001",
        name=name,
        payload={},
        user_id="user-001",
        created_at=datetime.datetime.now(datetime.UTC),
    )


async def _resolve_success(*args: object, **kwargs: object) -> object:
    """Return a minimal run request from resolve input."""
    del args, kwargs
    return Success(
        RunRequest(
            session_id="session-001",
            user_messages=[],
            agent_prompt=None,
            toolkits=[],
            model="gpt-test",
            credential_kwargs={},
            workspace_id="workspace-001",
            agent_id="agent-001",
        )
    )


async def _resolve_no_tools(*args: object, **kwargs: object) -> list[object]:
    """Return no dynamic tools."""
    del args, kwargs
    return []


def _patch_successful_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch RunExecutor dependencies to resolve a basic run request."""
    monkeypatch.setattr(run_executor_module, "resolve_invoke_input", _resolve_success)
    monkeypatch.setattr(run_executor_module, "resolve_agent_tools", _resolve_no_tools)
    monkeypatch.setattr(
        run_executor_module, "resolve_subagent_tools", _resolve_no_tools
    )


@pytest.mark.asyncio
async def test_execute_reports_resolve_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve failures end with a system error and RunComplete."""
    dispatched: list[PublishedEvent] = []
    executor = _executor()

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(user_messages=[], has_actionable_work=True)

    async def resolve_failure(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return Failure(AgentNotFound(agent_id="agent-001"))

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input",
        resolve_failure,
    )

    async def dispatch_event(
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        del session_id
        dispatched.append(event)

    result = await executor.execute(
        SessionWakeUp(
            agent_id="agent-001",
            session_id="session-001",
            user_id=None,
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-001",
            workspace_handle=None,
        ),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=cast(asyncio.Event, object()),
        dispatch_event=dispatch_event,
    )

    assert len(dispatched) == 2
    assert result.toolkits == []
    assert result.terminal_event_observed is True
    assert result.run_id is not None
    assert result.terminal_run_status == AgentRunStatus.FAILED
    error_event = dispatched[0]
    assert isinstance(error_event, Event)
    assert error_event.kind == EventKind.SYSTEM_ERROR
    assert isinstance(error_event.payload, SystemErrorPayload)
    assert error_event.payload.content == "AgentNotFound(agent_id='agent-001')"
    assert isinstance(dispatched[1], RunComplete)


@pytest.mark.asyncio
async def test_execute_enqueues_follow_up_after_context_invalidating_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Project-mutating actions stop before model dispatch and wake fresh context."""
    lifecycle = _SessionLifecycle()
    executor = _executor(session_lifecycle=lifecycle)
    message = _message()

    class PendingInputBufferService:
        """InputBufferService double with pending follow-up work."""

        async def has_pending_session_input_buffers(self, session_id: str) -> bool:
            """Return pending follow-up work for the session."""
            assert session_id == message.session_id
            return True

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            user_messages=[],
            has_actionable_work=False,
            context_invalidated=True,
        )

    async def resolve_failure(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("resolve_invoke_input should not be called")

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        executor,
        "input_buffer_service",
        cast(InputBufferService, PendingInputBufferService()),
    )
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input",
        resolve_failure,
    )

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id, event

    result = await executor.execute(
        message,
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=cast(asyncio.Event, object()),
        dispatch_event=dispatch_event,
    )

    assert result.no_actionable_work is True
    assert lifecycle.wake_ups == [message]


@pytest.mark.asyncio
async def test_execute_ignores_wake_up_without_runtime_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wake-up with no durable work does not start the engine path."""
    dispatched: list[PublishedEvent] = []
    executor = _executor()

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(user_messages=[], has_actionable_work=False)

    async def resolve_failure(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("resolve_invoke_input should not be called")

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input",
        resolve_failure,
    )

    async def dispatch_event(
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        del session_id
        dispatched.append(event)

    result = await executor.execute(
        SessionWakeUp(
            agent_id="agent-001",
            session_id="session-001",
            user_id=None,
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-001",
            workspace_handle=None,
        ),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=cast(asyncio.Event, object()),
        dispatch_event=dispatch_event,
    )

    assert result == RunExecutionResult(
        toolkits=[],
        terminal_event_observed=False,
        no_actionable_work=True,
    )
    assert dispatched == []


@pytest.mark.asyncio
async def test_execute_runs_pending_command_inside_run_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RunExecutor resolves and executes pending commands inside the run boundary."""
    _patch_successful_resolution(monkeypatch)
    dispatched: list[tuple[str, PublishedEvent]] = []
    lifecycle = _SessionLifecycle()
    session_repository = _AgentSessionRepository()
    live_event_projector = _LiveEventProjector()
    handler = _CommandHandler(
        [
            ephemeral(
                RunPhaseChanged(
                    run_id="command-run",
                    phase=AgentRunPhase.NORMALIZING_OUTPUT,
                )
            )
        ]
    )
    executor = _executor(
        lifecycle,
        command_registry={"compact": cast(CommandHandler, handler)},
        agent_session_repository=session_repository,
        live_event_projector=live_event_projector,
    )

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        dispatched.append((session_id, event))

    result = await executor.execute(
        _message(),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        command=_pending_command(),
    )

    assert len(handler.requests) == 1
    assert len(handler.contexts) == 1
    run_id = result.run_id
    assert run_id is not None
    assert handler.contexts[0].run_id == run_id
    assert lifecycle.activities == [
        ("session-001", run_id, AgentRunPhase.COMPACTING),
        ("session-001", run_id, AgentRunPhase.NORMALIZING_OUTPUT),
    ]
    assert [type(event).__name__ for _, event in dispatched] == [
        "RunStarted",
        "RunPhaseChanged",
        "RunComplete",
    ]
    assert live_event_projector.flushed_session_ids == ["session-001"]
    assert lifecycle.cleared_session_ids == ["session-001"]
    assert lifecycle.terminal_runs == [(run_id, AgentRunStatus.COMPLETED)]
    assert result.terminal_run_status == AgentRunStatus.COMPLETED
    assert session_repository.cleared_commands == [("session-001", "command-001")]


@pytest.mark.asyncio
async def test_execute_ignores_unknown_command_without_run_boundary() -> None:
    """Unknown commands are cleared before a run id is created."""
    dispatched: list[PublishedEvent] = []
    lifecycle = _SessionLifecycle()
    session_repository = _AgentSessionRepository()
    live_event_projector = _LiveEventProjector()
    executor = _executor(
        lifecycle,
        agent_session_repository=session_repository,
        live_event_projector=live_event_projector,
    )

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id
        dispatched.append(event)

    result = await executor.execute(
        _message(),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        command=_pending_command("unknown"),
    )

    assert result == RunExecutionResult(
        toolkits=[],
        terminal_event_observed=False,
        no_actionable_work=False,
    )
    assert dispatched == []
    assert lifecycle.activities == []
    assert lifecycle.cleared_session_ids == []
    assert lifecycle.terminal_runs == []
    assert session_repository.cleared_commands == [("session-001", "command-001")]
    assert live_event_projector.flushed_session_ids == []


@pytest.mark.asyncio
async def test_execute_finalizes_command_error_through_failed_run_finalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Command run-stopping errors use shared failed-run finalization."""
    _patch_successful_resolution(monkeypatch)
    lifecycle = _SessionLifecycle()
    session_repository = _AgentSessionRepository()
    finalizer = _FailedRunFinalizer()
    executor = _executor(
        lifecycle,
        command_registry={"compact": cast(CommandHandler, _FailingCommandHandler())},
        agent_session_repository=session_repository,
        failed_run_finalizer=finalizer,
        failed_run_max_retries=1,
    )
    dispatched: list[tuple[str, PublishedEvent]] = []

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        dispatched.append((session_id, event))

    result = await executor.execute(
        _message(),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        command=_pending_command(),
    )

    assert [type(event).__name__ for _, event in dispatched] == ["RunStarted"]
    assert len(finalizer.inputs) == 1
    finalization_input = finalizer.inputs[0]
    assert finalization_input.session_id == "session-001"
    assert finalization_input.run_id == result.run_id
    assert finalization_input.user_message == "command failed"
    assert finalization_input.retry_state.last_source == "command"
    assert finalization_input.retry_state.last_error_type == "UserVisibleRuntimeError"
    assert finalization_input.reason == "retry_exhausted"
    assert result.terminal_run_status == AgentRunStatus.FAILED
    assert session_repository.cleared_commands == [("session-001", "command-001")]


@pytest.mark.asyncio
async def test_execute_clears_activity_after_run_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RunComplete is the boundary that clears live run activity."""
    order: list[str] = []
    dispatched: list[PublishedEvent] = []
    live_event_projector = _LiveEventProjector()
    executor = _executor(
        _SessionLifecycle(order),
        live_event_projector=live_event_projector,
    )
    message = SessionWakeUp(
        agent_id="agent-001",
        session_id="session-001",
        user_id=None,
        additional_system_prompt=None,
        interface=None,
        workspace_id="workspace-001",
        workspace_handle=None,
    )

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(user_messages=[], has_actionable_work=True)

    async def resolve_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return Success(
            RunRequest(
                session_id="session-001",
                user_messages=[],
                agent_prompt=None,
                toolkits=[],
                model="gpt-test",
                credential_kwargs={},
                workspace_id="workspace-001",
                agent_id="agent-001",
            )
        )

    async def resolve_agent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    async def resolve_subagent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input",
        resolve_success,
    )
    monkeypatch.setattr(
        run_executor_module,
        "resolve_agent_tools",
        resolve_agent_tools_success,
    )
    monkeypatch.setattr(
        run_executor_module,
        "resolve_subagent_tools",
        resolve_subagent_tools_success,
    )

    async def dispatch_event(
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        del session_id
        dispatched.append(event)

    result = await executor.execute(
        message,
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
    )

    assert result.toolkits == []
    assert result.terminal_event_observed is True
    assert result.run_id is not None
    assert result.terminal_run_status == AgentRunStatus.COMPLETED
    assert any(isinstance(event, RunComplete) for event in dispatched)
    assert order == ["clear_session_activity"]
    assert live_event_projector.live_run_cleared_session_ids == ["session-001"]


def test_actionable_tail_ignores_completed_run_marker() -> None:
    """A transcript already covered by a run marker has no new work."""
    run_marker = Event(
        id="1123456789abcdef0123456789abcdea",
        session_id="session-1",
        kind=EventKind.RUN_MARKER,
        payload=RunMarkerPayload(run_id="run-1", status="completed"),
        created_at=run_executor_module.tznow(),
    )

    assert not has_actionable_tail([run_marker])


def test_actionable_tail_detects_goal_continuation_after_run_marker() -> None:
    """A durable continuation after a run marker must wake the model."""
    run_marker = Event(
        id="1123456789abcdef0123456789abcdea",
        session_id="session-1",
        kind=EventKind.RUN_MARKER,
        payload=RunMarkerPayload(run_id="run-1", status="completed"),
        created_at=run_executor_module.tznow(),
    )
    continuation = Event(
        id="1123456789abcdef0123456789abcdeb",
        session_id="session-1",
        kind=EventKind.GOAL_CONTINUATION,
        payload=UserMessagePayload(content="", metadata={"source": "goal"}),
        created_at=run_executor_module.tznow(),
    )

    assert has_actionable_tail([run_marker, continuation])


@pytest.mark.asyncio
async def test_run_session_heartbeat_loop_refreshes_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RunExecutor refreshes session heartbeat during engine execution."""
    lifecycle = _SessionLifecycle()
    monkeypatch.setattr(run_executor_module, "_RUN_HEARTBEAT_INTERVAL_SECONDS", 0.01)
    executor = _executor(session_lifecycle=lifecycle)

    task = asyncio.create_task(
        executor._run_session_heartbeat_loop(  # pyright: ignore[reportPrivateUsage]
            "session-001"
        )
    )
    try:
        while len(lifecycle.heartbeat_session_ids) < 2:
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert lifecycle.heartbeat_session_ids[:2] == ["session-001", "session-001"]


@pytest.mark.asyncio
async def test_execute_retries_failed_run_without_durable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed attempt persists retry state and retries without durable error."""
    monkeypatch.setattr(run_executor_module, "_FAILED_RUN_RETRY_WAIT_POLL_SECONDS", 0)
    lifecycle = _SessionLifecycle()
    engine = _FlakyEngine()
    finalizer = _FailedRunFinalizer()
    live_event_projector = _LiveEventProjector()
    executor = _executor(
        lifecycle,
        engine=cast(AgentEngineProtocol, engine),
        failed_run_finalizer=finalizer,
        live_event_projector=live_event_projector,
    )
    dispatched: list[PublishedEvent] = []

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(user_messages=[], has_actionable_work=True)

    async def resolve_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return Success(
            RunRequest(
                session_id="session-001",
                user_messages=[],
                agent_prompt=None,
                toolkits=[],
                model="gpt-test",
                credential_kwargs={},
                workspace_id="workspace-001",
                agent_id="agent-001",
            )
        )

    async def resolve_agent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    async def resolve_subagent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(run_executor_module, "resolve_invoke_input", resolve_success)
    monkeypatch.setattr(
        run_executor_module, "resolve_agent_tools", resolve_agent_tools_success
    )
    monkeypatch.setattr(
        run_executor_module, "resolve_subagent_tools", resolve_subagent_tools_success
    )

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id
        dispatched.append(event)

    result = await executor.execute(
        SessionWakeUp(
            agent_id="agent-001",
            session_id="session-001",
            user_id=None,
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-001",
            workspace_handle=None,
        ),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
    )

    assert engine.calls == 2
    assert result.terminal_run_status == AgentRunStatus.COMPLETED
    assert len(lifecycle.retry_states) == 1
    retry_state = lifecycle.retry_states[0]
    assert retry_state is not None
    assert retry_state.failed_attempt_count == 1
    assert retry_state.last_user_message == "model temporarily unavailable"
    retry_updates = [
        run.retry
        for _, run in live_event_projector.live_run_updates
        if run.retry is not None
    ]
    assert len(retry_updates) == 1
    assert retry_updates[0].last_error_message == "model temporarily unavailable"
    assert retry_updates[0].attempts[0].user_message == "model temporarily unavailable"
    assert finalizer.inputs == []
    assert not any(
        isinstance(event, Event) and event.kind == EventKind.SYSTEM_ERROR
        for event in dispatched
    )


@pytest.mark.asyncio
async def test_execute_publishes_retry_state_after_internal_attempt_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Internal attempt failures publish live retry state before waiting."""
    monkeypatch.setattr(run_executor_module, "_FAILED_RUN_RETRY_WAIT_POLL_SECONDS", 0)
    lifecycle = _SessionLifecycle()
    engine = _InternalFlakyEngine()
    live_event_projector = _LiveEventProjector()
    executor = _executor(
        lifecycle,
        engine=cast(AgentEngineProtocol, engine),
        live_event_projector=live_event_projector,
    )

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(user_messages=[], has_actionable_work=True)

    async def resolve_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return Success(
            RunRequest(
                session_id="session-001",
                user_messages=[],
                agent_prompt=None,
                toolkits=[],
                model="gpt-test",
                credential_kwargs={},
                workspace_id="workspace-001",
                agent_id="agent-001",
            )
        )

    async def resolve_agent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    async def resolve_subagent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(run_executor_module, "resolve_invoke_input", resolve_success)
    monkeypatch.setattr(
        run_executor_module, "resolve_agent_tools", resolve_agent_tools_success
    )
    monkeypatch.setattr(
        run_executor_module, "resolve_subagent_tools", resolve_subagent_tools_success
    )

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id, event

    result = await executor.execute(
        _message(),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
    )

    assert engine.calls == 2
    assert result.terminal_run_status == AgentRunStatus.COMPLETED
    retry_updates = [
        run.retry
        for _, run in live_event_projector.live_run_updates
        if run.retry is not None
    ]
    assert len(retry_updates) == 1
    assert retry_updates[0].last_error_message == "An internal error occurred."
    assert retry_updates[0].attempts[0].error_type == "RuntimeError"


@pytest.mark.asyncio
async def test_execute_finalizes_when_failed_run_retry_is_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop during retry promotes the latest attempt through the finalizer."""
    monkeypatch.setattr(run_executor_module, "_FAILED_RUN_RETRY_WAIT_POLL_SECONDS", 0)
    lifecycle = _SessionLifecycle()
    engine = _AlwaysFailingEngine()
    finalizer = _FailedRunFinalizer()
    executor = _executor(
        lifecycle,
        engine=cast(AgentEngineProtocol, engine),
        failed_run_finalizer=finalizer,
    )

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(user_messages=[], has_actionable_work=True)

    async def resolve_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return Success(
            RunRequest(
                session_id="session-001",
                user_messages=[],
                agent_prompt=None,
                toolkits=[],
                model="gpt-test",
                credential_kwargs={},
                workspace_id="workspace-001",
                agent_id="agent-001",
            )
        )

    async def resolve_agent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    async def resolve_subagent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(run_executor_module, "resolve_invoke_input", resolve_success)
    monkeypatch.setattr(
        run_executor_module, "resolve_agent_tools", resolve_agent_tools_success
    )
    monkeypatch.setattr(
        run_executor_module, "resolve_subagent_tools", resolve_subagent_tools_success
    )

    async def check_stop() -> bool:
        return True

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id, event

    result = await executor.execute(
        SessionWakeUp(
            agent_id="agent-001",
            session_id="session-001",
            user_id=None,
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-001",
            workspace_handle=None,
        ),
        poll_fn=None,
        check_stop=check_stop,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
    )

    assert engine.calls == 1
    assert result.terminal_run_status == AgentRunStatus.FAILED
    assert len(lifecycle.retry_states) == 1
    assert len(finalizer.inputs) == 1
    assert finalizer.inputs[0].reason == "retry_stopped_by_user"


@pytest.mark.asyncio
async def test_execute_finalizes_when_failed_run_retry_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry exhaustion promotes the latest attempt through the finalizer."""
    lifecycle = _SessionLifecycle()
    engine = _AlwaysFailingEngine()
    finalizer = _FailedRunFinalizer()
    executor = _executor(
        lifecycle,
        engine=cast(AgentEngineProtocol, engine),
        failed_run_finalizer=finalizer,
        failed_run_max_retries=1,
    )

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(user_messages=[], has_actionable_work=True)

    async def resolve_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return Success(
            RunRequest(
                session_id="session-001",
                user_messages=[],
                agent_prompt=None,
                toolkits=[],
                model="gpt-test",
                credential_kwargs={},
                workspace_id="workspace-001",
                agent_id="agent-001",
            )
        )

    async def resolve_agent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    async def resolve_subagent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(run_executor_module, "resolve_invoke_input", resolve_success)
    monkeypatch.setattr(
        run_executor_module, "resolve_agent_tools", resolve_agent_tools_success
    )
    monkeypatch.setattr(
        run_executor_module, "resolve_subagent_tools", resolve_subagent_tools_success
    )

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id, event

    result = await executor.execute(
        SessionWakeUp(
            agent_id="agent-001",
            session_id="session-001",
            user_id=None,
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-001",
            workspace_handle=None,
        ),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
    )

    assert engine.calls == 1
    assert result.terminal_run_status == AgentRunStatus.FAILED
    assert len(lifecycle.retry_states) == 1
    assert len(finalizer.inputs) == 1
    assert finalizer.inputs[0].reason == "retry_exhausted"


@pytest.mark.asyncio
async def test_execute_finalizes_non_retryable_failed_run_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Known non-retryable model failures are finalized on the first attempt."""
    lifecycle = _SessionLifecycle()
    engine = _AlwaysFailingEngine(
        'Model call failed (503): {"error":{"code":"no_fixture_match"}}'
    )
    finalizer = _FailedRunFinalizer()
    executor = _executor(
        lifecycle,
        engine=cast(AgentEngineProtocol, engine),
        failed_run_finalizer=finalizer,
    )

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(user_messages=[], has_actionable_work=True)

    async def resolve_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return Success(
            RunRequest(
                session_id="session-001",
                user_messages=[],
                agent_prompt=None,
                toolkits=[],
                model="gpt-test",
                credential_kwargs={},
                workspace_id="workspace-001",
                agent_id="agent-001",
            )
        )

    async def resolve_agent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    async def resolve_subagent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(run_executor_module, "resolve_invoke_input", resolve_success)
    monkeypatch.setattr(
        run_executor_module, "resolve_agent_tools", resolve_agent_tools_success
    )
    monkeypatch.setattr(
        run_executor_module, "resolve_subagent_tools", resolve_subagent_tools_success
    )

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id, event

    result = await executor.execute(
        SessionWakeUp(
            agent_id="agent-001",
            session_id="session-001",
            user_id=None,
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-001",
            workspace_handle=None,
        ),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
    )

    assert engine.calls == 1
    assert result.terminal_run_status == AgentRunStatus.FAILED
    assert len(lifecycle.retry_states) == 1
    retry_state = lifecycle.retry_states[0]
    assert retry_state is not None
    assert retry_state.retryability == "non_retryable"
    assert retry_state.failure_code == "no_fixture_match"
    assert retry_state.backoff_seconds == 0
    assert len(finalizer.inputs) == 1
    assert finalizer.inputs[0].reason == "non_retryable"
