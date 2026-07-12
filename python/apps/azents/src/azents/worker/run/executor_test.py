"""RunExecutor tests."""

import asyncio
import contextlib
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from typing import Any, cast

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

import azents.worker.run.executor as run_executor_module
from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.types import PublishedEvent, SessionBroker, SessionWakeUp
from azents.core.agent import AgentModelSelection
from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionKind,
    EventKind,
)
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    InferenceProfileFailureCode,
    InferenceProfileSource,
    RequestedInferenceProfile,
    SessionInferenceState,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.tools import ToolkitProvider
from azents.engine.events.engine_events import (
    RunComplete,
    RunPhaseChanged,
    SubagentTreeChanged,
)
from azents.engine.events.types import (
    ActiveToolCall,
    Event,
    RunMarkerPayload,
    SystemErrorPayload,
    UserMessagePayload,
)
from azents.engine.events.user_messages import make_run_user_message
from azents.engine.run.commands import CommandHandler
from azents.engine.run.contracts import AgentEngineProtocol, RunContext, RunRequest
from azents.engine.run.emit import Emit, ephemeral
from azents.engine.run.errors import (
    ModelCallError,
    UserVisibleRuntimeError,
)
from azents.engine.run.failure import FailedRunRetryState
from azents.engine.run.input import AgentNotFound
from azents.engine.run.resolve import ResolvedInvokeInputProfile
from azents.engine.run.types import PollMessagesResult
from azents.engine.tools.builtin import BuiltinToolkitProvider
from azents.engine.tools.claude_rules import ClaudeRulesToolkitProvider
from azents.engine.tools.goal import GoalToolkitProvider
from azents.engine.tools.skill import SkillToolkitProvider
from azents.engine.tools.subagent import SubagentToolkitProvider
from azents.engine.tools.todo import TodoToolkitProvider
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import PendingSessionCommand
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.toolkit import AgentToolkitRepository, ToolkitRepository
from azents.services.chat.data import ChatLiveRunState
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import (
    InputBufferService,
    PendingInputInferenceProfile,
    PromotedInputBuffers,
    TurnEffect,
)
from azents.services.model_file import ModelFileService
from azents.services.session_git_worktree import SessionGitWorktreeService
from azents.services.session_title import SessionTitleService
from azents.testing.model_selection import make_test_model_selection
from azents.transport.chat import chat_live_run_updated_dump
from azents.worker.config import AgentWorkerConfig
from azents.worker.live.event_projector import LiveEventProjector
from azents.worker.run.executor import (
    OperationActionProcessResult,
    RunExecutor,
    RunInputPollResult,
    has_actionable_tail,
)
from azents.worker.run.finalizer import FailedRunFinalizationInput
from azents.worker.run.results import RunExecutionResult
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.user_stop_finalizer import UserStopFinalizer


class _DBSession:
    """Minimal DB session test double."""

    async def commit(self) -> None:
        """Accept transaction commits."""


class _SessionScope(AbstractAsyncContextManager[AsyncSession]):
    """DB session scope test double."""

    async def __aenter__(self) -> AsyncSession:
        """Return a dummy DB session."""
        return cast(AsyncSession, _DBSession())

    async def __aexit__(self, *exc_info: object) -> None:
        """No resources to clean up."""


class _SessionManager:
    """SessionManager test double."""

    def __call__(self) -> _SessionScope:
        """Return a new session scope."""
        return _SessionScope()


@dataclasses.dataclass(frozen=True)
class _PendingRun:
    """Minimal pending-run projection for executor tests."""

    id: str = "run-001"
    requested_model_target_label: str | None = "default"
    requested_reasoning_effort: ModelReasoningEffort | None = None
    inference_profile_source: InferenceProfileSource = (
        InferenceProfileSource.AGENT_DEFAULT
    )
    resolved_model_selection: AgentModelSelection | None = None
    resolved_reasoning_effort: ModelReasoningEffort | None = None
    resolved_at: datetime.datetime | None = None
    effective_context_window_tokens: int | None = None
    effective_auto_compaction_threshold_tokens: int | None = None
    parent_agent_run_id: str | None = None
    status: AgentRunStatus = AgentRunStatus.PENDING
    phase: AgentRunPhase = AgentRunPhase.IDLE
    active_tool_calls: list[ActiveToolCall] = dataclasses.field(default_factory=list)
    retry_state: FailedRunRetryState | None = None


