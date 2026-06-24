"""RunExecutor tests."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Any, cast

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

import azents.worker.run.executor as run_executor_module
from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.types import PublishedEvent, SessionBroker, SessionWakeUp
from azents.core.enums import EventKind
from azents.core.tools import ToolkitProvider
from azents.engine.events.engine_events import RunComplete
from azents.engine.events.types import (
    Event,
    RunMarkerPayload,
    SystemErrorPayload,
    UserMessagePayload,
)
from azents.engine.run.background import BackgroundTaskRegistry
from azents.engine.run.contracts import AgentEngineProtocol, RunRequest
from azents.engine.run.emit import Emit, ephemeral
from azents.engine.run.input import AgentNotFound
from azents.engine.tools.builtin import BuiltinToolkitProvider
from azents.engine.tools.goal import GoalToolkitProvider
from azents.engine.tools.todo import TodoToolkitProvider
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_subagent import AgentSubagentRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.toolkit import AgentToolkitRepository, ToolkitRepository
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import InputBufferService
from azents.services.model_file import ModelFileService
from azents.worker.config import AgentWorkerConfig
from azents.worker.live.event_projector import LiveEventProjector
from azents.worker.run.executor import (
    RunExecutor,
    RunInputPollResult,
    has_actionable_tail,
)
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

    async def set_session_activity(
        self,
        session_id: str,
        *,
        run_id: str,
        phase: object,
        active_tool_calls: object = None,
    ) -> None:
        """Do not record session activity in this test double."""
        del session_id, run_id, phase, active_tool_calls

    async def clear_session_activity(self, session_id: str) -> None:
        """Do not clear session activity in this test double."""
        del session_id
        if self.order is not None:
            self.order.append("clear_session_activity")

    async def mark_agent_run_terminal_if_running(
        self,
        session_id: str,
        *,
        run_id: str,
        status: object,
    ) -> None:
        """Do not mutate AgentRun state in this test double."""
        del session_id, run_id, status

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


class _LiveEventProjector:
    """LiveEventProjector test double."""

    def __init__(self) -> None:
        self.flushed_session_ids: list[str] = []

    async def replace_active_tool_calls(
        self,
        session_id: str,
        active_tool_calls: object,
    ) -> None:
        """No-op active tool call projection."""
        del session_id, active_tool_calls

    async def flush_session(self, session_id: str) -> None:
        """Record flushed sessions."""
        self.flushed_session_ids.append(session_id)


class _Engine:
    """AgentEngineProtocol test double."""

    async def save_error_message(self, session_id: str, content: str) -> Event:
        """This test engine should not save errors."""
        del session_id, content
        raise AssertionError("save_error_message should not be called")

    def compact(self, request: RunRequest) -> AsyncIterator[Emit]:
        """Manual compaction is not used by these tests."""
        del request
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


def _executor(
    session_lifecycle: _SessionLifecycle | None = None,
    *,
    engine: AgentEngineProtocol | None = None,
) -> RunExecutor:
    """Create a RunExecutor for resolve-failure tests."""
    if session_lifecycle is None:
        session_lifecycle = _SessionLifecycle()
    if engine is None:
        engine = cast(AgentEngineProtocol, _Engine())
    return RunExecutor(
        broker=cast(SessionBroker, object()),
        session_manager=cast(SessionManager[AsyncSession], _SessionManager()),
        engine=engine,
        agent_repository=cast(AgentRepository, _AgentRepository()),
        integration_repository=cast(LLMProviderIntegrationRepository, object()),
        toolkit_registry=cast(dict[str, ToolkitProvider[Any]], {}),
        agent_toolkit_repository=cast(AgentToolkitRepository, object()),
        toolkit_repository=cast(ToolkitRepository, object()),
        agent_subagent_repository=cast(AgentSubagentRepository, object()),
        agent_runtime_repository=cast(AgentRuntimeRepository, object()),
        agent_session_repository=cast(
            AgentSessionRepository,
            _AgentSessionRepository(),
        ),
        event_session_repository=cast(Any, object()),
        event_transcript_repository=cast(Any, object()),
        session_lifecycle=cast(SessionLifecycleService, session_lifecycle),
        worker_config=AgentWorkerConfig(
            web_url="http://localhost:3000",
            oauth_secret_key="test-secret",
            mcp_proxy_url=None,
        ),
        exchange_file_service=cast(ExchangeFileService, object()),
        model_file_service=cast(ModelFileService, object()),
        input_buffer_service=cast(InputBufferService, object()),
        live_event_projector=cast(LiveEventProjector, _LiveEventProjector()),
        user_stop_finalizer=cast(UserStopFinalizer, object()),
        background_registry=cast(BackgroundTaskRegistry, object()),
        builtin_toolkit_provider=cast(BuiltinToolkitProvider, object()),
        todo_toolkit_provider=cast(TodoToolkitProvider, object()),
        goal_toolkit_provider=cast(GoalToolkitProvider, object()),
        broadcast=cast(WebSocketBroadcast, object()),
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
    error_event = dispatched[0]
    assert isinstance(error_event, Event)
    assert error_event.kind == EventKind.SYSTEM_ERROR
    assert isinstance(error_event.payload, SystemErrorPayload)
    assert error_event.payload.content == "AgentNotFound(agent_id='agent-001')"
    assert isinstance(dispatched[1], RunComplete)


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
async def test_execute_clears_activity_after_run_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RunComplete is the boundary that clears live run activity."""
    order: list[str] = []
    dispatched: list[PublishedEvent] = []
    executor = _executor(_SessionLifecycle(order))
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
    assert any(isinstance(event, RunComplete) for event in dispatched)
    assert order == ["clear_session_activity"]


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
