"""CommandExecutor tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Any, cast

import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

import azents.worker.run.command_executor as command_executor_module
from azents.broker.types import PublishedEvent
from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.engine.events.engine_events import (
    RunComplete,
    RunPhaseChanged,
    RunStarted,
)
from azents.engine.run.commands import CommandHandler, SlashCommandDefinition
from azents.engine.run.contracts import AgentEngineProtocol, RunRequest
from azents.engine.run.emit import Emit, ephemeral
from azents.engine.run.errors import UserVisibleRuntimeError
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import PendingSessionCommand
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.worker.live.event_projector import LiveEventProjector
from azents.worker.run.command_executor import CommandExecutor
from azents.worker.run.finalizer import FailedRunFinalizationInput
from azents.worker.session.lifecycle import SessionLifecycleService


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


class _SessionLifecycle:
    """SessionLifecycleService test double."""

    def __init__(self) -> None:
        self.activities: list[tuple[str, str, AgentRunPhase | None]] = []
        self.cleared_session_ids: list[str] = []
        self.created: list[AgentRunCreate] = []
        self.terminal_runs: list[tuple[str, AgentRunStatus]] = []

    async def create_agent_run_projection(
        self,
        session_id: str,
        *,
        run_id: str,
        phase: AgentRunPhase | None,
    ) -> None:
        """Record AgentRun create request."""
        self.created.append(
            AgentRunCreate(
                id=run_id,
                session_id=session_id,
                phase=phase or AgentRunPhase.IDLE,
            )
        )

    async def set_session_activity(
        self,
        session_id: str,
        *,
        run_id: str,
        phase: AgentRunPhase | None,
        active_tool_calls: object = None,
    ) -> None:
        """Record session activity set request."""
        del active_tool_calls
        self.activities.append((session_id, run_id, phase))

    async def clear_session_activity(self, session_id: str) -> None:
        """Record session activity removal request."""
        self.cleared_session_ids.append(session_id)

    async def mark_agent_run_terminal_if_running(
        self,
        session_id: str,
        *,
        run_id: str,
        status: AgentRunStatus,
    ) -> None:
        """Record terminal transition request."""
        del session_id
        self.terminal_runs.append((run_id, status))


class _AgentSessionRepository(AgentSessionRepository):
    """AgentRuntimeRepository test double."""

    def __init__(self) -> None:
        self.cleared_commands: list[tuple[str, str]] = []

    async def clear_pending_command(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        command_id: str,
    ) -> None:
        """Record pending command cleanup request."""
        del session
        self.cleared_commands.append((session_id, command_id))


class _LiveEventProjector:
    """LiveEventProjector test double."""

    def __init__(self) -> None:
        self.flushed_session_ids: list[str] = []
        self.replaced_active_tool_calls: list[tuple[str, object]] = []

    async def flush_session(self, session_id: str) -> None:
        """Record flush request."""
        self.flushed_session_ids.append(session_id)

    async def replace_active_tool_calls(
        self,
        session_id: str,
        active_tool_calls: object,
    ) -> None:
        """Record active tool call replacement request."""
        self.replaced_active_tool_calls.append((session_id, active_tool_calls))


class _CommandHandler:
    """CommandHandler test double."""

    definition = SlashCommandDefinition(name="test", description="test command")

    def __init__(self, events: list[PublishedEvent]) -> None:
        self.events = events
        self.requests: list[RunRequest] = []

    async def execute(
        self,
        engine: AgentEngineProtocol,
        request: RunRequest,
    ) -> AsyncIterator[Emit]:
        """Yield specified events in order."""
        del engine
        self.requests.append(request)
        for event in self.events:
            yield ephemeral(event)


class _FailingCommandHandler(_CommandHandler):
    """Command handler that raises a user-visible error."""

    async def execute(
        self,
        engine: AgentEngineProtocol,
        request: RunRequest,
    ) -> AsyncIterator[Emit]:
        """Raise while executing command."""
        del engine
        self.requests.append(request)
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
        """Record failed-run finalization input."""
        del dispatch_event
        self.inputs.append(input)
        return object()


def _executor(
    *,
    handler: CommandHandler,
    session_lifecycle: _SessionLifecycle,
    agent_session_repository: _AgentSessionRepository,
    live_event_projector: _LiveEventProjector,
    failed_run_finalizer: object | None = None,
) -> CommandExecutor:
    """Create CommandExecutor under test."""
    if failed_run_finalizer is None:
        failed_run_finalizer = _FailedRunFinalizer()
    return CommandExecutor(
        command_registry={"compact": handler},
        session_manager=cast(Any, _SessionManager()),
        engine=cast(AgentEngineProtocol, object()),
        agent_repository=cast(AgentRepository, object()),
        integration_repository=cast(LLMProviderIntegrationRepository, object()),
        agent_session_repository=agent_session_repository,
        session_lifecycle=cast(SessionLifecycleService, session_lifecycle),
        exchange_file_service=cast(ExchangeFileService, object()),
        model_file_service=cast(ModelFileService, object()),
        live_event_projector=cast(LiveEventProjector, live_event_projector),
        failed_run_finalizer=cast(Any, failed_run_finalizer),
    )


@pytest.mark.asyncio
async def test_execute_runs_command_and_marks_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CommandExecutor completes command run lifecycle."""
    dispatched: list[tuple[str, PublishedEvent]] = []
    session_lifecycle = _SessionLifecycle()
    session_repository = _AgentSessionRepository()
    live_event_projector = _LiveEventProjector()
    handler = _CommandHandler(
        [
            RunPhaseChanged(
                run_id="command-run",
                phase=AgentRunPhase.NORMALIZING_OUTPUT,
            )
        ]
    )

    async def resolve_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return Success(cast(RunRequest, object()))

    monkeypatch.setattr(
        command_executor_module,
        "resolve_invoke_input",
        resolve_success,
    )

    async def dispatch_event(
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        dispatched.append((session_id, event))

    executor = _executor(
        handler=cast(CommandHandler, handler),
        session_lifecycle=session_lifecycle,
        agent_session_repository=session_repository,
        live_event_projector=live_event_projector,
    )

    result = await executor.execute(
        agent_id="agent-001",
        session_id="session-001",
        command=PendingSessionCommand(
            id="command-001",
            name="compact",
            payload={},
            user_id="user-001",
            created_at=datetime.datetime.now(datetime.UTC),
        ),
        dispatch_event=dispatch_event,
    )

    assert len(handler.requests) == 1
    assert session_lifecycle.created[0].session_id == "session-001"
    assert session_lifecycle.created[0].phase == AgentRunPhase.COMPACTING
    run_id = session_lifecycle.created[0].id
    assert run_id is not None
    assert session_lifecycle.activities == [
        ("session-001", run_id, AgentRunPhase.COMPACTING),
        ("session-001", run_id, AgentRunPhase.NORMALIZING_OUTPUT),
    ]
    assert [type(event).__name__ for _, event in dispatched] == [
        "RunStarted",
        "RunPhaseChanged",
        "RunComplete",
    ]
    assert isinstance(dispatched[0][1], RunStarted)
    assert isinstance(dispatched[-1][1], RunComplete)
    assert live_event_projector.flushed_session_ids == ["session-001"]
    assert session_lifecycle.cleared_session_ids == ["session-001"]
    assert session_lifecycle.terminal_runs == [(run_id, AgentRunStatus.COMPLETED)]
    assert result.terminal_run_status == AgentRunStatus.COMPLETED
    assert session_repository.cleared_commands == [("session-001", "command-001")]


@pytest.mark.asyncio
async def test_execute_ignores_unknown_command() -> None:
    """Unregistered command is ignored without side effects."""
    dispatched: list[PublishedEvent] = []
    session_lifecycle = _SessionLifecycle()
    session_repository = _AgentSessionRepository()
    live_event_projector = _LiveEventProjector()
    executor = _executor(
        handler=cast(CommandHandler, _CommandHandler([])),
        session_lifecycle=session_lifecycle,
        agent_session_repository=session_repository,
        live_event_projector=live_event_projector,
    )

    async def dispatch_event(
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        del session_id
        dispatched.append(event)

    await executor.execute(
        agent_id="agent-001",
        session_id="session-001",
        command=PendingSessionCommand(
            id="command-001",
            name="noop",
            payload={},
            user_id="user-001",
            created_at=datetime.datetime.now(datetime.UTC),
        ),
        dispatch_event=dispatch_event,
    )

    assert dispatched == []
    assert session_lifecycle.activities == []
    assert session_lifecycle.cleared_session_ids == []
    assert session_lifecycle.created == []
    assert session_lifecycle.terminal_runs == []
    assert session_repository.cleared_commands == [("session-001", "command-001")]
    assert live_event_projector.flushed_session_ids == []


@pytest.mark.asyncio
async def test_execute_finalizes_command_error_through_failed_run_finalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Command run-stopping errors use shared failed-run finalization."""
    dispatched: list[tuple[str, PublishedEvent]] = []
    session_lifecycle = _SessionLifecycle()
    session_repository = _AgentSessionRepository()
    live_event_projector = _LiveEventProjector()
    finalizer = _FailedRunFinalizer()
    handler = _FailingCommandHandler([])

    async def resolve_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return Success(cast(RunRequest, object()))

    monkeypatch.setattr(
        command_executor_module,
        "resolve_invoke_input",
        resolve_success,
    )

    async def dispatch_event(
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        dispatched.append((session_id, event))

    executor = _executor(
        handler=cast(CommandHandler, handler),
        session_lifecycle=session_lifecycle,
        agent_session_repository=session_repository,
        live_event_projector=live_event_projector,
        failed_run_finalizer=finalizer,
    )

    result = await executor.execute(
        agent_id="agent-001",
        session_id="session-001",
        command=PendingSessionCommand(
            id="command-001",
            name="compact",
            payload={},
            user_id="user-001",
            created_at=datetime.datetime.now(datetime.UTC),
        ),
        dispatch_event=dispatch_event,
    )

    assert [type(event).__name__ for _, event in dispatched] == ["RunStarted"]
    assert len(finalizer.inputs) == 1
    finalization_input = finalizer.inputs[0]
    assert finalization_input.session_id == "session-001"
    assert finalization_input.run_id == session_lifecycle.created[0].id
    assert finalization_input.user_message == "command failed"
    assert finalization_input.retry_state.last_source == "command"
    assert finalization_input.retry_state.last_error_type == "UserVisibleRuntimeError"
    assert finalization_input.reason == "retry_exhausted"
    assert result.terminal_run_status == AgentRunStatus.FAILED
    assert session_repository.cleared_commands == [("session-001", "command-001")]