class _SessionLifecycle:
    """SessionLifecycleService test double."""

    def __init__(
        self,
        order: list[str] | None = None,
        *,
        recoverable_run: _PendingRun | None = None,
    ) -> None:
        self.order = order
        self.recoverable_run = recoverable_run
        self.heartbeat_session_ids: list[str] = []
        self.retry_states: list[FailedRunRetryState | None] = []
        self.activities: list[tuple[str, str, object]] = []
        self.cleared_session_ids: list[str] = []
        self.terminal_runs: list[tuple[str, AgentRunStatus]] = []
        self.profile_resolution_failures: list[
            tuple[str, InferenceProfileFailureCode, str]
        ] = []
        self.pending_profile_failures: list[
            tuple[str, InferenceProfileFailureCode, str]
        ] = []
        self.idle_session_ids: list[str] = []
        self.wake_ups: list[SessionWakeUp] = []
        self.pending_run_create_calls = 0
        self.activation_calls = 0
        self.inherited_activation_calls = 0
        self.cancelled_pending_run_ids: list[str] = []

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

    async def fail_agent_run_profile_resolution_if_running(
        self,
        session_id: str,
        *,
        run_id: str,
        failure_code: InferenceProfileFailureCode,
        failure_message: str,
    ) -> None:
        """Record a recovered run profile-resolution failure."""
        del session_id
        self.profile_resolution_failures.append((run_id, failure_code, failure_message))

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

    async def claim_recoverable_agent_run(
        self,
        session_id: str,
    ) -> _PendingRun | None:
        """Return the configured recoverable run."""
        del session_id
        return self.recoverable_run

    async def create_or_claim_pending_agent_run(
        self,
        session_id: str,
        **kwargs: object,
    ) -> _PendingRun:
        """Return one stable pending run for execution tests."""
        del session_id, kwargs
        self.pending_run_create_calls += 1
        return _PendingRun()

    async def cancel_pending_agent_run(
        self,
        session_id: str,
        *,
        run_id: str,
    ) -> _PendingRun:
        """Record cancellation of a new pending run with no model work."""
        del session_id
        self.cancelled_pending_run_ids.append(run_id)
        return _PendingRun(status=AgentRunStatus.CANCELLED)

    async def activate_pending_agent_run(
        self,
        session_id: str,
        **kwargs: object,
    ) -> _PendingRun:
        """Accept activation before provider invocation."""
        del session_id, kwargs
        self.activation_calls += 1
        if self.order is not None:
            self.order.append("activate_pending")
        return _PendingRun(status=AgentRunStatus.RUNNING)

    async def activate_inherited_pending_agent_run(
        self,
        session_id: str,
        **kwargs: object,
    ) -> _PendingRun:
        """Accept inherited activation before provider invocation."""
        del session_id, kwargs
        self.inherited_activation_calls += 1
        if self.order is not None:
            self.order.append("activate_inherited")
        return _PendingRun(status=AgentRunStatus.RUNNING)

    async def fail_pending_agent_run_profile(
        self,
        session_id: str,
        **kwargs: object,
    ) -> _PendingRun:
        """Accept terminal profile failure persistence."""
        del session_id
        self.pending_profile_failures.append(
            (
                cast(str, kwargs["run_id"]),
                cast(InferenceProfileFailureCode, kwargs["failure_code"]),
                cast(str, kwargs["failure_message"]),
            )
        )
        return _PendingRun()

    async def associate_agent_run_input_events(
        self,
        session_id: str,
        **kwargs: object,
    ) -> None:
        """Accept active-run input association."""
        del session_id, kwargs

    async def list_inference_run_event_projections(
        self,
        *,
        run_id: str,
    ) -> list[object]:
        """Return no durable projections for lightweight executor tests."""
        del run_id
        return []


class _AgentRepository:
    """AgentRepository test double."""

    async def get_by_id(self, session: AsyncSession, agent_id: str) -> object | None:
        """Return no persisted agent settings."""
        del session, agent_id
        return None


class _AgentSessionRepository:
    """AgentSessionRepository test double."""

    def __init__(
        self,
        *,
        inference_state: SessionInferenceState | None = None,
        current_session_agent: object | None = None,
        tree_session_agents: list[object] | None = None,
    ) -> None:
        self.inference_state = inference_state
        self.cleared_commands: list[tuple[str, str]] = []
        self.current_session_agent = current_session_agent
        self.tree_session_agents = tree_session_agents or []

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> object | None:
        """Return the configured Session inference state."""
        del session, agent_session_id
        return SimpleNamespace(
            inference_state=self.inference_state,
            session_kind=AgentSessionKind.ROOT,
        )

    async def set_inference_state(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        inference_state: SessionInferenceState,
    ) -> object:
        """Record a newly prepared Session inference state."""
        del session, session_id
        self.inference_state = inference_state
        return SimpleNamespace(inference_state=inference_state)

    async def list_session_agent_tree(
        self,
        session: AsyncSession,
        *,
        root_session_agent_id: str,
    ) -> list[object]:
        """Return the configured SessionAgent tree."""
        del session, root_session_agent_id
        return self.tree_session_agents

    async def get_session_agent_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> object | None:
        """Return the configured current SessionAgent."""
        del session, session_id
        return self.current_session_agent

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


class _InputBufferService:
    """InputBufferService test double."""

    async def peek_pending_inference_profile(
        self,
        session_id: str,
    ) -> PendingInputInferenceProfile:
        """Return one implicit pending input by default."""
        del session_id
        return PendingInputInferenceProfile(
            input_buffer_id="buffer-1",
            requires_inference=False,
            exists=True,
            requested_inference_profile=None,
        )

    async def has_pending_session_input_buffers(self, session_id: str) -> bool:
        """Return no additional buffered input after execution."""
        del session_id
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


class _RecordingEngine(_Engine):
    """Engine that records provider requests and activation ordering."""

    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.requests: list[RunRequest] = []

    def run(
        self,
        request: RunRequest,
        context: object,
        *,
        poll_messages: object = None,
        check_stop: object = None,
    ) -> AsyncIterator[Emit]:
        """Record the request before completing the run."""
        self.order.append("provider")
        self.requests.append(request)
        return super().run(
            request,
            context,
            poll_messages=poll_messages,
            check_stop=check_stop,
        )


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
        inference_state = None
        recoverable = session_lifecycle.recoverable_run
        if (
            recoverable is not None
            and recoverable.resolved_model_selection is not None
            and recoverable.effective_context_window_tokens is not None
            and recoverable.effective_auto_compaction_threshold_tokens is not None
        ):
            inference_state = SessionInferenceState(
                model_target_label=recoverable.requested_model_target_label
                or "default",
                model_selection=recoverable.resolved_model_selection,
                reasoning_effort=recoverable.resolved_reasoning_effort,
                effective_context_window_tokens=(
                    recoverable.effective_context_window_tokens
                ),
                effective_auto_compaction_threshold_tokens=(
                    recoverable.effective_auto_compaction_threshold_tokens
                ),
                resolved_at=recoverable.resolved_at
                or datetime.datetime.now(datetime.UTC),
            )
        agent_session_repository = _AgentSessionRepository(
            inference_state=inference_state
        )
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
        input_buffer_service=cast(InputBufferService, _InputBufferService()),
        session_git_worktree_service=cast(SessionGitWorktreeService, object()),
        session_title_service=cast(SessionTitleService, _SessionTitleService()),
        live_event_projector=cast(LiveEventProjector, live_event_projector),
        user_stop_finalizer=cast(UserStopFinalizer, object()),
        failed_run_finalizer=cast(Any, failed_run_finalizer),
        builtin_toolkit_provider=cast(BuiltinToolkitProvider, object()),
        claude_rules_toolkit_provider=cast(ClaudeRulesToolkitProvider, object()),
        todo_toolkit_provider=cast(TodoToolkitProvider, object()),
        goal_toolkit_provider=cast(GoalToolkitProvider, object()),
        skill_toolkit_provider=cast(SkillToolkitProvider, object()),
        subagent_toolkit_provider=cast(SubagentToolkitProvider, object()),
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
        ResolvedInvokeInputProfile(
            run_request=RunRequest(
                session_id="session-001",
                user_messages=[],
                agent_prompt=None,
                toolkits=[],
                model="gpt-test",
                credential_kwargs={},
                workspace_id="workspace-001",
                agent_id="agent-001",
                auto_compaction_threshold_tokens=None,
            ),
            model_selection=make_test_model_selection(),
            reasoning_effort=None,
        )
    )


async def _resolve_existing_success(*args: object, **kwargs: object) -> object:
    """Return a minimal run request for an existing Session inference state."""
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
            auto_compaction_threshold_tokens=None,
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
    monkeypatch.setattr(
        run_executor_module, "resolve_invoke_input_with_profile", _resolve_success
    )
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_resolved_profile",
        _resolve_existing_success,
    )
    monkeypatch.setattr(run_executor_module, "resolve_agent_tools", _resolve_no_tools)


@pytest.mark.asyncio
async def test_execute_reports_resolve_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preparation failures cancel the pending run and publish a typed error."""
    dispatched: list[PublishedEvent] = []
    executor = _executor()

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=True,
        )

    async def resolve_failure(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return Failure(AgentNotFound(agent_id="agent-001"))

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_profile",
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
    assert result.terminal_run_status == AgentRunStatus.CANCELLED
    error_event = dispatched[0]
    assert isinstance(error_event, Event)
    assert error_event.kind == EventKind.SYSTEM_ERROR
    assert isinstance(error_event.payload, SystemErrorPayload)
    assert (
        error_event.payload.content
        == "The selected model could not be prepared for this run."
    )
    assert isinstance(dispatched[1], RunComplete)


@pytest.mark.asyncio
async def test_execute_recovers_activated_run_before_flushing_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A running activation is reused with its exact profile and snapshot."""
    selection = make_test_model_selection()
    recoverable = _PendingRun(
        status=AgentRunStatus.RUNNING,
        requested_model_target_label="Quality",
        requested_reasoning_effort=ModelReasoningEffort.HIGH,
        inference_profile_source=InferenceProfileSource.EXPLICIT_INPUT,
        resolved_model_selection=selection,
        resolved_reasoning_effort=ModelReasoningEffort.HIGH,
        effective_context_window_tokens=64_000,
        effective_auto_compaction_threshold_tokens=51_200,
    )
    lifecycle = _SessionLifecycle(recoverable_run=recoverable)
    executor = _executor(session_lifecycle=lifecycle)
    poll_calls: list[dict[str, object]] = []
    recovered_snapshots: list[AgentModelSelection] = []

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args
        poll_calls.append(kwargs)
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=False,
        )

    async def resolve_recovered(*args: object, **kwargs: object) -> object:
        del args
        resolved_selection = cast(
            AgentModelSelection,
            kwargs["resolved_model_selection"],
        )
        recovered_snapshots.append(resolved_selection)
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
                auto_compaction_threshold_tokens=None,
            )
        )

    async def resolve_new(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("A recovered run must not resolve its target again")

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_resolved_profile",
        resolve_recovered,
    )
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_profile",
        resolve_new,
    )
    monkeypatch.setattr(run_executor_module, "resolve_agent_tools", _resolve_no_tools)

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

    assert result.run_id == recoverable.id
    assert recovered_snapshots == [selection]
    assert lifecycle.pending_run_create_calls == 0
    assert lifecycle.activation_calls == 0
    assert poll_calls[0]["required_inference_profile"] == RequestedInferenceProfile(
        model_target_label="Quality",
        reasoning_effort=ModelReasoningEffort.HIGH,
    )
    assert poll_calls[0]["active_run_id"] == recoverable.id


@pytest.mark.asyncio
async def test_execute_persists_recovered_profile_resolution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recovered run keeps safe resolution failure details in provenance."""
    recoverable = _PendingRun(
        status=AgentRunStatus.RUNNING,
        resolved_model_selection=make_test_model_selection(),
        effective_context_window_tokens=64_000,
        effective_auto_compaction_threshold_tokens=51_200,
    )
    lifecycle = _SessionLifecycle(recoverable_run=recoverable)
    executor = _executor(session_lifecycle=lifecycle)

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=False,
        )

    async def fail_recovered_resolution(
        *args: object,
        **kwargs: object,
    ) -> object:
        del args, kwargs
        return Failure(AgentNotFound(agent_id="agent-001"))

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_resolved_profile",
        fail_recovered_resolution,
    )

    dispatched: list[PublishedEvent] = []

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
    )

    assert lifecycle.terminal_runs == [(recoverable.id, AgentRunStatus.FAILED)]
    assert result.terminal_run_status == AgentRunStatus.FAILED
    assert len(dispatched) == 2
    assert isinstance(dispatched[0], Event)
    assert isinstance(dispatched[1], RunComplete)


@pytest.mark.asyncio
async def test_execute_recovers_activated_command_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Command wake-ups reuse an already activated command run."""
    selection = make_test_model_selection()
    recoverable = _PendingRun(
        status=AgentRunStatus.RUNNING,
        resolved_model_selection=selection,
        effective_context_window_tokens=64_000,
        effective_auto_compaction_threshold_tokens=51_200,
    )
    lifecycle = _SessionLifecycle(recoverable_run=recoverable)
    command_handler = _CommandHandler([])
    executor = _executor(
        session_lifecycle=lifecycle,
        command_registry={"compact": cast(CommandHandler, command_handler)},
    )

    async def resolve_recovered(*args: object, **kwargs: object) -> object:
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
                auto_compaction_threshold_tokens=None,
            )
        )

    async def resolve_new(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("A recovered command must not create a new run")

    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_resolved_profile",
        resolve_recovered,
    )
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_profile",
        resolve_new,
    )
    monkeypatch.setattr(run_executor_module, "resolve_agent_tools", _resolve_no_tools)

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id, event

    result = await executor.execute(
        _message(),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        command=_pending_command(),
    )

    assert result.run_id == recoverable.id
    assert lifecycle.pending_run_create_calls == 0
    assert lifecycle.activation_calls == 0
    assert len(command_handler.requests) == 1
    assert command_handler.requests[0].effective_max_input_tokens == 64_000
    assert command_handler.requests[0].auto_compaction_threshold_tokens == 51_200


@pytest.mark.asyncio
async def test_execute_recovers_durable_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovered runs continue from the persisted retry attempt and backoff."""
    now = datetime.datetime.now(datetime.UTC)
    retry_state = FailedRunRetryState(
        failed_attempt_count=1,
        max_retries=2,
        last_user_message="temporary failure",
        last_error_type="ModelCallError",
        last_source="model",
        last_failed_at=now - datetime.timedelta(seconds=2),
        backoff_seconds=1,
        next_retry_at=now - datetime.timedelta(seconds=1),
    )
    recoverable = _PendingRun(
        status=AgentRunStatus.RUNNING,
        resolved_model_selection=make_test_model_selection(),
        effective_context_window_tokens=64_000,
        effective_auto_compaction_threshold_tokens=51_200,
        retry_state=retry_state,
    )
    lifecycle = _SessionLifecycle(recoverable_run=recoverable)
    finalizer = _FailedRunFinalizer()
    executor = _executor(
        session_lifecycle=lifecycle,
        engine=_AlwaysFailingEngine(),
        failed_run_finalizer=finalizer,
        failed_run_max_retries=2,
    )

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=False,
        )

    async def resolve_recovered(*args: object, **kwargs: object) -> object:
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
                auto_compaction_threshold_tokens=None,
            )
        )

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_resolved_profile",
        resolve_recovered,
    )
    monkeypatch.setattr(run_executor_module, "resolve_agent_tools", _resolve_no_tools)

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

    assert result.terminal_run_status == AgentRunStatus.FAILED
    assert len(finalizer.inputs) == 1
    assert finalizer.inputs[0].retry_state.failed_attempt_count == 2


@pytest.mark.asyncio
async def test_execute_claims_manual_retry_profile_before_flushing_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manual retry preserves requested intent and routes it again."""
    recoverable = _PendingRun(
        requested_model_target_label="Fast",
        requested_reasoning_effort=ModelReasoningEffort.LOW,
        inference_profile_source=InferenceProfileSource.RETRY_ORIGINAL,
    )
    lifecycle = _SessionLifecycle(recoverable_run=recoverable)
    retry_state = SessionInferenceState(
        model_target_label="Fast",
        model_selection=make_test_model_selection(),
        reasoning_effort=ModelReasoningEffort.LOW,
        effective_context_window_tokens=64_000,
        effective_auto_compaction_threshold_tokens=51_200,
        resolved_at=datetime.datetime.now(datetime.UTC),
    )
    executor = _executor(
        session_lifecycle=lifecycle,
        agent_session_repository=_AgentSessionRepository(inference_state=retry_state),
    )
    poll_calls: list[dict[str, object]] = []

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args
        poll_calls.append(kwargs)
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=["event-001"],
            user_messages=[],
            has_actionable_work=True,
        )

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    _patch_successful_resolution(monkeypatch)

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

    assert result.run_id == recoverable.id
    assert lifecycle.pending_run_create_calls == 0
    assert lifecycle.activation_calls == 1
    assert poll_calls[0]["required_inference_profile"] == RequestedInferenceProfile(
        model_target_label="Fast",
        reasoning_effort=ModelReasoningEffort.LOW,
    )
    assert poll_calls[0]["active_run_id"] == recoverable.id


@pytest.mark.asyncio
async def test_execute_activates_pending_child_from_session_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child first run activates the exact Session snapshot before use."""
    selection = make_test_model_selection()
    recoverable = _PendingRun(parent_agent_run_id="parent-run-001")
    inference_state = SessionInferenceState(
        model_target_label="Parent model",
        model_selection=selection,
        reasoning_effort=ModelReasoningEffort.HIGH,
        effective_context_window_tokens=64_000,
        effective_auto_compaction_threshold_tokens=51_200,
        resolved_at=datetime.datetime.now(datetime.UTC),
    )
    order: list[str] = []
    lifecycle = _SessionLifecycle(order, recoverable_run=recoverable)
    engine = _RecordingEngine(order)
    executor = _executor(
        session_lifecycle=lifecycle,
        engine=engine,
        agent_session_repository=_AgentSessionRepository(
            inference_state=inference_state
        ),
    )
    resolved_snapshots: list[AgentModelSelection] = []

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=["event-001"],
            user_messages=[],
            has_actionable_work=True,
        )

    async def resolve_existing(*args: object, **kwargs: object) -> object:
        del args
        resolved_snapshots.append(
            cast(AgentModelSelection, kwargs["resolved_model_selection"])
        )
        assert kwargs["resolved_reasoning_effort"] == ModelReasoningEffort.HIGH
        return await _resolve_existing_success()

    async def resolve_target(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("Prepared Session state must not route its label again")

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_resolved_profile",
        resolve_existing,
    )
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_profile",
        resolve_target,
    )
    monkeypatch.setattr(run_executor_module, "resolve_agent_tools", _resolve_no_tools)

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

    assert result.run_id == recoverable.id
    assert resolved_snapshots == [selection]
    assert lifecycle.activation_calls == 1
    assert order[:2] == ["activate_pending", "provider"]
    request = engine.requests[0]
    assert request.effective_max_input_tokens == 64_000
    assert request.context_window_tokens == 64_000
    assert request.compaction_max_input_tokens == 64_000
    assert request.auto_compaction_threshold_tokens == 51_200


@pytest.mark.asyncio
async def test_execute_enqueues_follow_up_after_context_invalidating_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Project-mutating actions stop before model dispatch and wake fresh context."""
    lifecycle = _SessionLifecycle()
    executor = _executor(session_lifecycle=lifecycle)
    message = _message()

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=False,
            context_invalidated=True,
        )

    async def resolve_failure(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("resolve_invoke_input should not be called")

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_profile",
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
async def test_boundary_poll_processes_turn_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model-call boundary polling processes TurnActions, not only messages."""
    executor = _executor()
    message = _message()
    process_actions_values: list[bool] = []

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args
        process_actions_values.append(cast(bool, kwargs["process_actions"]))
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=True,
        )

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)

    poll = executor.make_boundary_poll(
        message=message,
        model="gpt-test",
        requested_inference_profile=RequestedInferenceProfile(
            model_target_label="default",
            reasoning_effort=None,
        ),
        run_id="run-001",
        poll_fn=None,
        mark_context_invalidated=lambda: None,
    )

    assert await poll() == PollMessagesResult(
        user_messages=[],
        context_invalidated=False,
        complete_run=False,
    )
    assert process_actions_values == [True]


@pytest.mark.asyncio
async def test_boundary_poll_stops_after_context_invalidating_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Project-mutating TurnActions stop the current run and wake fresh context."""
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
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=False,
            context_invalidated=True,
        )

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        executor,
        "input_buffer_service",
        cast(InputBufferService, PendingInputBufferService()),
    )

    context_invalidated = False

    def mark_context_invalidated() -> None:
        nonlocal context_invalidated
        context_invalidated = True

    poll = executor.make_boundary_poll(
        message=message,
        model="gpt-test",
        requested_inference_profile=RequestedInferenceProfile(
            model_target_label="default",
            reasoning_effort=None,
        ),
        run_id="run-001",
        poll_fn=None,
        mark_context_invalidated=mark_context_invalidated,
    )

    assert await poll() == PollMessagesResult(
        complete_run=False,
        user_messages=[],
        context_invalidated=True,
    )
    assert context_invalidated is True
    assert lifecycle.wake_ups == [message]


@pytest.mark.asyncio
async def test_poll_run_inputs_continues_fifo_after_failed_turn_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed TurnActions are marked failed and the next FIFO input is promoted."""
    executor = _executor()
    user_message = make_run_user_message(
        content="continue after failed action",
        metadata={},
        attachments=[],
        external_id="buffer-user",
        attachment_source="input_buffer",
    )
    promoted_batches = [
        PromotedInputBuffers(
            worktree_action=None,
            turn_effect=TurnEffect.FAILED,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            events=[],
            deleted_buffer_ids=["buffer-action"],
            claimed_count=1,
            inserted_count=0,
            deduped_count=0,
        ),
        PromotedInputBuffers(
            worktree_action=None,
            turn_effect=TurnEffect.ELIGIBLE,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[user_message],
            events=[
                Event(
                    id="1123456789abcdef0123456789abcdf1",
                    session_id="session-1",
                    kind=EventKind.USER_MESSAGE,
                    payload=user_message.payload,
                    created_at=run_executor_module.tznow(),
                )
            ],
            deleted_buffer_ids=["buffer-user"],
            claimed_count=1,
            inserted_count=1,
            deduped_count=0,
        ),
        PromotedInputBuffers(
            worktree_action=None,
            turn_effect=TurnEffect.NEUTRAL,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            events=[],
            deleted_buffer_ids=[],
            claimed_count=0,
            inserted_count=0,
            deduped_count=0,
        ),
    ]
    processed_worktree_actions: list[object | None] = []

    async def promote(*args: object, **kwargs: object) -> PromotedInputBuffers:
        del args, kwargs
        return promoted_batches.pop(0)

    async def process_operation_actions(
        *args: object,
        **kwargs: object,
    ) -> OperationActionProcessResult:
        del args
        processed_worktree_actions.append(kwargs["worktree_action"])
        return OperationActionProcessResult(context_invalidated=False)

    async def has_actionable_model_input(session_id: str) -> bool:
        del session_id
        return False

    monkeypatch.setattr(executor, "_promote_input_buffers", promote)
    monkeypatch.setattr(
        executor,
        "_process_operation_actions",
        process_operation_actions,
    )
    monkeypatch.setattr(
        executor,
        "_has_actionable_model_input",
        has_actionable_model_input,
    )

    result = await executor.poll_run_inputs(
        agent_id="agent-1",
        session_id="session-1",
        model="gpt-test",
        required_inference_profile=None,
        active_run_id=None,
        initial_turn_eligible=False,
        poll_fn=None,
        process_actions=True,
    )

    assert result.user_messages == [user_message]
    assert result.has_actionable_work is True
    assert result.context_invalidated is False
    assert result.complete_run is False
    assert processed_worktree_actions == [None, None]
    assert promoted_batches == []


@pytest.mark.asyncio
async def test_poll_run_inputs_completes_run_after_terminal_preparation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A handled preparation failure completes the active run without retry."""
    executor = _executor()
    promoted_batches = [
        PromotedInputBuffers(
            worktree_action=None,
            turn_effect=TurnEffect.FAILED,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            events=[],
            deleted_buffer_ids=["buffer-failed"],
            claimed_count=1,
            inserted_count=1,
            deduped_count=0,
        ),
        PromotedInputBuffers(
            worktree_action=None,
            turn_effect=TurnEffect.NEUTRAL,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            events=[],
            deleted_buffer_ids=[],
            claimed_count=0,
            inserted_count=0,
            deduped_count=0,
        ),
    ]

    async def promote(*args: object, **kwargs: object) -> PromotedInputBuffers:
        del args, kwargs
        return promoted_batches.pop(0)

    async def has_actionable_model_input(session_id: str) -> bool:
        del session_id
        return False

    monkeypatch.setattr(executor, "_promote_input_buffers", promote)
    monkeypatch.setattr(
        executor,
        "_has_actionable_model_input",
        has_actionable_model_input,
    )

    result = await executor.poll_run_inputs(
        agent_id="agent-1",
        session_id="session-1",
        model="gpt-test",
        required_inference_profile=None,
        active_run_id="run-1",
        initial_turn_eligible=False,
        poll_fn=None,
        process_actions=False,
    )

    assert result.complete_run is True
    assert result.has_actionable_work is False
    assert result.context_invalidated is False
    assert promoted_batches == []


@pytest.mark.asyncio
async def test_execute_ignores_wake_up_without_runtime_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wake-up with no durable work does not start the engine path."""
    dispatched: list[PublishedEvent] = []
    executor = _executor()

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=False,
        )

    async def resolve_failure(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("resolve_invoke_input should not be called")

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_profile",
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
    dispatched: list[tuple[str, PublishedEvent]] = []
    live_event_projector = _LiveEventProjector()
    session_repository = _AgentSessionRepository(
        current_session_agent=SimpleNamespace(
            id="child-session-agent",
            root_session_agent_id="root-session-agent",
        ),
        tree_session_agents=[
            SimpleNamespace(agent_session_id="session-001"),
            SimpleNamespace(agent_session_id="parent-session"),
            SimpleNamespace(agent_session_id="root-session"),
        ],
    )
    executor = _executor(
        _SessionLifecycle(order),
        agent_session_repository=session_repository,
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
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=True,
        )

    async def resolve_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return await _resolve_success()

    async def resolve_agent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_profile",
        resolve_success,
    )
    monkeypatch.setattr(
        run_executor_module,
        "resolve_agent_tools",
        resolve_agent_tools_success,
    )

    async def dispatch_event(
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        dispatched.append((session_id, event))

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
    assert any(isinstance(event, RunComplete) for _, event in dispatched)
    tree_changes = [
        (session_id, event)
        for session_id, event in dispatched
        if isinstance(event, SubagentTreeChanged)
    ]
    assert [session_id for session_id, _ in tree_changes] == [
        "session-001",
        "parent-session",
        "root-session",
        "session-001",
        "parent-session",
        "root-session",
    ]
    assert all(
        event.changed_session_agent_id == "child-session-agent"
        for _, event in tree_changes
    )
    assert order == ["activate_pending", "clear_session_activity"]
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
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=True,
        )

    async def resolve_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return await _resolve_success()

    async def resolve_agent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module, "resolve_invoke_input_with_profile", resolve_success
    )
    monkeypatch.setattr(
        run_executor_module, "resolve_agent_tools", resolve_agent_tools_success
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
    assert live_event_projector.live_run_updates[-1][1].retry is None
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
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=True,
        )

    async def resolve_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return await _resolve_success()

    async def resolve_agent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module, "resolve_invoke_input_with_profile", resolve_success
    )
    monkeypatch.setattr(
        run_executor_module, "resolve_agent_tools", resolve_agent_tools_success
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
    assert all(
        run.inference_profile
        == AppliedInferenceProfile(
            model_target_label="default",
            reasoning_effort=None,
        )
        for _, run in live_event_projector.live_run_updates
    )
    latest_live_run = live_event_projector.live_run_updates[-1][1]
    assert latest_live_run.retry is None
    wire_event = chat_live_run_updated_dump("session-001", latest_live_run)
    wire_run = wire_event["run"]
    assert isinstance(wire_run, dict)
    assert wire_run["inference_profile"] == {
        "model_target_label": "default",
        "reasoning_effort": None,
    }


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
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=True,
        )

    async def resolve_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return await _resolve_success()

    async def resolve_agent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module, "resolve_invoke_input_with_profile", resolve_success
    )
    monkeypatch.setattr(
        run_executor_module, "resolve_agent_tools", resolve_agent_tools_success
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
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=True,
        )

    async def resolve_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return await _resolve_success()

    async def resolve_agent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module, "resolve_invoke_input_with_profile", resolve_success
    )
    monkeypatch.setattr(
        run_executor_module, "resolve_agent_tools", resolve_agent_tools_success
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
async def test_execute_preserves_retry_attempt_history_after_live_retry_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clearing retry projection before retrying preserves local attempt history."""
    monkeypatch.setattr(run_executor_module, "_FAILED_RUN_RETRY_WAIT_POLL_SECONDS", 0)
    _patch_successful_resolution(monkeypatch)
    lifecycle = _SessionLifecycle()
    engine = _AlwaysFailingEngine()
    finalizer = _FailedRunFinalizer()
    executor = _executor(
        lifecycle,
        engine=cast(AgentEngineProtocol, engine),
        failed_run_finalizer=finalizer,
        failed_run_max_retries=2,
    )

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=True,
        )

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)

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
    assert result.terminal_run_status == AgentRunStatus.FAILED
    assert len(lifecycle.retry_states) == 2
    final_retry_state = lifecycle.retry_states[1]
    assert final_retry_state is not None
    assert final_retry_state.failed_attempt_count == 2
    assert [attempt.attempt_number for attempt in final_retry_state.attempts] == [1, 2]
    assert len(finalizer.inputs) == 1
    assert [
        attempt.attempt_number for attempt in finalizer.inputs[0].retry_state.attempts
    ] == [1, 2]


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
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=True,
        )

    async def resolve_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return await _resolve_success()

    async def resolve_agent_tools_success(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return []

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module, "resolve_invoke_input_with_profile", resolve_success
    )
    monkeypatch.setattr(
        run_executor_module, "resolve_agent_tools", resolve_agent_tools_success
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
