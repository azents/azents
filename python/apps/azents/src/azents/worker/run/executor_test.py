"""RunExecutor tests."""

import asyncio
import contextlib
import dataclasses
import datetime
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

import azents.worker.run.executor as run_executor_module
from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.types import PublishedEvent, SessionBroker, SessionWakeUp
from azents.core.agent import AgentModelSelection
from azents.core.enums import (
    ActionExecutionStatus,
    AgentLifecycleStatus,
    AgentRunPhase,
    AgentRunStatus,
    AgentRuntimeCapability,
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentType,
    EventKind,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    InferenceProfileFailureCode,
    InferenceProfileSource,
    RequestedInferenceProfile,
    SessionAppliedInferenceProfile,
    SessionInferenceState,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.runtime_capabilities import (
    RuntimeCapability,
    RuntimeCapabilityResolver,
)
from azents.core.tools import ToolkitContext, ToolkitExecutionMode, ToolkitProvider
from azents.core.vfs import VfsProjection, make_vfs_projection
from azents.engine.events.action_messages import (
    AgentCreateGitWorktreeAction,
    AgentRemoveGitWorktreeAction,
    CreateGitWorktreeAction,
)
from azents.engine.events.engine_events import (
    RunComplete,
    RunPhaseChanged,
    RunStopped,
    SubagentTreeChanged,
)
from azents.engine.events.types import (
    ActiveToolCall,
    AgentRunState,
    AssistantMessagePayload,
    Event,
    ExternalChannelMessagePayload,
    NativeArtifact,
    RunMarkerPayload,
    SystemErrorPayload,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.engine.events.user_messages import make_run_user_message
from azents.engine.run.commands import CommandHandler
from azents.engine.run.contracts import (
    AgentEngineProtocol,
    RunContext,
    RunRequest,
    ToolkitBinding,
)
from azents.engine.run.emit import Emit, durable, ephemeral
from azents.engine.run.errors import (
    CompactionModelStreamTimeoutError,
    ModelCallError,
    ModelStreamTimeoutError,
    NonRetryableModelCallError,
    TransientModelCallError,
    UserVisibleRuntimeError,
)
from azents.engine.run.failure import FailedRunRetryState
from azents.engine.run.input import AgentNotFound, InvokeInput
from azents.engine.run.model_transport import InMemoryModelTransportState
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    model_provider_failure,
)
from azents.engine.run.resolve import (
    ModelTargetNotFound,
    ReasoningEffortUnsupported,
    ResolvedInvokeInputProfile,
)
from azents.engine.run.retry_policy import FailedRunRetryPolicy
from azents.engine.run.turn_action_bridge import TurnActionBridgeBoundary
from azents.engine.run.types import (
    SHUTDOWN_CANCEL_MESSAGE,
    USER_STOP_CANCEL_MESSAGE,
    PollMessages,
    PollMessagesResult,
)
from azents.engine.tools.builtin import BuiltinToolkitProvider
from azents.engine.tools.claude_rules import ClaudeRulesToolkitProvider
from azents.engine.tools.dynamic_worktree import (
    DynamicWorktreeToolkit,
    DynamicWorktreeToolkitProvider,
)
from azents.engine.tools.external_channel import ExternalChannelToolkitProvider
from azents.engine.tools.goal import GoalToolkitProvider
from azents.engine.tools.scheduled import ScheduledToolkitProvider
from azents.engine.tools.skill import SkillToolkitProvider
from azents.engine.tools.subagent import SubagentToolkitProvider
from azents.engine.tools.todo import TodoToolkitProvider
from azents.rdb.session import SessionManager
from azents.repos.action_execution.data import ActionExecution
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, PendingSessionCommand
from azents.repos.external_channel.data import ExternalChannelMailboxProjectionItem
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.mailbox.data import MailboxItem
from azents.repos.toolkit import AgentToolkitRepository, ToolkitRepository
from azents.services.chat.data import ChatLiveRunState
from azents.services.exchange_file import ExchangeFileService
from azents.services.mailbox import (
    ExternalChannelMessageMailboxProcessor,
    MailboxPreparationContext,
    MailboxService,
    PendingInputInferenceProfile,
    PreparedMailboxFiles,
    PromotedMailboxItems,
    ScheduledMailboxAdmission,
    TurnEffect,
    build_external_channel_mailbox_payload,
)
from azents.services.model_file import ModelFileService
from azents.services.session_git_worktree import (
    GitWorktreeActionExecutionResult,
    SessionGitWorktreeService,
)
from azents.services.session_title import SessionTitleService
from azents.services.turn_action import TurnActionCapabilityRegistry
from azents.services.vfs import VfsProjectionService
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
    make_test_selectable_model_options,
)
from azents.testing.types import is_string_object_dict
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
from azents.worker.run.turn_action_executor import OperationActionExecutorRegistry
from azents.worker.session.execution_snapshot import (
    CanonicalExecutionOwnerGenerationStaleError,
    CanonicalExecutionSnapshot,
    CanonicalExecutionWorkDriftError,
    PendingCommandSnapshot,
)
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.supervisor import ToolAdmissionBarrier
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


async def _noop_dispatch_event(
    session_id: str,
    event: PublishedEvent,
) -> None:
    """Ignore a published worker event."""
    del session_id, event


class _VfsProjectionService:
    """Run VFS projection service test double."""

    def __init__(self, order: list[str] | None = None) -> None:
        self.order = order
        self.calls: list[tuple[str, str, str, str]] = []

    async def ensure_run_projection(
        self,
        *,
        run_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str,
        execution_mode: ToolkitExecutionMode,
    ) -> VfsProjection:
        """Record projection admission before input promotion."""
        del execution_mode
        if self.order is not None:
            self.order.append("vfs")
        self.calls.append((run_id, agent_id, session_id, workspace_id))
        return make_vfs_projection([])


@dataclasses.dataclass(frozen=True)
class _PendingRun:
    """Minimal pending-run projection for executor tests."""

    id: str = "run-001"
    run_index: int = 1
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
    model_call_started_at: datetime.datetime | None = None
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
        self.second_heartbeat = asyncio.Event()
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
        self.activation_phases: list[AgentRunPhase] = []
        self.activation_profiles: list[RequestedInferenceProfile] = []
        self.inherited_activation_calls = 0
        self.cancelled_pending_run_ids: list[str] = []
        self.completed_bridge_predecessors: list[str] = []
        self.cleared_commands: list[tuple[str, str]] = []

    async def set_session_activity(
        self,
        session_id: str,
        *,
        run_id: str,
        phase: object,
    ) -> None:
        """Record session activity updates."""
        self.activities.append((session_id, run_id, phase))

    async def clear_session_activity(self, session_id: str) -> None:
        """Record session activity cleanup."""
        self.cleared_session_ids.append(session_id)
        if self.order is not None:
            self.order.append("clear_session_activity")

    async def mark_session_idle(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> bool:
        """Record session idle transitions."""
        del owner_generation
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
        owner_generation: int,
        run_id: str,
        status: object,
    ) -> None:
        """Record terminal run updates."""
        del session_id, owner_generation
        self.terminal_runs.append((run_id, cast(AgentRunStatus, status)))

    async def update_agent_run_retry_state(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
        retry_state: FailedRunRetryState | None,
    ) -> None:
        """Record retry-state updates."""
        del session_id, owner_generation, run_id
        self.retry_states.append(retry_state)

    async def heartbeat_session(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> None:
        """Record the session id passed to heartbeat."""
        del owner_generation
        self.heartbeat_session_ids.append(session_id)
        if len(self.heartbeat_session_ids) == 2:
            self.second_heartbeat.set()

    async def get_running_agent_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> _PendingRun | None:
        """Return the configured Run only when it is active."""
        del session_id, owner_generation
        if (
            self.recoverable_run is not None
            and self.recoverable_run.status == AgentRunStatus.RUNNING
        ):
            return self.recoverable_run
        return None

    async def get_active_agent_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> _PendingRun | None:
        """Return the configured pending or running Run without claiming it."""
        del session_id, owner_generation
        return self.recoverable_run

    async def claim_recoverable_agent_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> _PendingRun | None:
        """Return the configured recoverable run."""
        del session_id, owner_generation
        return self.recoverable_run

    async def create_pending_agent_run(
        self,
        session_id: str,
        **kwargs: object,
    ) -> _PendingRun:
        """Return one stable pending run for execution tests."""
        del session_id, kwargs
        self.pending_run_create_calls += 1
        return _PendingRun()

    async def claim_lifecycle_start(
        self,
        session_id: str,
        **kwargs: object,
    ) -> bool:
        """Pretend the Session-start hook was already claimed."""
        del session_id, kwargs
        return False

    async def cancel_pending_agent_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
    ) -> _PendingRun:
        """Record cancellation of a new pending run with no model work."""
        del session_id, owner_generation
        self.cancelled_pending_run_ids.append(run_id)
        return _PendingRun(status=AgentRunStatus.CANCELLED)

    async def complete_bridge_predecessor_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
    ) -> AgentRunStatus:
        """Record one bridge predecessor terminalization boundary."""
        del session_id, owner_generation
        self.completed_bridge_predecessors.append(run_id)
        if self.recoverable_run is None:
            raise AssertionError("Bridge predecessor Run was not configured")
        if self.recoverable_run.status is AgentRunStatus.PENDING:
            return AgentRunStatus.CANCELLED
        if self.recoverable_run.status is AgentRunStatus.RUNNING:
            return AgentRunStatus.COMPLETED
        raise AssertionError("Bridge predecessor Run is not active")

    async def activate_pending_agent_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
        initial_phase: AgentRunPhase,
        requested_profile: RequestedInferenceProfile,
    ) -> _PendingRun:
        """Accept activation before provider invocation."""
        del session_id, owner_generation, run_id
        self.activation_calls += 1
        self.activation_phases.append(initial_phase)
        self.activation_profiles.append(requested_profile)
        if self.order is not None:
            self.order.append("activate_pending")
        return _PendingRun(
            status=AgentRunStatus.RUNNING,
            phase=initial_phase,
        )

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

    async def validate_pending_command(
        self,
        session_id: str,
        **kwargs: object,
    ) -> None:
        """Accept exact pending-command validation."""
        del session_id, kwargs

    async def clear_pending_command(
        self,
        session_id: str,
        **kwargs: object,
    ) -> None:
        """Accept fenced pending-command cleanup."""
        self.cleared_commands.append((session_id, cast(str, kwargs["command_id"])))

    async def set_inference_state(
        self,
        session_id: str,
        **kwargs: object,
    ) -> None:
        """Accept fenced inference-state persistence."""
        del session_id, kwargs

    async def list_inference_run_event_projections(
        self,
        *,
        run_id: str,
    ) -> list[object]:
        """Return no durable projections for lightweight executor tests."""
        del run_id
        return []


def _default_agent() -> Agent:
    """Create a typed Agent fixture for execution tests."""
    now = datetime.datetime.now(datetime.UTC)
    selection = make_test_model_selection()
    fast_selection = selection
    planning_selection = selection
    return Agent(
        id="agent-001",
        workspace_id="workspace-001",
        name="Executor test Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=[
            *make_test_selectable_model_options(selection),
            *make_test_selectable_model_options(fast_selection, label="fast"),
            *make_test_selectable_model_options(
                planning_selection,
                label="planning",
            ),
        ],
        main_model_label="default",
        lightweight_model_label="default",
        enabled=True,
        external_channel_default_response_mode=ExternalChannelResponseMode.MENTION_ONLY,
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
        type=AgentType.PUBLIC,
        runtime_profile_id=None,
        runtime_profile_selection_version=1,
        runtime_capability=AgentRuntimeCapability.NONE,
        runtime_capability_version=1,
        tool_search_enabled=True,
        auto_archive_ttl_days=30,
        created_at=now,
        updated_at=now,
    )


def _default_agent_session(
    *,
    inference_state: SessionInferenceState | None,
    applied_inference_profile: SessionAppliedInferenceProfile | None = None,
    owner_generation: int = 1,
) -> AgentSession:
    """Create a typed AgentSession fixture for execution tests."""
    now = datetime.datetime.now(datetime.UTC)
    return AgentSession(
        id="session-001",
        workspace_id="workspace-001",
        agent_id="agent-001",
        handle="executor-test-session",
        inference_state=inference_state,
        applied_inference_profile=applied_inference_profile,
        session_kind=AgentSessionKind.ROOT,
        status=AgentSessionStatus.ACTIVE,
        product_mode=AgentSessionProductMode.TEAM,
        associated_user_id=None,
        start_reason=AgentSessionStartReason.INITIAL,
        title=None,
        title_source=None,
        title_generated_at=None,
        title_generation_event_id=None,
        last_user_input_at=now,
        last_activity_at=now,
        pinned=False,
        started_at=now,
        owner_generation=owner_generation,
        created_at=now,
        updated_at=now,
    )


class _AgentRepository:
    """AgentRepository test double."""

    def __init__(
        self,
        agent: object | None = None,
        *,
        default_if_none: bool = True,
    ) -> None:
        self.agent = _default_agent() if agent is None and default_if_none else agent

    async def get_by_id(self, session: AsyncSession, agent_id: str) -> object | None:
        """Return the configured persisted Agent settings."""
        del session, agent_id
        return self.agent

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> object | None:
        """Return the configured Agent under the final preparation fence."""
        del session, agent_id
        return self.agent


class _AgentSessionRepository:
    """AgentSessionRepository test double."""

    def __init__(
        self,
        *,
        inference_state: SessionInferenceState | None = None,
        current_session_agent: object | None = None,
        tree_session_agents: list[object] | None = None,
        owner_generation: int = 1,
    ) -> None:
        self.inference_state = inference_state
        self.owner_generation = owner_generation
        self.applied_inference_profile: SessionAppliedInferenceProfile | None = None
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
        return _default_agent_session(
            inference_state=self.inference_state,
            applied_inference_profile=self.applied_inference_profile,
            owner_generation=self.owner_generation,
        )

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession:
        """Return the configured Session under the final preparation fence."""
        del session, agent_session_id
        return _default_agent_session(
            inference_state=self.inference_state,
            applied_inference_profile=self.applied_inference_profile,
            owner_generation=self.owner_generation,
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

    async def get_session_agent_by_id(
        self,
        session: AsyncSession,
        session_agent_id: str,
    ) -> object | None:
        """Return a configured SessionAgent by ID."""
        del session
        candidates = [self.current_session_agent, *self.tree_session_agents]
        return next(
            (
                candidate
                for candidate in candidates
                if candidate is not None
                and getattr(candidate, "id", None) == session_agent_id
            ),
            None,
        )

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


class _MailboxService:
    """MailboxService test double."""

    def __init__(
        self,
        scheduled_admission: ScheduledMailboxAdmission | None,
        mailbox_item_id: str,
    ) -> None:
        self.scheduled_admission = scheduled_admission
        self.mailbox_item_id = mailbox_item_id
        self.scheduled_admission_calls: list[tuple[str, int, str | None]] = []

    async def admit_scheduled_mailbox_head(
        self,
        *,
        session_id: str,
        owner_generation: int,
        expected_buffer_id: str | None,
    ) -> ScheduledMailboxAdmission | None:
        """Return the configured Scheduled admission result."""
        self.scheduled_admission_calls.append(
            (session_id, owner_generation, expected_buffer_id)
        )
        return self.scheduled_admission

    async def peek_pending_inference_profile(
        self,
        session_id: str,
    ) -> PendingInputInferenceProfile:
        """Return one implicit pending input by default."""
        del session_id
        return PendingInputInferenceProfile(
            mailbox_item_id=self.mailbox_item_id,
            requires_inference=True,
            exists=True,
            requested_inference_profile=None,
        )

    async def has_pending_session_mailbox_items(self, session_id: str) -> bool:
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
        self.discarded_session_ids: list[str] = []
        self.projection_operations: list[str] = []
        self.active_tool_calls: list[tuple[str, object]] = []
        self.live_run_updates: list[tuple[str, ChatLiveRunState]] = []
        self.live_run_clears: list[tuple[str, str]] = []

    async def publish_live_run_updated(
        self,
        session_id: str,
        run: ChatLiveRunState,
    ) -> None:
        """Record live run update broadcasts."""
        self.live_run_updates.append((session_id, run))
        if run.retry is not None:
            self.projection_operations.append("retry_update")

    async def publish_live_run_cleared(
        self,
        session_id: str,
        *,
        run_id: str,
    ) -> None:
        """Record live run clear broadcasts."""
        self.live_run_clears.append((session_id, run_id))

    async def replace_active_tool_calls(
        self,
        session_id: str,
        active_tool_calls: object,
        *,
        removed_call_ids: set[str],
    ) -> None:
        """Record active tool call projection replacements."""
        del removed_call_ids
        self.active_tool_calls.append((session_id, active_tool_calls))

    async def flush_session(self, session_id: str) -> None:
        """Record flushed sessions."""
        self.flushed_session_ids.append(session_id)

    async def discard_failed_attempt(self, session_id: str) -> None:
        """Record failed-attempt model partial discard."""
        self.discarded_session_ids.append(session_id)
        self.projection_operations.append("discard")


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
        del request, poll_messages, check_stop
        assert isinstance(context, RunContext)

        async def iterator() -> AsyncIterator[Emit]:
            yield ephemeral(RunComplete(run_id=context.run_id))

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


class _BoundarySwitchEngine(_Engine):
    """Engine that returns control once for a turn-boundary profile switch."""

    def __init__(self) -> None:
        self.requests: list[RunRequest] = []

    def run(
        self,
        request: RunRequest,
        context: object,
        *,
        poll_messages: object = None,
        check_stop: object = None,
    ) -> AsyncIterator[Emit]:
        """Poll the first boundary, then complete the rebuilt request."""
        del check_stop
        assert isinstance(context, RunContext)
        self.requests.append(request)

        async def iterator() -> AsyncIterator[Emit]:
            if len(self.requests) == 1:
                poll = cast(PollMessages, poll_messages)
                poll_result = await poll()
                assert poll_result.context_invalidated is True
                return
            yield ephemeral(RunComplete(run_id=context.run_id))

        return iterator()


class _FlakyEngine(_Engine):
    """Engine that fails once and then completes."""

    def __init__(self, error: ModelCallError | None = None) -> None:
        self.calls = 0
        self.error = error or ModelCallError("model temporarily unavailable")

    def run(
        self,
        request: RunRequest,
        context: object,
        *,
        poll_messages: object = None,
        check_stop: object = None,
    ) -> AsyncIterator[Emit]:
        """Fail the first attempt and complete the second."""
        del request, poll_messages, check_stop
        assert isinstance(context, RunContext)

        async def iterator() -> AsyncIterator[Emit]:
            self.calls += 1
            if self.calls == 1:
                yield ephemeral(
                    RunPhaseChanged(
                        run_id=context.run_id,
                        phase=AgentRunPhase.WAITING_FOR_MODEL,
                        model_call_started_at=datetime.datetime.now(datetime.UTC),
                    )
                )
                raise self.error
            yield ephemeral(RunComplete(run_id=context.run_id))

        return iterator()


def _successful_model_output_event() -> Event:
    """Create committed model output without a usage turn marker."""
    native_artifact = NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="litellm",
            native_format="responses",
            provider="openai",
            model="gpt-4o",
            schema_version="1",
        ),
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-4o",
        schema_version="1",
        item={"type": "message"},
    )
    return Event(
        id="0" * 32,
        session_id="session-001",
        kind=EventKind.ASSISTANT_MESSAGE,
        payload=AssistantMessagePayload(
            content="first turn recovered",
            native_artifact=native_artifact,
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )


class _RetryAcrossTurnsEngine(_Engine):
    """Engine that fails once in each of two model turns."""

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
        """Recover turn one, cross its output boundary, then fail turn two."""
        del request, poll_messages, check_stop
        assert isinstance(context, RunContext)

        async def iterator() -> AsyncIterator[Emit]:
            self.calls += 1
            if self.calls == 1:
                raise ModelCallError("first turn temporarily unavailable")
            if self.calls == 2:
                yield durable(_successful_model_output_event())
                raise ModelCallError("second turn temporarily unavailable")
            yield ephemeral(RunComplete(run_id=context.run_id))

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
        del request, poll_messages, check_stop
        assert isinstance(context, RunContext)

        async def iterator() -> AsyncIterator[Emit]:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("database temporarily unavailable")
            yield ephemeral(RunComplete(run_id=context.run_id))

        return iterator()


class _SyntheticTransientModelCallError(TransientModelCallError):
    """Safe transient model failure used to verify retry persistence."""

    failure_code = "synthetic_transport_failure"


class _SyntheticNonRetryableModelCallError(NonRetryableModelCallError):
    """Safe deterministic model failure used to verify immediate finalization."""

    failure_code = "synthetic_invalid_request"


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


class _AlwaysProviderFailingEngine(_Engine):
    """Engine that always raises one typed provider failure."""

    def __init__(self, failure: ModelProviderFailure) -> None:
        self.calls = 0
        self.failure = failure

    def run(
        self,
        request: RunRequest,
        context: object,
        *,
        poll_messages: object = None,
        check_stop: object = None,
    ) -> AsyncIterator[Emit]:
        """Raise the configured provider failure for every attempt."""
        del request, context, poll_messages, check_stop

        async def iterator() -> AsyncIterator[Emit]:
            self.calls += 1
            raise self.failure
            yield  # pragma: no cover

        return iterator()


class _ProviderFailThenStopEngine(_Engine):
    """Engine that fails once and emits terminal Stop on the retry."""

    def __init__(self, failure: ModelProviderFailure) -> None:
        self.calls = 0
        self.failure = failure

    def run(
        self,
        request: RunRequest,
        context: object,
        *,
        poll_messages: object = None,
        check_stop: object = None,
    ) -> AsyncIterator[Emit]:
        """Fail the first attempt and stop the next attempt."""
        del request, poll_messages, check_stop
        assert isinstance(context, RunContext)

        async def iterator() -> AsyncIterator[Emit]:
            self.calls += 1
            if self.calls == 1:
                raise self.failure
            yield ephemeral(RunStopped(run_id=context.run_id))

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

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error or UserVisibleRuntimeError("command failed")

    async def execute(
        self,
        engine: AgentEngineProtocol,
        request: RunRequest,
        context: RunContext,
    ) -> AsyncIterator[Emit]:
        """Fail command execution."""
        del engine, request, context
        raise self.error
        yield  # pragma: no cover


class _SessionGitWorktreeService:
    """Worktree operation service test double."""

    def __init__(self) -> None:
        self.reconciled_session_ids: list[str] = []
        self.reconciled_predecessor_run_ids: list[str | None] = []
        self.cancelled_execution_ids: list[str] = []
        self.executed_execution_ids: list[str] = []
        self.executed_predecessor_run_ids: list[str] = []

    async def cancel_live_action_executions(
        self,
        *,
        session_id: str,
        reason: str,
        on_history_event_appended: object,
        on_action_execution_removed: object,
        predecessor_run_id: str | None = None,
    ) -> list[Event]:
        """Record stale-operation reconciliation."""
        del (
            reason,
            on_history_event_appended,
            on_action_execution_removed,
        )
        self.reconciled_session_ids.append(session_id)
        self.reconciled_predecessor_run_ids.append(predecessor_run_id)
        return []

    async def cancel_action_execution(
        self,
        *,
        execution: ActionExecution,
        reason: str,
        on_history_event_appended: object,
        predecessor_run_id: str | None,
    ) -> None:
        """Record one operation cancellation."""
        del reason, on_history_event_appended, predecessor_run_id
        self.cancelled_execution_ids.append(execution.id)

    async def run_git_worktree_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        action: CreateGitWorktreeAction,
        owner_generation: int,
        on_projection_updated: object,
        on_history_event_appended: object,
    ) -> GitWorktreeActionExecutionResult:
        """Record one admitted operation."""
        del (
            agent_id,
            session_id,
            action,
            owner_generation,
            on_projection_updated,
            on_history_event_appended,
        )
        self.executed_execution_ids.append(execution.id)
        return GitWorktreeActionExecutionResult(
            completed=True,
            context_invalidated=True,
            complete_run=False,
        )

    async def run_agent_create_git_worktree_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        action: AgentCreateGitWorktreeAction,
        owner_generation: int,
        predecessor_run_id: str,
        on_projection_updated: object,
        on_history_event_appended: object,
    ) -> GitWorktreeActionExecutionResult:
        """Record one admitted Agent bridge operation."""
        del (
            agent_id,
            session_id,
            action,
            owner_generation,
            on_projection_updated,
            on_history_event_appended,
        )
        self.executed_execution_ids.append(execution.id)
        self.executed_predecessor_run_ids.append(predecessor_run_id)
        return GitWorktreeActionExecutionResult(
            completed=True,
            context_invalidated=False,
            complete_run=True,
        )

    async def run_agent_remove_git_worktree_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        action: AgentRemoveGitWorktreeAction,
        owner_generation: int,
        predecessor_run_id: str,
        on_projection_updated: object,
        on_history_event_appended: object,
    ) -> GitWorktreeActionExecutionResult:
        """Record one admitted Agent removal bridge operation."""
        del (
            agent_id,
            session_id,
            action,
            owner_generation,
            on_projection_updated,
            on_history_event_appended,
        )
        self.executed_execution_ids.append(execution.id)
        self.executed_predecessor_run_ids.append(predecessor_run_id)
        return GitWorktreeActionExecutionResult(
            completed=True,
            context_invalidated=False,
            complete_run=True,
        )


class _FailedRunFinalizer:
    """Failed-run finalizer test double."""

    def __init__(self, *, claimed: bool = True) -> None:
        self.inputs: list[FailedRunFinalizationInput] = []
        self.claimed = claimed

    async def finalize(
        self,
        input: FailedRunFinalizationInput,
        *,
        dispatch_event: object,
    ) -> object | None:
        """Record finalization input."""
        del dispatch_event
        self.inputs.append(input)
        return object() if self.claimed else None


class _UserStopFinalizer:
    """User-stop finalizer test double."""

    def __init__(self) -> None:
        self.interrupted_runs: list[tuple[str, str]] = []
        self.parent_result_activity_run_ids: list[str] = []

    async def record_interrupted_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
    ) -> None:
        """Record one recoverable stopped Run."""
        del owner_generation
        self.interrupted_runs.append((session_id, run_id))


def _executor(
    session_lifecycle: _SessionLifecycle | None = None,
    *,
    engine: AgentEngineProtocol | None = None,
    agent: object | None = None,
    failed_run_finalizer: object | None = None,
    user_stop_finalizer: _UserStopFinalizer | None = None,
    command_registry: dict[str, CommandHandler] | None = None,
    agent_session_repository: _AgentSessionRepository | None = None,
    live_event_projector: _LiveEventProjector | None = None,
    mailbox_item_service: _MailboxService | None = None,
    session_git_worktree_service: _SessionGitWorktreeService | None = None,
    vfs_projection_service: _VfsProjectionService | None = None,
    failed_run_max_retries: int = 10,
) -> RunExecutor:
    """Create a RunExecutor for resolve-failure tests."""
    if session_lifecycle is None:
        session_lifecycle = _SessionLifecycle()
    if engine is None:
        engine = cast(AgentEngineProtocol, _Engine())
    if failed_run_finalizer is None:
        failed_run_finalizer = _FailedRunFinalizer()
    if user_stop_finalizer is None:
        user_stop_finalizer = _UserStopFinalizer()
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
                model_settings=make_test_model_settings(),
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
    if mailbox_item_service is None:
        mailbox_item_service = _MailboxService(
            scheduled_admission=None,
            mailbox_item_id="buffer-1",
        )
    if session_git_worktree_service is None:
        session_git_worktree_service = _SessionGitWorktreeService()
    if vfs_projection_service is None:
        vfs_projection_service = _VfsProjectionService()
    return RunExecutor(
        broker=cast(SessionBroker, object()),
        session_manager=cast(SessionManager[AsyncSession], _SessionManager()),
        engine=engine,
        agent_repository=cast(AgentRepository, _AgentRepository(agent)),
        command_registry=command_registry,
        integration_repository=cast(LLMProviderIntegrationRepository, object()),
        toolkit_registry=cast(dict[str, ToolkitProvider[Any]], {}),
        vfs_projection_service=cast(
            VfsProjectionService[AsyncSession],
            vfs_projection_service,
        ),
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
            openai_responses_websocket_enabled=False,
            failed_run_retry_policy=FailedRunRetryPolicy(
                max_retries=failed_run_max_retries,
                base_backoff_seconds=1,
                backoff_multiplier=2,
                max_backoff_seconds=60,
            ),
        ),
        exchange_file_service=cast(ExchangeFileService, object()),
        model_file_service=cast(ModelFileService, object()),
        mailbox_item_service=cast(MailboxService, mailbox_item_service),
        session_git_worktree_service=cast(
            SessionGitWorktreeService,
            session_git_worktree_service,
        ),
        operation_action_executor=OperationActionExecutorRegistry(
            capabilities=TurnActionCapabilityRegistry(
                agent_session_repository=cast(
                    AgentSessionRepository,
                    agent_session_repository,
                ),
                goal_store=cast(Any, object()),
                skill_store=cast(Any, object()),
                vfs_projection_service=None,
            ),
            session_git_worktree_service=cast(
                SessionGitWorktreeService,
                session_git_worktree_service,
            ),
        ),
        session_title_service=cast(SessionTitleService, _SessionTitleService()),
        live_event_projector=cast(LiveEventProjector, live_event_projector),
        user_stop_finalizer=cast(UserStopFinalizer, user_stop_finalizer),
        failed_run_finalizer=cast(Any, failed_run_finalizer),
        builtin_toolkit_provider=cast(BuiltinToolkitProvider, object()),
        claude_rules_toolkit_provider=cast(ClaudeRulesToolkitProvider, object()),
        todo_toolkit_provider=cast(TodoToolkitProvider, object()),
        goal_toolkit_provider=cast(GoalToolkitProvider, object()),
        scheduled_toolkit_provider=cast(
            ScheduledToolkitProvider,
            SimpleNamespace(
                channel_service=SimpleNamespace(
                    create_initial_tracker=AsyncMock(return_value=None)
                )
            ),
        ),
        external_channel_toolkit_provider=cast(
            ExternalChannelToolkitProvider,
            object(),
        ),
        skill_toolkit_provider=cast(SkillToolkitProvider, object()),
        subagent_toolkit_provider=cast(SubagentToolkitProvider, object()),
        dynamic_worktree_toolkit_provider=cast(
            DynamicWorktreeToolkitProvider,
            object(),
        ),
        broadcast=cast(WebSocketBroadcast, object()),
    )


@pytest.mark.asyncio
async def test_idle_continuation_toolkits_use_persisted_session_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Idle continuation ignores the transient broker workspace identifier."""
    executor = _executor()
    resolved_contexts: list[ToolkitContext] = []

    async def resolve_tools(
        agent_id: str,
        context: ToolkitContext,
        **kwargs: object,
    ) -> list[ToolkitBinding]:
        """Capture the toolkit resolution context."""
        del agent_id, kwargs
        resolved_contexts.append(context)
        return []

    async def prepare_toolkits(
        toolkits: Sequence[ToolkitBinding],
    ) -> list[ToolkitBinding]:
        """Return the empty prepared toolkit set."""
        return list(toolkits)

    monkeypatch.setattr(run_executor_module, "resolve_agent_tools", resolve_tools)

    await executor.resolve_idle_continuation_toolkits(
        _message(),
        run_id="run-001",
        prepare_toolkits=prepare_toolkits,
        dispatch_event=_noop_dispatch_event,
    )

    assert resolved_contexts[0].workspace_id == "workspace-001"


def _runtime_agent(
    *,
    state: AgentRuntimeCapability = AgentRuntimeCapability.NONE,
    version: int = 1,
    shell_enabled: bool = True,
) -> SimpleNamespace:
    """Create Runtime capability fields used by Worker resolution tests."""
    return SimpleNamespace(
        memory_enabled=True,
        runtime_capability=state,
        runtime_capability_version=version,
        shell_enabled=shell_enabled,
    )


@pytest.mark.asyncio
async def test_idle_continuation_projects_runtime_tools_from_capability_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Idle continuation passes the capability resolver instead of shell state."""
    executor = _executor(
        agent=_runtime_agent(
            state=AgentRuntimeCapability.MANAGED,
            version=7,
            shell_enabled=True,
        )
    )
    captured: list[RuntimeCapabilityResolver] = []

    async def resolve_tools(
        agent_id: str,
        context: ToolkitContext,
        **kwargs: object,
    ) -> list[ToolkitBinding]:
        """Capture the idle continuation resolver."""
        del agent_id, context
        captured.append(
            cast(RuntimeCapabilityResolver, kwargs["runtime_capability_resolver"])
        )
        return []

    monkeypatch.setattr(run_executor_module, "resolve_agent_tools", resolve_tools)

    async def prepare_toolkits(
        toolkits: Sequence[ToolkitBinding],
    ) -> list[ToolkitBinding]:
        """Return the empty prepared toolkit set."""
        return list(toolkits)

    await executor.resolve_idle_continuation_toolkits(
        _message(),
        run_id="run-001",
        prepare_toolkits=prepare_toolkits,
        dispatch_event=_noop_dispatch_event,
    )

    assert len(captured) == 1
    assert captured[0].snapshot.version == 7
    assert captured[0].project(
        (
            RuntimeCapability.WORKSPACE,
            RuntimeCapability.RUNTIME_FILESYSTEM,
            RuntimeCapability.PROCESS_EXECUTION,
        )
    )


@pytest.mark.asyncio
async def test_runtime_capability_resolver_fails_closed() -> None:
    """Capability state and version fences deny Runtime projection/admission."""
    agent = _runtime_agent(state=AgentRuntimeCapability.NONE, version=3)
    executor = _executor(agent=agent)
    resolver = executor._runtime_capability_resolver(
        agent_id="agent-001",
        agent=cast(Agent, agent),
    )

    assert not resolver.project((RuntimeCapability.WORKSPACE,))

    agent.runtime_capability = AgentRuntimeCapability.MANAGED
    agent.runtime_capability_version = 4
    decision = await resolver.decide(RuntimeCapability.WORKSPACE)

    assert decision.allowed is False
    assert decision.reason_code == "runtime_capability_stale"
    assert decision.expected_version == 3
    assert decision.actual_version == 4

    missing_executor = _executor()
    missing_executor.agent_repository = cast(
        AgentRepository,
        _AgentRepository(default_if_none=False),
    )
    missing_resolver = missing_executor._runtime_capability_resolver(
        agent_id="missing-agent",
        agent=None,
    )
    with pytest.raises(RuntimeError, match="Agent was not found"):
        await missing_resolver.decide(RuntimeCapability.WORKSPACE)


@pytest.mark.asyncio
async def test_finalize_unhandled_active_run_uses_terminal_finalizer() -> None:
    """An exception escaping an active Run reaches durable failed finalization."""
    lifecycle = _SessionLifecycle(
        recoverable_run=_PendingRun(status=AgentRunStatus.RUNNING)
    )
    failed_run_finalizer = _FailedRunFinalizer()
    live_event_projector = _LiveEventProjector()
    executor = _executor(
        lifecycle,
        failed_run_finalizer=failed_run_finalizer,
        live_event_projector=live_event_projector,
    )
    dispatched: list[tuple[str, PublishedEvent]] = []

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        dispatched.append((session_id, event))

    try:
        raise RuntimeError("escaped active run failure")
    except RuntimeError as exc:
        finalized_run_id = await executor.finalize_unhandled_active_run(
            "session-001",
            exc,
            owner_generation=1,
            dispatch_event=dispatch_event,
        )

    assert finalized_run_id == "run-001"
    assert lifecycle.retry_states[-1] is not None
    assert lifecycle.retry_states[-1].attempts[-1].source == "session_runner"
    assert lifecycle.retry_states[-1].attempts[-1].retryability == "non_retryable"
    assert len(failed_run_finalizer.inputs) == 1
    assert failed_run_finalizer.inputs[0].run_id == "run-001"
    assert failed_run_finalizer.inputs[0].reason == "non_retryable"
    assert live_event_projector.discarded_session_ids == ["session-001"]
    assert dispatched == []


def _message(
    *,
    owner_generation: int = 1,
    recoverable_run: _PendingRun | None = None,
    pending_command: PendingSessionCommand | None = None,
) -> CanonicalExecutionSnapshot:
    """Create a canonical Session execution snapshot for executor tests."""
    return CanonicalExecutionSnapshot(
        session_id="session-001",
        root_session_id="session-001",
        workspace_id="workspace-001",
        workspace_handle="workspace",
        agent_id="agent-001",
        session_agent_id="session-agent-001",
        root_session_agent_id="session-agent-001",
        session_agent_context_id="context-001",
        execution_mode=AgentSessionKind.ROOT,
        owner_generation=owner_generation,
        pending_command=(
            PendingCommandSnapshot(
                id=pending_command.id,
                name=pending_command.name,
                payload=pending_command.payload,
                requester_user_id=pending_command.requester_user_id,
                created_at=pending_command.created_at,
            )
            if pending_command is not None
            else None
        ),
        recoverable_run_id=(
            recoverable_run.id if recoverable_run is not None else None
        ),
        recoverable_run_status=(
            recoverable_run.status if recoverable_run is not None else None
        ),
        pending_idle_continuation_run_id=None,
    )


def _action_execution(*, owner_generation: int = 1) -> ActionExecution:
    """Create an active operation execution for executor tests."""
    now = datetime.datetime.now(datetime.UTC)
    action = CreateGitWorktreeAction(
        source_project_path="/workspace/agent/repo",
        starting_ref="main",
    )
    return ActionExecution(
        id="action-execution-001",
        session_id="session-001",
        mailbox_item_id="input-buffer-001",
        sender_user_id=None,
        action_type=action.type,
        action=action.model_dump(mode="json"),
        status=ActionExecutionStatus.PENDING,
        owner_generation=owner_generation,
        failure_summary=None,
        cancellation_summary=None,
        started_at=None,
        completed_at=None,
        failed_at=None,
        cancelled_at=None,
        created_at=now,
        updated_at=now,
    )


def _agent_create_action_execution(
    *,
    owner_generation: int = 1,
) -> ActionExecution:
    """Create an admitted Agent worktree bridge execution."""
    now = datetime.datetime.now(datetime.UTC)
    action = AgentCreateGitWorktreeAction(
        bridge_identity="bridge-001",
        originating_run_id="originating-run-001",
        client_tool_call_id="call-001",
        session_agent_context_id="context-001",
        originating_agent_session_id="session-001",
        source_project_id="project-001",
        source_project_path="/workspace/agent/repo",
        starting_ref=None,
        branch_name=None,
    )
    return ActionExecution(
        id="agent-action-execution-001",
        session_id="session-001",
        mailbox_item_id="agent-input-buffer-001",
        sender_user_id=None,
        action_type=action.type,
        action=action.model_dump(mode="json"),
        status=ActionExecutionStatus.PENDING,
        owner_generation=owner_generation,
        failure_summary=None,
        cancellation_summary=None,
        started_at=None,
        completed_at=None,
        failed_at=None,
        cancelled_at=None,
        created_at=now,
        updated_at=now,
    )


def _agent_remove_action_execution(
    *,
    owner_generation: int = 1,
) -> ActionExecution:
    """Create an admitted Agent worktree removal bridge execution."""
    now = datetime.datetime.now(datetime.UTC)
    action = AgentRemoveGitWorktreeAction(
        bridge_identity="bridge-remove-001",
        originating_run_id="originating-remove-run-001",
        client_tool_call_id="call-remove-001",
        session_agent_context_id="context-001",
        originating_agent_session_id="session-001",
        worktree_project_id="project-worktree-001",
        worktree_allocation_id="allocation-001",
        worktree_path="/workspace/agent/worktree",
        force=False,
    )
    return ActionExecution(
        id="agent-remove-action-execution-001",
        session_id="session-001",
        mailbox_item_id="agent-remove-input-buffer-001",
        sender_user_id=None,
        action_type=action.type,
        action=action.model_dump(mode="json"),
        status=ActionExecutionStatus.PENDING,
        owner_generation=owner_generation,
        failure_summary=None,
        cancellation_summary=None,
        started_at=None,
        completed_at=None,
        failed_at=None,
        cancelled_at=None,
        created_at=now,
        updated_at=now,
    )


def _pending_command(name: str = "compact") -> PendingSessionCommand:
    """Create a pending command for executor tests."""
    return PendingSessionCommand(
        id="command-001",
        name=name,
        payload={},
        requester_user_id="user-001",
        created_at=datetime.datetime.now(datetime.UTC),
    )


@pytest.mark.parametrize(
    ("cancel_message", "expected_reason"),
    [
        (USER_STOP_CANCEL_MESSAGE, "Operation cancelled by user stop."),
        (
            SHUTDOWN_CANCEL_MESSAGE,
            "Operation cancelled after the worker shutdown wait expired.",
        ),
    ],
)
@pytest.mark.asyncio
async def test_boundary_cancellation_waits_for_live_action_handoff(
    monkeypatch: pytest.MonkeyPatch,
    cancel_message: str,
    expected_reason: str,
) -> None:
    """Cancellation cannot escape after a claim until live actions hand off."""
    worktree_service = _SessionGitWorktreeService()
    executor = _executor(session_git_worktree_service=worktree_service)
    claim_committed = asyncio.Event()
    cleanup_started = asyncio.Event()
    cleanup_release = asyncio.Event()
    cancellation_reasons: list[str] = []

    async def execute_after_claim(
        *args: object,
        **kwargs: object,
    ) -> RunExecutionResult:
        del args, kwargs
        claim_committed.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def cancel_live_action_executions(
        *,
        session_id: str,
        reason: str,
        on_history_event_appended: object,
        on_action_execution_removed: object,
        predecessor_run_id: str | None = None,
    ) -> list[Event]:
        del (
            session_id,
            on_history_event_appended,
            on_action_execution_removed,
            predecessor_run_id,
        )
        cancellation_reasons.append(reason)
        cleanup_started.set()
        await cleanup_release.wait()
        return []

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id, event

    monkeypatch.setattr(executor, "_execute", execute_after_claim)
    monkeypatch.setattr(
        worktree_service,
        "cancel_live_action_executions",
        cancel_live_action_executions,
    )
    task = asyncio.create_task(
        executor.execute(
            _message(),
            poll_fn=None,
            check_stop=None,
            prepare_toolkits=None,
            shutdown_event=asyncio.Event(),
            dispatch_event=dispatch_event,
            owner_generation=1,
            tool_admission_barrier=ToolAdmissionBarrier(),
            model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
        )
    )
    await claim_committed.wait()
    task.cancel(cancel_message)
    await cleanup_started.wait()
    assert not task.done()

    cleanup_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancellation_reasons == [expected_reason]


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
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                compaction_provider_integration_id=None,
                inference_state=None,
            ),
            model_selection=make_test_model_selection(),
            model_settings=make_test_model_settings(),
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
            tool_search_enabled=False,
            auto_compaction_threshold_tokens=None,
            compaction_provider_integration_id=None,
            inference_state=None,
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
async def test_execute_classifies_new_recoverable_run_as_snapshot_drift() -> None:
    """A Run appearing after snapshot load is retried instead of finalized."""
    lifecycle = _SessionLifecycle(
        recoverable_run=_PendingRun(status=AgentRunStatus.RUNNING)
    )
    executor = _executor(session_lifecycle=lifecycle)

    with pytest.raises(
        CanonicalExecutionWorkDriftError,
        match="recoverable AgentRun changed",
    ):
        await executor.execute(
            _message(),
            poll_fn=None,
            check_stop=None,
            prepare_toolkits=None,
            shutdown_event=asyncio.Event(),
            dispatch_event=_noop_dispatch_event,
            owner_generation=1,
            tool_admission_barrier=ToolAdmissionBarrier(),
            model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
        )


@pytest.mark.asyncio
async def test_execute_uses_atomic_scheduled_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Scheduled FIFO head supplies its pre-created Run and promoted input."""
    now = datetime.datetime.now(datetime.UTC)
    scheduled_run = AgentRunState(
        id="1234567890abcdef1234567890abcdef",
        session_id="session-001",
        scheduled_task_cycle_id="abcdef1234567890abcdef1234567890",
        run_index=1,
        phase=AgentRunPhase.IDLE,
        status=AgentRunStatus.PENDING,
        parent_agent_run_id=None,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        active_tool_calls=[],
        parent_result_delivery_state=None,
        parent_result_mailbox_item_id=None,
        parent_result_enqueued_at=None,
        created_at=now,
        started_at=None,
        model_call_started_at=None,
        updated_at=now,
    )
    scheduled_message = make_run_user_message(
        sender_user_id=None,
        content="Scheduled task input",
        metadata={"scheduled_task": "true"},
        attachments=[],
        external_id="scheduled-buffer-001:scheduled_task",
        attachment_source="mailbox_item",
        requested_inference_profile=None,
    )
    mailbox_service = _MailboxService(
        scheduled_admission=ScheduledMailboxAdmission(
            run=scheduled_run,
            promoted=PromotedMailboxItems(
                operation_action=None,
                turn_effect=TurnEffect.ELIGIBLE,
                requested_inference_profile=None,
                promoted_event_ids=["scheduled-event-001"],
                user_messages=[scheduled_message],
                events=[],
                deleted_buffer_ids=["scheduled-buffer-001"],
                changed_session_agent_ids=[],
                claimed_count=1,
                inserted_count=1,
                deduped_count=0,
                complete_run=False,
                suppress_parent_result=False,
            ),
            stale=False,
        ),
        mailbox_item_id="scheduled-buffer-001",
    )
    order: list[str] = []
    lifecycle = _SessionLifecycle(order)
    executor = _executor(
        session_lifecycle=lifecycle,
        engine=_RecordingEngine(order),
        mailbox_item_service=mailbox_service,
        vfs_projection_service=_VfsProjectionService(order),
    )

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        raise AssertionError("Scheduled admission must bypass ordinary FIFO promotion")

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    _patch_successful_resolution(monkeypatch)

    result = await executor.execute(
        _message(),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=_noop_dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert mailbox_service.scheduled_admission_calls == [
        ("session-001", 1, "scheduled-buffer-001")
    ]
    assert lifecycle.pending_run_create_calls == 0
    assert lifecycle.activation_calls == 1
    assert lifecycle.activation_profiles == [
        RequestedInferenceProfile(
            model_target_label="default",
            reasoning_effort=None,
        )
    ]
    assert result.run_id == scheduled_run.id
    assert result.terminal_run_status is AgentRunStatus.COMPLETED
    assert order[:3] == ["vfs", "activate_pending", "provider"]


@pytest.mark.asyncio
async def test_execute_discards_stale_scheduled_admission() -> None:
    """A stale Scheduled trigger is consumed without creating another Run."""
    mailbox_service = _MailboxService(
        scheduled_admission=ScheduledMailboxAdmission(
            run=None,
            promoted=None,
            stale=True,
        ),
        mailbox_item_id="scheduled-buffer-001",
    )
    lifecycle = _SessionLifecycle()
    vfs_projection_service = _VfsProjectionService()
    executor = _executor(
        session_lifecycle=lifecycle,
        mailbox_item_service=mailbox_service,
        vfs_projection_service=vfs_projection_service,
    )

    result = await executor.execute(
        _message(),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=_noop_dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert result == RunExecutionResult(
        toolkits=[],
        terminal_event_observed=False,
        no_actionable_work=True,
    )
    assert mailbox_service.scheduled_admission_calls == [
        ("session-001", 1, "scheduled-buffer-001")
    ]
    assert lifecycle.pending_run_create_calls == 0
    assert vfs_projection_service.calls == []


@pytest.mark.asyncio
async def test_takeover_cancellation_uses_pending_snapshot_run_as_predecessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pending processing Run fences takeover continuation before it is claimed."""
    recoverable = _PendingRun(id="pending-run-001", status=AgentRunStatus.PENDING)
    lifecycle = _SessionLifecycle(recoverable_run=recoverable)
    worktree_service = _SessionGitWorktreeService()
    executor = _executor(
        session_lifecycle=lifecycle,
        session_git_worktree_service=worktree_service,
    )

    async def stop_after_handoff(*args: object, **kwargs: object) -> _PendingRun:
        del args, kwargs
        raise RuntimeError("stop after predecessor capture")

    monkeypatch.setattr(
        lifecycle,
        "claim_recoverable_agent_run",
        stop_after_handoff,
    )

    with pytest.raises(RuntimeError, match="stop after predecessor capture"):
        await executor.execute(
            _message(recoverable_run=recoverable),
            poll_fn=None,
            check_stop=None,
            prepare_toolkits=None,
            shutdown_event=asyncio.Event(),
            dispatch_event=_noop_dispatch_event,
            owner_generation=1,
            tool_admission_barrier=ToolAdmissionBarrier(),
            model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
        )

    assert worktree_service.reconciled_predecessor_run_ids == [recoverable.id]


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
            suppress_parent_result=False,
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
        _message(),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=cast(asyncio.Event, object()),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
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
    """A running activation keeps its prepared profile before pending input."""
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
    order: list[str] = []
    vfs_projection_service = _VfsProjectionService(order)
    captured_resolvers: list[RuntimeCapabilityResolver] = []
    executor = _executor(
        session_lifecycle=lifecycle,
        vfs_projection_service=vfs_projection_service,
        agent=_runtime_agent(
            state=AgentRuntimeCapability.MANAGED,
            version=11,
            shell_enabled=True,
        ),
    )
    recovered_snapshots: list[AgentModelSelection] = []
    pending_profile = RequestedInferenceProfile(
        model_target_label="Fast",
        reasoning_effort=None,
    )
    pending_inputs = [
        PendingInputInferenceProfile(
            mailbox_item_id="buffer-later-profile",
            requires_inference=True,
            exists=True,
            requested_inference_profile=pending_profile,
        ),
        PendingInputInferenceProfile(
            mailbox_item_id=None,
            requires_inference=False,
            exists=False,
            requested_inference_profile=None,
        ),
    ]

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
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                compaction_provider_integration_id=None,
                inference_state=None,
            )
        )

    async def resolve_new(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("A recovered run must not resolve its target again")

    async def resolve_tools(
        agent_id: str,
        context: ToolkitContext,
        **kwargs: object,
    ) -> list[ToolkitBinding]:
        """Capture the active Run capability resolver."""
        del agent_id, context
        captured_resolvers.append(
            cast(RuntimeCapabilityResolver, kwargs["runtime_capability_resolver"])
        )
        return []

    async def peek_pending_input(
        session_id: str,
    ) -> PendingInputInferenceProfile:
        assert session_id == "session-001"
        return pending_inputs.pop(0)

    async def promote_pending_input(
        *args: object,
        **kwargs: object,
    ) -> PromotedMailboxItems:
        del args
        pending = cast(PendingInputInferenceProfile, kwargs["pending"])
        assert pending.requested_inference_profile == pending_profile
        order.append("input")
        return PromotedMailboxItems(
            operation_action=None,
            turn_effect=TurnEffect.ELIGIBLE,
            requested_inference_profile=pending_profile,
            promoted_event_ids=["event-later-profile"],
            user_messages=[],
            events=[],
            deleted_buffer_ids=["buffer-later-profile"],
            changed_session_agent_ids=[],
            claimed_count=1,
            inserted_count=1,
            deduped_count=0,
            complete_run=False,
            suppress_parent_result=False,
        )

    async def has_actionable_model_input(session_id: str) -> bool:
        assert session_id == "session-001"
        return True

    async def process_operation_actions(
        *args: object,
        **kwargs: object,
    ) -> OperationActionProcessResult:
        del args, kwargs
        return OperationActionProcessResult(
            context_invalidated=False,
            complete_run=False,
        )

    monkeypatch.setattr(
        executor.mailbox_item_service,
        "peek_pending_inference_profile",
        peek_pending_input,
    )
    monkeypatch.setattr(executor, "_promote_mailbox_items", promote_pending_input)
    monkeypatch.setattr(
        executor,
        "_has_actionable_model_input",
        has_actionable_model_input,
    )
    monkeypatch.setattr(
        executor,
        "_process_operation_actions",
        process_operation_actions,
    )
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
    monkeypatch.setattr(run_executor_module, "resolve_agent_tools", resolve_tools)

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id, event

    result = await executor.execute(
        _message(recoverable_run=recoverable),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert result.run_id == recoverable.id
    assert recovered_snapshots == [selection]
    assert order[:2] == ["vfs", "input"]
    assert len(captured_resolvers) == 1
    assert captured_resolvers[0].snapshot.state is AgentRuntimeCapability.MANAGED
    assert captured_resolvers[0].snapshot.version == 11
    assert vfs_projection_service.calls == [
        (recoverable.id, "agent-001", "session-001", "workspace-001")
    ]
    assert lifecycle.pending_run_create_calls == 0
    assert lifecycle.activation_calls == 0
    assert pending_inputs == []


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
            suppress_parent_result=False,
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
        _message(recoverable_run=recoverable),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
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
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                compaction_provider_integration_id=None,
                inference_state=None,
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
        _message(
            recoverable_run=recoverable,
            pending_command=_pending_command(),
        ),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
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
            suppress_parent_result=False,
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
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                compaction_provider_integration_id=None,
                inference_state=None,
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
        _message(recoverable_run=recoverable),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert result.terminal_run_status == AgentRunStatus.FAILED
    assert len(finalizer.inputs) == 1
    assert finalizer.inputs[0].retry_state.failed_attempt_count == 3


@pytest.mark.asyncio
async def test_execute_claims_manual_retry_profile_before_flushing_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manual retry preserves requested intent and routes it again."""
    recoverable = _PendingRun(
        requested_model_target_label="fast",
        requested_reasoning_effort=None,
        inference_profile_source=InferenceProfileSource.RETRY_ORIGINAL,
    )
    lifecycle = _SessionLifecycle(recoverable_run=recoverable)
    retry_state = SessionInferenceState(
        model_target_label="fast",
        model_selection=make_test_model_selection(),
        model_settings=make_test_model_settings(),
        reasoning_effort=None,
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
            suppress_parent_result=False,
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
        _message(recoverable_run=recoverable),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert result.run_id == recoverable.id
    assert lifecycle.pending_run_create_calls == 0
    assert lifecycle.activation_calls == 1
    assert poll_calls[0]["required_inference_profile"] == RequestedInferenceProfile(
        model_target_label="fast",
        reasoning_effort=None,
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
        model_target_label="default",
        model_selection=selection,
        model_settings=make_test_model_settings(),
        reasoning_effort=None,
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
            suppress_parent_result=False,
            requested_inference_profile=None,
            promoted_event_ids=["event-001"],
            user_messages=[],
            has_actionable_work=True,
        )

    async def resolve_target(*args: object, **kwargs: object) -> object:
        del args, kwargs
        resolved_snapshots.append(selection)
        return await _resolve_success()

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_profile",
        resolve_target,
    )
    monkeypatch.setattr(run_executor_module, "resolve_agent_tools", _resolve_no_tools)

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id, event

    result = await executor.execute(
        _message(recoverable_run=recoverable),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert result.run_id == recoverable.id
    assert resolved_snapshots == [selection]
    assert lifecycle.activation_calls == 1
    assert order[:2] == ["activate_pending", "provider"]
    request = engine.requests[0]
    assert request.effective_max_input_tokens == 128_000
    assert request.context_window_tokens == 128_000
    assert request.compaction_max_input_tokens == 128_000
    assert request.auto_compaction_threshold_tokens == 115_200
    assert request.inference_state is not None
    assert request.inference_state.model_target_label == "default"
    assert request.inference_state.model_selection == selection


@pytest.mark.asyncio
async def test_prepare_fresh_turn_remaps_same_label_to_current_agent_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh preparation resolves the current Agent mapping for one stable label."""
    old_state = SessionInferenceState(
        model_target_label="default",
        model_selection=make_test_model_selection(model_identifier="gpt-old"),
        model_settings=make_test_model_settings(),
        reasoning_effort=None,
        effective_context_window_tokens=64_000,
        effective_auto_compaction_threshold_tokens=51_200,
        resolved_at=datetime.datetime.now(datetime.UTC),
    )
    session_repository = _AgentSessionRepository(inference_state=old_state)
    session_repository.applied_inference_profile = SessionAppliedInferenceProfile(
        model_target_label="default",
        reasoning_effort=None,
    )
    executor = _executor(agent_session_repository=session_repository)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_profile",
        _resolve_success,
    )

    prepared = await executor._prepare_fresh_main_model_turn(
        agent_id="agent-001",
        session_id="session-001",
        owner_generation=1,
        invoke_input=InvokeInput(
            agent_id="agent-001",
            session_id="session-001",
            messages=[],
        ),
        override=None,
    )

    assert isinstance(prepared, Success)
    assert prepared.value.profile == RequestedInferenceProfile(
        model_target_label="default",
        reasoning_effort=None,
    )
    assert prepared.value.inference_state.model_selection.model_identifier == "gpt-4o"
    assert session_repository.inference_state is prepared.value.inference_state


@pytest.mark.asyncio
async def test_execute_new_implicit_run_remaps_same_label_to_current_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new implicit Run resolves current Agent mapping despite prepared state."""
    old_state = SessionInferenceState(
        model_target_label="default",
        model_selection=make_test_model_selection(model_identifier="gpt-old"),
        model_settings=make_test_model_settings(),
        reasoning_effort=None,
        effective_context_window_tokens=64_000,
        effective_auto_compaction_threshold_tokens=51_200,
        resolved_at=datetime.datetime.now(datetime.UTC),
    )
    session_repository = _AgentSessionRepository(inference_state=old_state)
    session_repository.applied_inference_profile = SessionAppliedInferenceProfile(
        model_target_label="default",
        reasoning_effort=None,
    )
    engine = _RecordingEngine([])
    executor = _executor(
        engine=engine,
        agent_session_repository=session_repository,
    )
    _patch_successful_resolution(monkeypatch)

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            user_messages=[],
            requested_inference_profile=None,
            promoted_event_ids=[],
            has_actionable_work=True,
            context_invalidated=False,
            complete_run=False,
            suppress_parent_result=False,
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert result.terminal_run_status == AgentRunStatus.COMPLETED
    assert len(engine.requests) == 1
    assert engine.requests[0].inference_state is not None
    assert engine.requests[0].inference_state.model_target_label == "default"
    assert (
        engine.requests[0].inference_state.model_selection.model_identifier == "gpt-4o"
    )
    assert session_repository.inference_state is not None
    assert (
        session_repository.inference_state.model_selection.model_identifier == "gpt-4o"
    )


@pytest.mark.asyncio
async def test_prepare_fresh_turn_fails_closed_when_session_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing canonical Session rows do not resolve, dispatch, or commit."""
    session_repository = _AgentSessionRepository()
    session_repository.get_by_id = AsyncMock(return_value=None)
    executor = _executor(agent_session_repository=session_repository)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_profile",
        AsyncMock(side_effect=AssertionError("missing Session must not resolve")),
    )

    with pytest.raises(ValueError, match="AgentSession or Agent not found"):
        await executor._prepare_fresh_main_model_turn(
            agent_id="agent-001",
            session_id="session-001",
            owner_generation=1,
            invoke_input=InvokeInput(
                agent_id="agent-001",
                session_id="session-001",
                messages=[],
            ),
            override=None,
        )
    assert session_repository.inference_state is None


@pytest.mark.asyncio
async def test_prepare_fresh_turn_fails_closed_when_agent_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing canonical Agent rows do not resolve, dispatch, or commit."""
    agent_repository = _AgentRepository(default_if_none=False)
    session_repository = _AgentSessionRepository()
    executor = _executor(
        agent=cast(object, None),
        agent_session_repository=session_repository,
    )
    executor.agent_repository = cast(AgentRepository, agent_repository)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_profile",
        AsyncMock(side_effect=AssertionError("missing Agent must not resolve")),
    )

    with pytest.raises(ValueError, match="AgentSession or Agent not found"):
        await executor._prepare_fresh_main_model_turn(
            agent_id="agent-001",
            session_id="session-001",
            owner_generation=1,
            invoke_input=InvokeInput(
                agent_id="agent-001",
                session_id="session-001",
                messages=[],
            ),
            override=None,
        )
    assert session_repository.inference_state is None


@pytest.mark.asyncio
async def test_prepare_fresh_turn_rejects_owner_generation_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A final owner fence prevents committing a candidate prepared by a stale owner."""
    session_repository = _AgentSessionRepository(owner_generation=2)
    executor = _executor(agent_session_repository=session_repository)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_profile",
        _resolve_success,
    )

    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await executor._prepare_fresh_main_model_turn(
            agent_id="agent-001",
            session_id="session-001",
            owner_generation=1,
            invoke_input=InvokeInput(
                agent_id="agent-001",
                session_id="session-001",
                messages=[],
            ),
            override=None,
        )

    assert session_repository.inference_state is None


@pytest.mark.asyncio
async def test_execute_rebuilds_turn_with_exact_updated_inference_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn-boundary profile change reaches the next model call exactly."""
    initial_state = SessionInferenceState(
        model_target_label="fast",
        model_selection=make_test_model_selection(model_identifier="gpt-fast"),
        model_settings=make_test_model_settings(),
        reasoning_effort=ModelReasoningEffort.LOW,
        effective_context_window_tokens=64_000,
        effective_auto_compaction_threshold_tokens=51_200,
        resolved_at=datetime.datetime.now(datetime.UTC),
    )
    updated_state = SessionInferenceState(
        model_target_label="planning",
        model_selection=make_test_model_selection(model_identifier="gpt-planning"),
        model_settings=make_test_model_settings(),
        reasoning_effort=None,
        effective_context_window_tokens=128_000,
        effective_auto_compaction_threshold_tokens=102_400,
        resolved_at=datetime.datetime.now(datetime.UTC),
    )
    session_repo = _AgentSessionRepository(inference_state=initial_state)
    engine = _BoundarySwitchEngine()
    executor = _executor(
        engine=engine,
        agent_session_repository=session_repo,
    )
    poll_count = 0

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        nonlocal poll_count
        del args, kwargs
        poll_count += 1
        if poll_count == 2:
            session_repo.inference_state = updated_state
            session_repo.applied_inference_profile = SessionAppliedInferenceProfile(
                model_target_label="planning",
                reasoning_effort=None,
            )
            return RunInputPollResult(
                context_invalidated=True,
                complete_run=False,
                suppress_parent_result=False,
                requested_inference_profile=RequestedInferenceProfile(
                    model_target_label="planning",
                    reasoning_effort=None,
                ),
                promoted_event_ids=["event-002"],
                user_messages=[],
                has_actionable_work=True,
            )
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            suppress_parent_result=False,
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert result.terminal_run_status == AgentRunStatus.COMPLETED
    assert engine.requests[0].inference_state is not None
    assert engine.requests[0].inference_state.model_target_label == "default"
    assert engine.requests[1].inference_state is not None
    assert engine.requests[1].inference_state.model_target_label == "planning"
    assert engine.requests[1].inference_state.reasoning_effort is None
    assert engine.requests[1].effective_max_input_tokens == 128_000
    assert engine.requests[1].auto_compaction_threshold_tokens == 115_200


@pytest.mark.parametrize(
    ("resolve_error", "expected_failure_code"),
    [
        (
            ModelTargetNotFound(model_target_label="planning"),
            InferenceProfileFailureCode.MODEL_TARGET_NOT_FOUND,
        ),
        (
            ReasoningEffortUnsupported(
                model_target_label="planning",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            InferenceProfileFailureCode.REASONING_EFFORT_UNSUPPORTED,
        ),
    ],
)
@pytest.mark.asyncio
async def test_execute_terminalizes_late_profile_failure_without_retry_or_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    resolve_error: object,
    expected_failure_code: InferenceProfileFailureCode,
) -> None:
    """Late deterministic profile drift terminalizes without overwriting state."""
    session_repository = _AgentSessionRepository()
    lifecycle = _SessionLifecycle()
    engine = _BoundarySwitchEngine()
    finalizer = _FailedRunFinalizer()
    executor = _executor(
        session_lifecycle=lifecycle,
        engine=engine,
        agent_session_repository=session_repository,
        failed_run_finalizer=finalizer,
    )
    resolve_calls = 0
    poll_calls = 0

    async def resolve_profile(*args: object, **kwargs: object) -> object:
        nonlocal resolve_calls
        del args, kwargs
        resolve_calls += 1
        if resolve_calls == 1:
            return await _resolve_success()
        return Failure(resolve_error)

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        nonlocal poll_calls
        del args, kwargs
        poll_calls += 1
        if poll_calls == 2:
            session_repository.applied_inference_profile = (
                SessionAppliedInferenceProfile(
                    model_target_label="planning",
                    reasoning_effort=None,
                )
            )
        return RunInputPollResult(
            context_invalidated=True,
            complete_run=False,
            suppress_parent_result=False,
            requested_inference_profile=None,
            promoted_event_ids=["event-boundary"],
            user_messages=[],
            has_actionable_work=True,
        )

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        run_executor_module,
        "resolve_invoke_input_with_profile",
        resolve_profile,
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert result.terminal_run_status == AgentRunStatus.FAILED
    assert len(finalizer.inputs) == 1
    retry_state = finalizer.inputs[0].retry_state
    assert retry_state.failed_attempt_count == 1
    assert retry_state.retryability == "non_retryable"
    assert retry_state.attempts[0].failure_code == expected_failure_code
    assert len(engine.requests) == 1
    assert resolve_calls == 2
    assert session_repository.inference_state is not None
    assert session_repository.inference_state.model_target_label == "default"


@pytest.mark.asyncio
async def test_execute_enqueues_follow_up_after_context_invalidating_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Project-mutating actions stop before dispatch without stale wake fallback."""
    lifecycle = _SessionLifecycle()
    executor = _executor(session_lifecycle=lifecycle)
    message = _message()

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            complete_run=False,
            suppress_parent_result=False,
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert result.no_actionable_work is True
    assert lifecycle.wake_ups == []


def test_dynamic_worktree_binding_receives_current_run_boundary() -> None:
    """The reconciled Toolkit receives the private boundary for this exact Run."""
    toolkit = DynamicWorktreeToolkit(
        service=cast(SessionGitWorktreeService, object()),
        broker=cast(SessionBroker, object()),
        agent_id="agent-001",
        session_id="session-001",
    )
    binding = ToolkitBinding(
        toolkit=toolkit,
        slug="dynamic_worktree",
        use_prefix=False,
    )
    boundary = TurnActionBridgeBoundary()

    run_executor_module._bind_dynamic_worktree_toolkits(
        [binding],
        run_id="run-001",
        turn_action_bridge_boundary=boundary,
    )

    assert toolkit.run_id == "run-001"
    assert toolkit.turn_action_bridge_boundary is boundary


@pytest.mark.asyncio
async def test_agent_create_operation_uses_active_processing_run_as_predecessor() -> (
    None
):
    """Agent bridge dispatch carries the Run that executes its terminal action."""
    service = _SessionGitWorktreeService()
    executor = _executor(session_git_worktree_service=service)
    execution = _agent_create_action_execution()
    action = AgentCreateGitWorktreeAction.model_validate(execution.action)

    result = await executor._process_operation_action(
        agent_id="agent-001",
        session_id="session-001",
        active_run_id="processing-run-001",
        execution=execution,
        action=action,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
    )

    assert result.complete_run is True
    assert service.executed_execution_ids == [execution.id]
    assert service.executed_predecessor_run_ids == ["processing-run-001"]


@pytest.mark.asyncio
async def test_agent_create_operation_requires_active_processing_run() -> None:
    """A bridge action cannot terminalize without a predecessor Run identity."""
    service = _SessionGitWorktreeService()
    executor = _executor(session_git_worktree_service=service)
    execution = _agent_create_action_execution()
    action = AgentCreateGitWorktreeAction.model_validate(execution.action)

    with pytest.raises(RuntimeError, match="requires an active processing Run"):
        await executor._process_operation_action(
            agent_id="agent-001",
            session_id="session-001",
            active_run_id=None,
            execution=execution,
            action=action,
            owner_generation=1,
            tool_admission_barrier=ToolAdmissionBarrier(),
        )

    assert service.executed_execution_ids == []
    assert service.executed_predecessor_run_ids == []


@pytest.mark.asyncio
async def test_agent_remove_operation_uses_active_processing_run_as_predecessor() -> (
    None
):
    """Agent removal dispatch carries the Run that executes its terminal action."""
    service = _SessionGitWorktreeService()
    executor = _executor(session_git_worktree_service=service)
    execution = _agent_remove_action_execution()
    action = AgentRemoveGitWorktreeAction.model_validate(execution.action)

    result = await executor._process_operation_action(
        agent_id="agent-001",
        session_id="session-001",
        active_run_id="processing-remove-run-001",
        execution=execution,
        action=action,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
    )

    assert result.complete_run is True
    assert service.executed_execution_ids == [execution.id]
    assert service.executed_predecessor_run_ids == ["processing-remove-run-001"]


@pytest.mark.asyncio
async def test_operation_admission_closed_by_shutdown_is_cancelled() -> None:
    """A closed foreground barrier prevents the operation side effect."""
    service = _SessionGitWorktreeService()
    executor = _executor(session_git_worktree_service=service)
    barrier = ToolAdmissionBarrier()
    await barrier.close()
    execution = _action_execution()
    action = CreateGitWorktreeAction.model_validate(execution.action)

    # Pin operation admission fencing directly.
    result = await executor._process_operation_action(
        agent_id="agent-001",
        session_id="session-001",
        active_run_id=None,
        execution=execution,
        action=action,
        owner_generation=1,
        tool_admission_barrier=barrier,
    )

    assert result.completed is True
    assert result.context_invalidated is False
    assert service.cancelled_execution_ids == [execution.id]
    assert service.executed_execution_ids == []


@pytest.mark.asyncio
async def test_operation_owner_generation_mismatch_is_cancelled() -> None:
    """A worker cannot execute an operation admitted by another owner."""
    service = _SessionGitWorktreeService()
    executor = _executor(session_git_worktree_service=service)
    execution = _action_execution(owner_generation=2)
    action = CreateGitWorktreeAction.model_validate(execution.action)

    # Pin operation admission fencing directly.
    result = await executor._process_operation_action(
        agent_id="agent-001",
        session_id="session-001",
        active_run_id=None,
        execution=execution,
        action=action,
        owner_generation=3,
        tool_admission_barrier=ToolAdmissionBarrier(),
    )

    assert result.completed is True
    assert result.context_invalidated is False
    assert service.cancelled_execution_ids == [execution.id]
    assert service.executed_execution_ids == []


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
            suppress_parent_result=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=True,
        )

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)

    poll = executor.make_boundary_poll(
        snapshot=message,
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
        dispatch_event=_noop_dispatch_event,
    )

    assert await poll() == PollMessagesResult(
        user_messages=[],
        context_invalidated=False,
        complete_run=False,
        suppress_parent_result=False,
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

    class PendingMailboxService:
        """MailboxService double with pending follow-up work."""

        async def has_pending_session_mailbox_items(self, session_id: str) -> bool:
            """Return pending follow-up work for the session."""
            assert session_id == message.session_id
            return True

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            complete_run=False,
            suppress_parent_result=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=False,
            context_invalidated=True,
        )

    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    monkeypatch.setattr(
        executor,
        "mailbox_item_service",
        cast(MailboxService, PendingMailboxService()),
    )

    context_invalidated = False

    def mark_context_invalidated() -> None:
        nonlocal context_invalidated
        context_invalidated = True

    poll = executor.make_boundary_poll(
        snapshot=message,
        model="gpt-test",
        requested_inference_profile=RequestedInferenceProfile(
            model_target_label="default",
            reasoning_effort=None,
        ),
        run_id="run-001",
        poll_fn=None,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        mark_context_invalidated=mark_context_invalidated,
        dispatch_event=_noop_dispatch_event,
    )

    assert await poll() == PollMessagesResult(
        complete_run=False,
        suppress_parent_result=False,
        user_messages=[],
        context_invalidated=True,
    )
    assert context_invalidated is True
    assert lifecycle.wake_ups == [SessionWakeUp(session_id=message.session_id)]


@pytest.mark.asyncio
async def test_poll_run_inputs_consumes_external_channel_batch_under_one_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Session owner consumes context and invocation rows before an empty read."""
    executor = _executor()
    created_at = datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC)
    context = ExternalChannelMailboxProjectionItem(
        invocation_id="batch-1",
        binding_id="binding-1",
        trigger_provider_message_key="C123:1.0:2",
        prompt_role="context",
        context_omitted=True,
        sequence=0,
        revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
        body="Context",
        attachment_metadata={},
        reference_mappings=None,
        resource_id="resource-1",
        provider_resource_key="C123:1.0",
        resource_type=ExternalChannelResourceType.THREAD,
        resource_labels={"channel_id": "C123", "thread_ts": "1.0"},
        provider=ExternalChannelProvider.SLACK,
        provider_tenant_id="T1",
        provider_message_key="C123:1.0:1",
        provider_position="1",
        principal_id="principal-1",
        provider_user_id="U1",
        sender_display_name="Alice",
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        provider_created_at=created_at,
        provider_updated_at=None,
        original_url=None,
    )
    invocation = context.model_copy(
        update={
            "prompt_role": "invocation",
            "context_omitted": False,
            "sequence": 1,
            "body": "Invoke",
            "provider_message_key": "C123:1.0:2",
            "provider_position": "2",
        }
    )

    def mailbox_item(
        item: ExternalChannelMailboxProjectionItem,
        mailbox_id: str,
    ) -> MailboxItem:
        return MailboxItem(
            id=mailbox_id,
            session_id="session-1",
            kind=MailboxItemKind.EXTERNAL_CHANNEL_MESSAGE,
            scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            sender_user_id=None,
            order_group="00000000000000000000000000000001",
            order_sequence=item.sequence,
            content="",
            idempotency_key=f"external-channel-message:{item.sequence}",
            metadata={},
            payload=build_external_channel_mailbox_payload(
                item,
                context_omitted=item.context_omitted,
                initial_title_eligible=item.prompt_role == "invocation",
            ),
            action=None,
            attachments=[],
            file_parts=[],
            created_at=created_at,
        )

    buffers = {
        "buffer-context": mailbox_item(context, "buffer-context"),
        "buffer-invocation": mailbox_item(invocation, "buffer-invocation"),
    }
    profiles = [
        PendingInputInferenceProfile(
            mailbox_item_id="buffer-context",
            requires_inference=True,
            exists=True,
            requested_inference_profile=None,
        ),
        PendingInputInferenceProfile(
            mailbox_item_id="buffer-invocation",
            requires_inference=True,
            exists=True,
            requested_inference_profile=None,
        ),
        PendingInputInferenceProfile(
            mailbox_item_id=None,
            requires_inference=False,
            exists=False,
            requested_inference_profile=None,
        ),
    ]
    processor = ExternalChannelMessageMailboxProcessor(
        cast(MailboxService, SimpleNamespace())
    )
    preparation_context = MailboxPreparationContext(
        session=cast(AsyncSession, object()),
        session_id="session-1",
        active_run_id=None,
        required_inference_profile=None,
        prepared_inference_state=None,
        prepared_files=PreparedMailboxFiles(
            attachments=[],
            file_parts=[],
            created_model_file_ids=[],
        ),
    )
    promoted_buffer_ids: list[str] = []
    promoted_events: list[Event] = []

    async def peek(session_id: str) -> PendingInputInferenceProfile:
        assert session_id == "session-1"
        return profiles.pop(0)

    async def promote(*args: object, **kwargs: object) -> PromotedMailboxItems:
        del args
        pending = cast(PendingInputInferenceProfile, kwargs["pending"])
        assert pending.mailbox_item_id is not None
        buffer = buffers[pending.mailbox_item_id]
        outcome = await processor.process(preparation_context, buffer)
        events = [
            Event(
                id=f"{index + len(promoted_events) + 1:032x}",
                session_id="session-1",
                kind=item.event_kind,
                payload=item.payload,
                external_id=item.external_id,
                created_at=created_at,
            )
            for index, item in enumerate(outcome.promoted)
        ]
        promoted_buffer_ids.append(buffer.id)
        promoted_events.extend(events)
        return PromotedMailboxItems(
            operation_action=None,
            turn_effect=outcome.turn_effect,
            requested_inference_profile=None,
            promoted_event_ids=[event.id for event in events],
            user_messages=[],
            events=events,
            deleted_buffer_ids=[buffer.id],
            changed_session_agent_ids=[],
            claimed_count=1,
            inserted_count=len(events),
            deduped_count=0,
            complete_run=outcome.complete_run,
            suppress_parent_result=outcome.suppress_parent_result,
        )

    monkeypatch.setattr(
        executor.mailbox_item_service,
        "peek_pending_inference_profile",
        peek,
    )
    monkeypatch.setattr(executor, "_promote_mailbox_items", promote)

    async def has_actionable_model_input(session_id: str) -> bool:
        assert session_id == "session-1"
        return True

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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        initial_turn_eligible=False,
        poll_fn=None,
        process_actions=False,
        dispatch_event=_noop_dispatch_event,
    )

    assert result.has_actionable_work is True
    assert promoted_buffer_ids == ["buffer-context", "buffer-invocation"]
    assert [event.kind for event in promoted_events] == [
        EventKind.SYSTEM_REMINDER,
        EventKind.EXTERNAL_CHANNEL_MESSAGE,
        EventKind.EXTERNAL_CHANNEL_MESSAGE,
    ]
    assert [
        event.payload.prompt_role
        for event in promoted_events
        if isinstance(event.payload, ExternalChannelMessagePayload)
    ] == ["context", "invocation"]
    assert profiles == []


@pytest.mark.asyncio
async def test_poll_run_inputs_defers_append_after_empty_read_to_next_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An append after an empty read is consumed by the next leased wake-up."""
    executor = _executor()
    profiles = [
        PendingInputInferenceProfile(
            mailbox_item_id=None,
            requires_inference=False,
            exists=False,
            requested_inference_profile=None,
        ),
        PendingInputInferenceProfile(
            mailbox_item_id="appended-buffer",
            requires_inference=True,
            exists=True,
            requested_inference_profile=None,
        ),
        PendingInputInferenceProfile(
            mailbox_item_id=None,
            requires_inference=False,
            exists=False,
            requested_inference_profile=None,
        ),
    ]
    promoted_buffer_ids: list[str] = []

    async def peek(session_id: str) -> PendingInputInferenceProfile:
        assert session_id == "session-1"
        return profiles.pop(0)

    async def promote(*args: object, **kwargs: object) -> PromotedMailboxItems:
        del args
        pending = cast(PendingInputInferenceProfile, kwargs["pending"])
        assert pending.mailbox_item_id is not None
        promoted_buffer_ids.append(pending.mailbox_item_id)
        return PromotedMailboxItems(
            operation_action=None,
            turn_effect=TurnEffect.ELIGIBLE,
            requested_inference_profile=None,
            promoted_event_ids=["appended-event"],
            user_messages=[],
            events=[],
            deleted_buffer_ids=[pending.mailbox_item_id],
            changed_session_agent_ids=[],
            claimed_count=1,
            inserted_count=1,
            deduped_count=0,
            complete_run=False,
            suppress_parent_result=False,
        )

    async def has_actionable_model_input(session_id: str) -> bool:
        assert session_id == "session-1"
        return True

    monkeypatch.setattr(
        executor.mailbox_item_service,
        "peek_pending_inference_profile",
        peek,
    )
    monkeypatch.setattr(executor, "_promote_mailbox_items", promote)
    monkeypatch.setattr(
        executor,
        "_has_actionable_model_input",
        has_actionable_model_input,
    )

    first = await executor.poll_run_inputs(
        agent_id="agent-1",
        session_id="session-1",
        model="gpt-test",
        required_inference_profile=None,
        active_run_id=None,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        initial_turn_eligible=False,
        poll_fn=None,
        process_actions=False,
        dispatch_event=_noop_dispatch_event,
    )
    second = await executor.poll_run_inputs(
        agent_id="agent-1",
        session_id="session-1",
        model="gpt-test",
        required_inference_profile=None,
        active_run_id=None,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        initial_turn_eligible=False,
        poll_fn=None,
        process_actions=False,
        dispatch_event=_noop_dispatch_event,
    )

    assert first.has_actionable_work is False
    assert second.has_actionable_work is True
    assert promoted_buffer_ids == ["appended-buffer"]
    assert profiles == []


@pytest.mark.asyncio
async def test_poll_run_inputs_continues_fifo_after_failed_turn_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed TurnActions are marked failed and the next FIFO input is promoted."""
    executor = _executor()
    user_message = make_run_user_message(
        sender_user_id=None,
        content="continue after failed action",
        metadata={},
        attachments=[],
        external_id="buffer-user",
        attachment_source="mailbox_item",
        requested_inference_profile=None,
    )
    promoted_batches = [
        PromotedMailboxItems(
            operation_action=None,
            turn_effect=TurnEffect.FAILED,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            events=[],
            deleted_buffer_ids=["buffer-action"],
            changed_session_agent_ids=[],
            claimed_count=1,
            inserted_count=0,
            deduped_count=0,
            complete_run=False,
            suppress_parent_result=False,
        ),
        PromotedMailboxItems(
            operation_action=None,
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
            changed_session_agent_ids=[],
            claimed_count=1,
            inserted_count=1,
            deduped_count=0,
            complete_run=False,
            suppress_parent_result=False,
        ),
        PromotedMailboxItems(
            operation_action=None,
            turn_effect=TurnEffect.NEUTRAL,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            events=[],
            deleted_buffer_ids=[],
            changed_session_agent_ids=[],
            claimed_count=0,
            inserted_count=0,
            deduped_count=0,
            complete_run=False,
            suppress_parent_result=False,
        ),
    ]
    processed_operation_actions: list[object | None] = []

    async def promote(*args: object, **kwargs: object) -> PromotedMailboxItems:
        del args, kwargs
        return promoted_batches.pop(0)

    async def process_operation_actions(
        *args: object,
        **kwargs: object,
    ) -> OperationActionProcessResult:
        del args
        processed_operation_actions.append(kwargs["operation_action"])
        return OperationActionProcessResult(
            context_invalidated=False,
            complete_run=False,
        )

    async def has_actionable_model_input(session_id: str) -> bool:
        del session_id
        return False

    monkeypatch.setattr(executor, "_promote_mailbox_items", promote)
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        initial_turn_eligible=False,
        poll_fn=None,
        process_actions=True,
        dispatch_event=_noop_dispatch_event,
    )

    assert result.user_messages == [user_message]
    assert result.has_actionable_work is True
    assert result.context_invalidated is False
    assert result.complete_run is False
    assert processed_operation_actions == [None, None]
    assert promoted_batches == []


@pytest.mark.asyncio
async def test_poll_run_inputs_stops_fifo_after_bridge_action_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bridge terminal result stops FIFO promotion and queued polling."""
    executor = _executor()
    promoted_batches = [
        PromotedMailboxItems(
            operation_action=None,
            turn_effect=TurnEffect.NEUTRAL,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            events=[],
            deleted_buffer_ids=["buffer-action"],
            changed_session_agent_ids=[],
            claimed_count=1,
            inserted_count=0,
            deduped_count=0,
            complete_run=False,
            suppress_parent_result=False,
        )
    ]
    process_calls = 0
    queued_poll_calls = 0

    async def promote(*args: object, **kwargs: object) -> PromotedMailboxItems:
        del args, kwargs
        return promoted_batches.pop(0)

    async def process_operation_actions(
        *args: object,
        **kwargs: object,
    ) -> OperationActionProcessResult:
        nonlocal process_calls
        del args, kwargs
        process_calls += 1
        return OperationActionProcessResult(
            context_invalidated=False,
            complete_run=True,
        )

    async def queued_poll() -> PollMessagesResult:
        nonlocal queued_poll_calls
        queued_poll_calls += 1
        return PollMessagesResult(
            user_messages=[],
            context_invalidated=False,
            complete_run=False,
            suppress_parent_result=False,
        )

    async def has_actionable_model_input(session_id: str) -> bool:
        del session_id
        raise AssertionError("A completed bridge run has no same-Run model input")

    monkeypatch.setattr(executor, "_promote_mailbox_items", promote)
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
        active_run_id="run-1",
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        initial_turn_eligible=True,
        poll_fn=queued_poll,
        process_actions=True,
        dispatch_event=_noop_dispatch_event,
    )

    assert result.complete_run is True
    assert result.context_invalidated is False
    assert result.has_actionable_work is False
    assert process_calls == 1
    assert queued_poll_calls == 0
    assert promoted_batches == []


@pytest.mark.asyncio
async def test_poll_run_inputs_completes_predecessor_without_promoting_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery leaves a fenced continuation pending and completes its predecessor."""
    executor = _executor()
    promoted_batches = [
        PromotedMailboxItems(
            operation_action=None,
            turn_effect=TurnEffect.NEUTRAL,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            events=[],
            deleted_buffer_ids=[],
            changed_session_agent_ids=[],
            claimed_count=0,
            inserted_count=0,
            deduped_count=0,
            complete_run=True,
            suppress_parent_result=True,
        )
    ]
    queued_poll_calls = 0

    async def promote(*args: object, **kwargs: object) -> PromotedMailboxItems:
        del args, kwargs
        return promoted_batches.pop(0)

    async def queued_poll() -> PollMessagesResult:
        nonlocal queued_poll_calls
        queued_poll_calls += 1
        return PollMessagesResult(
            user_messages=[],
            context_invalidated=False,
            complete_run=False,
            suppress_parent_result=False,
        )

    async def has_actionable_model_input(session_id: str) -> bool:
        del session_id
        raise AssertionError("A fenced predecessor cannot continue model execution")

    monkeypatch.setattr(executor, "_promote_mailbox_items", promote)
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        initial_turn_eligible=True,
        poll_fn=queued_poll,
        process_actions=True,
        dispatch_event=_noop_dispatch_event,
    )

    assert result.complete_run is True
    assert result.suppress_parent_result is True
    assert result.context_invalidated is False
    assert result.has_actionable_work is False
    assert queued_poll_calls == 0
    assert promoted_batches == []


@pytest.mark.asyncio
async def test_poll_run_inputs_consumes_mixed_eligible_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed eligible inputs are consumed in FIFO order at one boundary."""
    executor = _executor()
    profiles = [
        PendingInputInferenceProfile(
            mailbox_item_id="buffer-external",
            requires_inference=True,
            exists=True,
            requested_inference_profile=None,
        ),
        PendingInputInferenceProfile(
            mailbox_item_id="buffer-ordinary",
            requires_inference=True,
            exists=True,
            requested_inference_profile=None,
        ),
        PendingInputInferenceProfile(
            mailbox_item_id=None,
            requires_inference=False,
            exists=False,
            requested_inference_profile=None,
        ),
    ]
    promoted_batches = [
        PromotedMailboxItems(
            operation_action=None,
            turn_effect=TurnEffect.ELIGIBLE,
            requested_inference_profile=None,
            promoted_event_ids=["external-event"],
            user_messages=[],
            events=[],
            deleted_buffer_ids=["buffer-external"],
            changed_session_agent_ids=[],
            claimed_count=1,
            inserted_count=1,
            deduped_count=0,
            complete_run=False,
            suppress_parent_result=False,
        ),
        PromotedMailboxItems(
            operation_action=None,
            turn_effect=TurnEffect.ELIGIBLE,
            requested_inference_profile=None,
            promoted_event_ids=["ordinary-event"],
            user_messages=[],
            events=[],
            deleted_buffer_ids=["buffer-ordinary"],
            changed_session_agent_ids=[],
            claimed_count=1,
            inserted_count=1,
            deduped_count=0,
            complete_run=False,
            suppress_parent_result=False,
        ),
    ]

    async def peek(session_id: str) -> PendingInputInferenceProfile:
        assert session_id == "session-1"
        return profiles.pop(0)

    async def promote(*args: object, **kwargs: object) -> PromotedMailboxItems:
        del args, kwargs
        return promoted_batches.pop(0)

    async def has_actionable_model_input(session_id: str) -> bool:
        assert session_id == "session-1"
        return True

    monkeypatch.setattr(
        executor.mailbox_item_service,
        "peek_pending_inference_profile",
        peek,
    )
    monkeypatch.setattr(executor, "_promote_mailbox_items", promote)
    monkeypatch.setattr(
        executor,
        "_has_actionable_model_input",
        has_actionable_model_input,
    )

    await executor.poll_run_inputs(
        agent_id="agent-1",
        session_id="session-1",
        model="gpt-test",
        required_inference_profile=None,
        active_run_id="run-1",
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        initial_turn_eligible=False,
        poll_fn=None,
        process_actions=False,
        dispatch_event=_noop_dispatch_event,
    )

    assert profiles == []
    assert promoted_batches == []


@pytest.mark.asyncio
async def test_poll_run_inputs_publishes_acknowledgment_after_promotion_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Committed cursor changes notify viewers without failing on one error."""
    root_agent = SimpleNamespace(
        id="root-agent",
        root_session_agent_id="root-agent",
        agent_session_id="root-session",
    )
    child_agent = SimpleNamespace(
        id="child-agent",
        root_session_agent_id="root-agent",
        agent_session_id="child-session",
    )
    session_repository = _AgentSessionRepository(
        current_session_agent=root_agent,
        tree_session_agents=[root_agent, child_agent],
    )
    executor = _executor(agent_session_repository=session_repository)
    order: list[str] = []
    promoted_batches = [
        PromotedMailboxItems(
            operation_action=None,
            turn_effect=TurnEffect.NEUTRAL,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            events=[],
            deleted_buffer_ids=["buffer-result"],
            changed_session_agent_ids=["child-agent"],
            claimed_count=1,
            inserted_count=1,
            deduped_count=0,
            complete_run=False,
            suppress_parent_result=False,
        ),
        PromotedMailboxItems(
            operation_action=None,
            turn_effect=TurnEffect.NEUTRAL,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            events=[],
            deleted_buffer_ids=[],
            changed_session_agent_ids=[],
            claimed_count=0,
            inserted_count=0,
            deduped_count=0,
            complete_run=False,
            suppress_parent_result=False,
        ),
    ]

    async def promote(*args: object, **kwargs: object) -> PromotedMailboxItems:
        del args, kwargs
        result = promoted_batches.pop(0)
        order.append("promotion_committed")
        return result

    async def has_actionable_model_input(session_id: str) -> bool:
        del session_id
        return False

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        assert isinstance(event, SubagentTreeChanged)
        order.append(f"dispatch:{session_id}:{event.changed_session_agent_id}")
        if session_id == "child-session":
            raise RuntimeError("viewer unavailable")

    monkeypatch.setattr(executor, "_promote_mailbox_items", promote)
    monkeypatch.setattr(
        executor,
        "_has_actionable_model_input",
        has_actionable_model_input,
    )

    await executor.poll_run_inputs(
        agent_id="agent-1",
        session_id="root-session",
        model="gpt-test",
        required_inference_profile=None,
        active_run_id="run-1",
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        initial_turn_eligible=True,
        poll_fn=None,
        process_actions=False,
        dispatch_event=dispatch_event,
    )

    assert order == [
        "promotion_committed",
        "dispatch:child-session:child-agent",
        "dispatch:root-session:child-agent",
        "promotion_committed",
    ]
    assert promoted_batches == []


@pytest.mark.asyncio
async def test_poll_run_inputs_completes_run_after_terminal_preparation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A handled preparation failure completes the active run without retry."""
    executor = _executor()
    promoted_batches = [
        PromotedMailboxItems(
            operation_action=None,
            turn_effect=TurnEffect.FAILED,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            events=[],
            deleted_buffer_ids=["buffer-failed"],
            changed_session_agent_ids=[],
            claimed_count=1,
            inserted_count=1,
            deduped_count=0,
            complete_run=False,
            suppress_parent_result=False,
        ),
        PromotedMailboxItems(
            operation_action=None,
            turn_effect=TurnEffect.NEUTRAL,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            events=[],
            deleted_buffer_ids=[],
            changed_session_agent_ids=[],
            claimed_count=0,
            inserted_count=0,
            deduped_count=0,
            complete_run=False,
            suppress_parent_result=False,
        ),
    ]

    async def promote(*args: object, **kwargs: object) -> PromotedMailboxItems:
        del args, kwargs
        return promoted_batches.pop(0)

    async def has_actionable_model_input(session_id: str) -> bool:
        del session_id
        return False

    monkeypatch.setattr(executor, "_promote_mailbox_items", promote)
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        initial_turn_eligible=False,
        poll_fn=None,
        process_actions=False,
        dispatch_event=_noop_dispatch_event,
    )

    assert result.complete_run is True
    assert result.has_actionable_work is False
    assert result.context_invalidated is False
    assert promoted_batches == []


@pytest.mark.asyncio
async def test_execute_cancels_pending_run_after_terminal_preparation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed initial preparation cannot leave a recoverable pending run."""
    lifecycle = _SessionLifecycle()
    executor = _executor(session_lifecycle=lifecycle)
    dispatched: list[PublishedEvent] = []

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=True,
            suppress_parent_result=False,
            requested_inference_profile=None,
            promoted_event_ids=["failure-event"],
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert lifecycle.cancelled_pending_run_ids == [result.run_id]
    assert lifecycle.terminal_runs == []
    assert result.terminal_run_status is AgentRunStatus.CANCELLED
    assert any(isinstance(event, RunComplete) for event in dispatched)


@pytest.mark.parametrize(
    ("run_status", "expected_terminal_status"),
    [
        (AgentRunStatus.PENDING, AgentRunStatus.CANCELLED),
        (AgentRunStatus.RUNNING, AgentRunStatus.COMPLETED),
    ],
)
@pytest.mark.asyncio
async def test_execute_suppresses_recovered_bridge_predecessor_result(
    monkeypatch: pytest.MonkeyPatch,
    run_status: AgentRunStatus,
    expected_terminal_status: AgentRunStatus,
) -> None:
    """Recovery terminalizes a bridge predecessor without parent delivery."""
    recoverable_run = _PendingRun(
        status=run_status,
        resolved_model_selection=(
            make_test_model_selection()
            if run_status is AgentRunStatus.RUNNING
            else None
        ),
        effective_context_window_tokens=(
            128_000 if run_status is AgentRunStatus.RUNNING else None
        ),
        effective_auto_compaction_threshold_tokens=(
            102_400 if run_status is AgentRunStatus.RUNNING else None
        ),
        resolved_at=(
            datetime.datetime.now(datetime.UTC)
            if run_status is AgentRunStatus.RUNNING
            else None
        ),
    )
    lifecycle = _SessionLifecycle(recoverable_run=recoverable_run)
    executor = _executor(session_lifecycle=lifecycle)
    dispatched: list[PublishedEvent] = []

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=True,
            suppress_parent_result=True,
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

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id
        dispatched.append(event)

    result = await executor.execute(
        _message(recoverable_run=recoverable_run),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert lifecycle.completed_bridge_predecessors == [recoverable_run.id]
    assert lifecycle.cancelled_pending_run_ids == []
    assert lifecycle.terminal_runs == []
    assert result.terminal_run_status is expected_terminal_status
    assert any(isinstance(event, RunComplete) for event in dispatched)


@pytest.mark.parametrize(
    (
        "recoverable_run",
        "pending_input_exists",
        "expected_pending_run_create_calls",
    ),
    [
        (None, False, 1),
        (_PendingRun(), False, 0),
        (None, True, 1),
    ],
    ids=["fresh", "recoverable", "pending-neutral-input"],
)
@pytest.mark.asyncio
async def test_execute_preserves_actionable_transcript_eligibility(
    monkeypatch: pytest.MonkeyPatch,
    recoverable_run: _PendingRun | None,
    pending_input_exists: bool,
    expected_pending_run_create_calls: int,
) -> None:
    """A direct control event remains eligible across pending-run states."""
    order: list[str] = []
    lifecycle = _SessionLifecycle(order, recoverable_run=recoverable_run)
    engine = _RecordingEngine(order)
    executor = _executor(lifecycle, engine=engine)
    initial_turn_eligibility: list[bool] = []

    async def peek_pending_input(
        session_id: str,
    ) -> PendingInputInferenceProfile:
        del session_id
        return PendingInputInferenceProfile(
            mailbox_item_id="buffer-1" if pending_input_exists else None,
            exists=pending_input_exists,
            requires_inference=False,
            requested_inference_profile=None,
        )

    async def has_actionable_model_input(session_id: str) -> bool:
        assert session_id == "session-001"
        return True

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args
        initial_turn_eligibility.append(cast(bool, kwargs["initial_turn_eligible"]))
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            suppress_parent_result=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            has_actionable_work=True,
        )

    monkeypatch.setattr(
        executor.mailbox_item_service,
        "peek_pending_inference_profile",
        peek_pending_input,
    )
    monkeypatch.setattr(
        executor,
        "_has_actionable_model_input",
        has_actionable_model_input,
    )
    monkeypatch.setattr(executor, "poll_run_inputs", poll_run_inputs)
    _patch_successful_resolution(monkeypatch)

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id, event

    result = await executor.execute(
        _message(recoverable_run=recoverable_run),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert initial_turn_eligibility == [True]
    assert "provider" in order
    assert lifecycle.pending_run_create_calls == expected_pending_run_create_calls
    assert result.terminal_run_status is AgentRunStatus.COMPLETED


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
            suppress_parent_result=False,
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
        _message(),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=cast(asyncio.Event, object()),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
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
                    model_call_started_at=None,
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
        _message(pending_command=_pending_command()),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert len(handler.requests) == 1
    assert len(handler.contexts) == 1
    assert lifecycle.activation_phases == [AgentRunPhase.COMPACTING]
    run_id = result.run_id
    assert run_id is not None
    assert handler.contexts[0].run_id == run_id
    assert lifecycle.activities == [
        ("session-001", run_id, AgentRunPhase.COMPACTING),
        ("session-001", run_id, AgentRunPhase.NORMALIZING_OUTPUT),
    ]
    initial_live_run = live_event_projector.live_run_updates[0][1]
    assert initial_live_run.operation is not None
    assert initial_live_run.operation.kind == "preparing_context"
    assert initial_live_run.operation.operation_id == f"{run_id}:preparing-context"
    assert initial_live_run.operation.status == "running"
    assert live_event_projector.live_run_updates[-1][1].operation is None
    assert [type(event).__name__ for _, event in dispatched] == [
        "RunStarted",
        "RunPhaseChanged",
        "RunComplete",
    ]
    assert live_event_projector.flushed_session_ids == ["session-001"]
    assert lifecycle.cleared_session_ids == []
    assert lifecycle.terminal_runs == [(run_id, AgentRunStatus.COMPLETED)]
    assert result.terminal_run_status == AgentRunStatus.COMPLETED
    assert lifecycle.cleared_commands == [("session-001", "command-001")]


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
        _message(pending_command=_pending_command()),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
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
    assert lifecycle.cleared_commands == [("session-001", "command-001")]
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
        _message(pending_command=_pending_command()),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
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
    assert lifecycle.cleared_commands == [("session-001", "command-001")]


@pytest.mark.asyncio
async def test_execute_stop_wins_race_with_terminal_command_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Stop fenced by the failed finalizer completes the Run as stopped."""
    _patch_successful_resolution(monkeypatch)
    lifecycle = _SessionLifecycle()
    finalizer = _FailedRunFinalizer(claimed=False)
    user_stop_finalizer = _UserStopFinalizer()
    executor = _executor(
        lifecycle,
        command_registry={"compact": cast(CommandHandler, _FailingCommandHandler())},
        failed_run_finalizer=finalizer,
        user_stop_finalizer=user_stop_finalizer,
        failed_run_max_retries=1,
    )

    result = await executor.execute(
        _message(pending_command=_pending_command()),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=_noop_dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert len(finalizer.inputs) == 1
    assert result.run_id is not None
    assert user_stop_finalizer.interrupted_runs == [("session-001", result.run_id)]
    assert result.terminal_run_status is AgentRunStatus.STOPPED


@pytest.mark.asyncio
async def test_execute_preserves_compaction_timeout_failure_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manual compaction timeouts retain their stable retry classification."""
    _patch_successful_resolution(monkeypatch)
    timeout = ModelStreamTimeoutError(
        timeout_kind="parsed_event_idle",
        deadline_seconds=5,
        elapsed_seconds=5,
        call_kind="compaction",
        provider="openai",
        model="gpt-test",
    )
    finalizer = _FailedRunFinalizer()
    executor = _executor(
        command_registry={
            "compact": cast(
                CommandHandler,
                _FailingCommandHandler(CompactionModelStreamTimeoutError(timeout)),
            )
        },
        failed_run_finalizer=finalizer,
        failed_run_max_retries=0,
    )

    result = await executor.execute(
        _message(pending_command=_pending_command()),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=_noop_dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert result.terminal_run_status is AgentRunStatus.FAILED
    assert len(finalizer.inputs) == 1
    attempt = finalizer.inputs[0].retry_state.attempts[0]
    assert attempt.source == "model"
    assert attempt.retryability == "transient"
    assert attempt.failure_code == "model_stream_idle_timeout"
    assert finalizer.inputs[0].reason == "retry_exhausted"


@pytest.mark.asyncio
async def test_execute_clears_live_projection_after_run_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RunComplete clears live projection while idle owns activity cleanup."""
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
    message = _message()

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            suppress_parent_result=False,
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert [binding.slug for binding in result.toolkits] == ["wait"]
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
    assert order == ["activate_pending"]
    assert live_event_projector.live_run_clears == [("session-001", result.run_id)]


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
        payload=UserMessagePayload(
            sender_user_id=None, content="", metadata={"source": "goal"}
        ),
        created_at=run_executor_module.tznow(),
    )

    assert has_actionable_tail([run_marker, continuation])


def test_actionable_tail_detects_goal_update_after_run_marker() -> None:
    """A Goal resume event after a run marker must wake the model."""
    run_marker = Event(
        id="1123456789abcdef0123456789abcdea",
        session_id="session-1",
        kind=EventKind.RUN_MARKER,
        payload=RunMarkerPayload(run_id="run-1", status="completed"),
        created_at=run_executor_module.tznow(),
    )
    goal_update = Event(
        id="1123456789abcdef0123456789abcdeb",
        session_id="session-1",
        kind=EventKind.GOAL_UPDATED,
        payload=UserMessagePayload(
            sender_user_id=None,
            content="",
            metadata={
                "source": "goal",
                "goal_control_action": "resume",
                "previous_goal_status": "blocked",
            },
        ),
        created_at=run_executor_module.tznow(),
    )

    assert has_actionable_tail([run_marker, goal_update])


@pytest.mark.asyncio
async def test_run_session_heartbeat_loop_refreshes_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RunExecutor refreshes session heartbeat during engine execution."""
    lifecycle = _SessionLifecycle()
    monkeypatch.setattr(run_executor_module, "_RUN_HEARTBEAT_INTERVAL_SECONDS", 0.01)
    executor = _executor(session_lifecycle=lifecycle)

    task = asyncio.create_task(
        executor._run_session_heartbeat_loop(
            "session-001",
            owner_generation=1,
        )
    )
    try:
        await asyncio.wait_for(lifecycle.second_heartbeat.wait(), timeout=1)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert lifecycle.heartbeat_session_ids[:2] == ["session-001", "session-001"]


def test_failed_run_attempt_classifies_typed_non_retryable_model_error() -> None:
    """Typed deterministic non-provider failures still finalize immediately."""
    executor = _executor()

    attempt = executor._failed_run_attempt_from_user_visible_error(
        _SyntheticNonRetryableModelCallError("request rejected"),
        attempt_number=1,
        source="model",
    )

    assert attempt.retryability == "non_retryable"
    assert attempt.failure_code == "synthetic_invalid_request"
    assert attempt.user_message == "request rejected"


@pytest.mark.asyncio
async def test_provider_failure_uses_full_budget_despite_retryability() -> None:
    """Provider diagnostics never reduce the configured retry budget."""
    executor = _executor(failed_run_max_retries=2)
    failure = model_provider_failure(
        operation="sampling",
        provider="openai",
        model="gpt-4o",
        integration="integration-001",
        provider_message="The request is invalid.",
        status_code=400,
        provider_code="invalid_request",
        provider_error_type="bad_request",
        provider_error_param=None,
    )
    retry_state: FailedRunRetryState | None = None
    finalization_reasons: list[str | None] = []

    for attempt_number in range(1, 4):
        # Exercise provider policy at the retry boundary.
        attempt = executor._failed_run_attempt_from_user_visible_error(
            failure,
            attempt_number=attempt_number,
            source="model",
        )
        # Exercise durable retry policy directly.
        retry_state = await executor._record_failed_run_attempt(
            session_id="session-001",
            run_id="run-001",
            owner_generation=1,
            attempt=attempt,
            previous_retry_state=retry_state,
        )
        finalization_reasons.append(
            run_executor_module._failed_run_finalization_reason(
                retry_state
            )  # Verify the full-budget terminal boundary.
        )

    assert retry_state is not None
    assert retry_state.retryability == "non_retryable"
    assert retry_state.provider_failure is not None
    assert [attempt.backoff_seconds for attempt in retry_state.attempts] == [1, 2, 4]
    assert finalization_reasons == [None, None, "retry_exhausted"]


@pytest.mark.asyncio
async def test_timeout_failure_uses_full_budget_with_stable_attempt_codes() -> None:
    """Timeout attempts retain their stable code through retry exhaustion."""
    executor = _executor(failed_run_max_retries=3)
    failure = ModelStreamTimeoutError(
        timeout_kind="parsed_event_idle",
        deadline_seconds=5,
        elapsed_seconds=5,
        call_kind="sampling",
        provider="openai",
        model="gpt-test",
    )
    retry_state: FailedRunRetryState | None = None

    for attempt_number in range(1, 5):
        # Exercise timeout classification at the retry boundary.
        attempt = executor._failed_run_attempt_from_user_visible_error(
            failure,
            attempt_number=attempt_number,
            source="model",
        )
        # Exercise durable timeout history directly.
        retry_state = await executor._record_failed_run_attempt(
            session_id="session-001",
            run_id="run-001",
            owner_generation=1,
            attempt=attempt,
            previous_retry_state=retry_state,
        )

    assert retry_state is not None
    assert [attempt.attempt_number for attempt in retry_state.attempts] == [1, 2, 3, 4]
    assert {attempt.failure_code for attempt in retry_state.attempts} == {
        "model_stream_idle_timeout"
    }
    assert all(attempt.retryability == "transient" for attempt in retry_state.attempts)
    assert (
        run_executor_module._failed_run_finalization_reason(
            retry_state
        )  # Verify the terminal retry boundary.
        == "retry_exhausted"
    )


@pytest.mark.asyncio
async def test_execute_retries_failed_run_without_durable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed attempt persists retry state and retries without durable error."""
    monkeypatch.setattr(run_executor_module, "_FAILED_RUN_RETRY_WAIT_POLL_SECONDS", 0)
    lifecycle = _SessionLifecycle()
    engine = _FlakyEngine(
        _SyntheticTransientModelCallError("model temporarily unavailable")
    )
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
            suppress_parent_result=False,
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
        _message(),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert engine.calls == 2
    assert result.terminal_run_status == AgentRunStatus.COMPLETED
    assert len(lifecycle.retry_states) == 1
    retry_state = lifecycle.retry_states[0]
    assert retry_state is not None
    assert retry_state.failed_attempt_count == 1
    assert retry_state.last_user_message == "model temporarily unavailable"
    assert retry_state.retryability == "transient"
    assert retry_state.failure_code == "synthetic_transport_failure"
    retry_updates = [
        run.retry
        for _, run in live_event_projector.live_run_updates
        if run.retry is not None
    ]
    assert len(retry_updates) == 1
    assert retry_updates[0].last_error_message == "model temporarily unavailable"
    assert retry_updates[0].attempts[0].user_message == "model temporarily unavailable"
    retry_live_runs = [
        run for _, run in live_event_projector.live_run_updates if run.retry is not None
    ]
    assert retry_live_runs[0].model_call_started_at is None
    assert live_event_projector.projection_operations == ["discard", "retry_update"]
    assert live_event_projector.live_run_clears == [("session-001", result.run_id)]
    assert finalizer.inputs == []
    assert not any(
        isinstance(event, Event) and event.kind == EventKind.SYSTEM_ERROR
        for event in dispatched
    )


@pytest.mark.asyncio
async def test_execute_resets_retry_budget_after_successful_model_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later model turn starts a fresh failed-attempt history and count."""
    monkeypatch.setattr(run_executor_module, "_FAILED_RUN_RETRY_WAIT_POLL_SECONDS", 0)
    lifecycle = _SessionLifecycle()
    engine = _RetryAcrossTurnsEngine()
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
            suppress_parent_result=False,
            requested_inference_profile=None,
            promoted_event_ids=[],
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert result.terminal_run_status == AgentRunStatus.COMPLETED
    assert engine.calls == 3
    retry_states = [state for state in lifecycle.retry_states if state is not None]
    assert [state.failed_attempt_count for state in retry_states] == [1, 1]
    attempt_numbers = [
        [attempt.attempt_number for attempt in state.attempts] for state in retry_states
    ]
    assert attempt_numbers == [[1], [1]]
    assert [state.last_user_message for state in retry_states] == [
        "first turn temporarily unavailable",
        "second turn temporarily unavailable",
    ]

    live_runs = [run for _, run in live_event_projector.live_run_updates]
    first_retry_index = next(
        index
        for index, run in enumerate(live_runs)
        if run.retry is not None
        and run.retry.last_error_message == "first turn temporarily unavailable"
    )
    second_retry_index = next(
        index
        for index, run in enumerate(live_runs)
        if run.retry is not None
        and run.retry.last_error_message == "second turn temporarily unavailable"
    )
    assert any(
        run.retry is None
        for run in live_runs[first_retry_index + 1 : second_retry_index]
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
            suppress_parent_result=False,
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
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
    assert live_event_projector.projection_operations == ["discard", "retry_update"]
    assert all(
        run.inference_profile
        == AppliedInferenceProfile(
            model_target_label="default",
            model_display_name="gpt-4o",
            reasoning_effort=None,
        )
        for _, run in live_event_projector.live_run_updates
    )
    assert live_event_projector.live_run_clears == [("session-001", result.run_id)]
    latest_live_run = live_event_projector.live_run_updates[-1][1]
    wire_event = chat_live_run_updated_dump("session-001", latest_live_run)
    wire_run = wire_event["run"]
    assert is_string_object_dict(wire_run)
    assert wire_run["inference_profile"] == {
        "model_target_label": "default",
        "model_display_name": "gpt-4o",
        "reasoning_effort": None,
    }


@pytest.mark.asyncio
async def test_record_provider_failure_logs_safe_structured_attempt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every provider failure attempt emits one safe structured warning."""
    lifecycle = _SessionLifecycle()
    executor = _executor(lifecycle)
    failure = model_provider_failure(
        operation="sampling",
        provider="openai",
        model="gpt-4o",
        integration="integration-001",
        provider_message="The provider is temporarily unavailable.",
        status_code=503,
        provider_code="server_error",
        provider_error_type="api_error",
        provider_error_param=None,
    )
    # Exercise provider-attempt logging directly.
    attempt = executor._failed_run_attempt_from_user_visible_error(
        failure,
        attempt_number=1,
        source="model",
    )

    with caplog.at_level(logging.WARNING, logger=run_executor_module.__name__):
        # Exercise provider-attempt logging directly.
        await executor._record_failed_run_attempt(
            session_id="session-001",
            run_id="run-001",
            owner_generation=1,
            attempt=attempt,
            previous_retry_state=None,
        )

    records = [
        record
        for record in caplog.records
        if record.getMessage() == "Model provider attempt failed"
    ]
    assert len(records) == 1
    record = records[0]
    log_fields = record.__dict__
    assert record.levelno == logging.WARNING
    assert log_fields["session_id"] == "session-001"
    assert log_fields["run_id"] == "run-001"
    assert log_fields["attempt_number"] == 1
    assert log_fields["provider_failure_operation"] == "sampling"
    assert log_fields["provider_failure_provider"] == "openai"
    assert log_fields["provider_failure_integration"] == "integration-001"
    assert log_fields["provider_failure_model"] == "gpt-4o"
    assert log_fields["provider_failure_category"] == "provider_unavailable"
    assert log_fields["provider_failure_retryability"] == "transient"
    assert log_fields["provider_failure_status_code"] == 503
    assert log_fields["provider_failure_code"] == "server_error"
    assert log_fields["provider_failure_error_type"] == "api_error"
    assert log_fields["provider_failure_message"] == (
        "The provider is temporarily unavailable."
    )
    assert log_fields["provider_failure_fingerprint"] == failure.fingerprint
    assert log_fields["provider_failure_retry_outcome"] == "scheduled"
    assert record.getMessage() == "Model provider attempt failed"


def test_chat_live_retry_state_hides_provider_diagnostic_taxonomy() -> None:
    """Provider retry projections expose only the public presentation contract."""
    executor = _executor(_SessionLifecycle())
    failure = model_provider_failure(
        operation="sampling",
        provider="openai",
        model="gpt-4o",
        integration="integration-001",
        provider_message="The provider is temporarily unavailable.",
        status_code=503,
        provider_code="server_error",
        provider_error_type="api_error",
        provider_error_param=None,
    )
    # Exercise the live provider retry projection directly.
    attempt = executor._failed_run_attempt_from_user_visible_error(
        failure,
        attempt_number=1,
        source="model",
    )
    retry_state = FailedRunRetryState.from_attempt(
        attempt,
        max_retries=10,
        backoff_seconds=1,
        next_retry_at=attempt.occurred_at + datetime.timedelta(seconds=1),
    )

    # Exercise the live provider retry projection directly.
    projected = run_executor_module._chat_live_retry_state(retry_state)

    assert retry_state.retryability == "transient"
    assert retry_state.failure_code == "model_provider_provider_unavailable"
    assert projected is not None
    assert projected.error_kind == "model_provider"
    assert (
        projected.last_error_message
        == "Model provider error: The provider is temporarily unavailable."
    )
    assert len(projected.attempts) == 1
    assert projected.attempts[0].retryability == "unknown"
    assert projected.attempts[0].failure_code is None


@pytest.mark.asyncio
async def test_execute_prioritizes_stop_over_provider_failure_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A durable Stop prevents provider retry state and failed finalization."""
    monkeypatch.setattr(run_executor_module, "_FAILED_RUN_RETRY_WAIT_POLL_SECONDS", 0)
    lifecycle = _SessionLifecycle()
    failure = model_provider_failure(
        operation="sampling",
        provider="openai",
        model="gpt-4o",
        integration="integration-001",
        provider_message="The provider is temporarily unavailable.",
        status_code=503,
        provider_code="server_error",
        provider_error_type="api_error",
        provider_error_param=None,
    )
    engine = _AlwaysProviderFailingEngine(failure)
    finalizer = _FailedRunFinalizer()
    user_stop_finalizer = _UserStopFinalizer()
    live_event_projector = _LiveEventProjector()
    executor = _executor(
        lifecycle,
        engine=cast(AgentEngineProtocol, engine),
        failed_run_finalizer=finalizer,
        user_stop_finalizer=user_stop_finalizer,
        live_event_projector=live_event_projector,
    )

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            suppress_parent_result=False,
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
        _message(),
        poll_fn=None,
        check_stop=check_stop,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert engine.calls == 1
    assert result.terminal_run_status == AgentRunStatus.STOPPED
    assert lifecycle.retry_states == []
    assert finalizer.inputs == []
    assert user_stop_finalizer.interrupted_runs == [("session-001", "run-001")]
    assert user_stop_finalizer.parent_result_activity_run_ids == []
    assert live_event_projector.live_run_clears == [("session-001", "run-001")]


@pytest.mark.asyncio
async def test_execute_clears_retry_state_when_retry_emits_run_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normal RunStopped retry outcome removes earlier failed-attempt state."""
    monkeypatch.setattr(run_executor_module, "_FAILED_RUN_RETRY_WAIT_POLL_SECONDS", 0)
    _patch_successful_resolution(monkeypatch)
    lifecycle = _SessionLifecycle()
    failure = model_provider_failure(
        operation="sampling",
        provider="openai",
        model="gpt-4o",
        integration="integration-001",
        provider_message="The provider is temporarily unavailable.",
        status_code=503,
        provider_code="server_error",
        provider_error_type="api_error",
        provider_error_param=None,
    )
    engine = _ProviderFailThenStopEngine(failure)
    finalizer = _FailedRunFinalizer()
    live_event_projector = _LiveEventProjector()
    executor = _executor(
        lifecycle,
        engine=cast(AgentEngineProtocol, engine),
        failed_run_finalizer=finalizer,
        live_event_projector=live_event_projector,
    )

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            suppress_parent_result=False,
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert engine.calls == 2
    assert result.terminal_run_status == AgentRunStatus.STOPPED
    assert len(lifecycle.retry_states) == 2
    assert lifecycle.retry_states[0] is not None
    assert lifecycle.retry_states[1] is None
    assert finalizer.inputs == []
    assert live_event_projector.live_run_clears == [("session-001", "run-001")]


@pytest.mark.parametrize(
    ("max_retries", "expected_calls"),
    [(0, 1), (1, 2)],
)
@pytest.mark.asyncio
async def test_execute_finalizes_when_failed_run_retry_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    max_retries: int,
    expected_calls: int,
) -> None:
    """Retry exhaustion supports both disabled and positive retry budgets."""
    lifecycle = _SessionLifecycle()
    engine = _AlwaysFailingEngine()
    finalizer = _FailedRunFinalizer()
    executor = _executor(
        lifecycle,
        engine=cast(AgentEngineProtocol, engine),
        failed_run_finalizer=finalizer,
        failed_run_max_retries=max_retries,
    )

    async def poll_run_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            context_invalidated=False,
            complete_run=False,
            suppress_parent_result=False,
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert engine.calls == expected_calls
    assert result.terminal_run_status == AgentRunStatus.FAILED
    assert len(lifecycle.retry_states) == expected_calls
    assert len(finalizer.inputs) == 1
    retry_state = finalizer.inputs[0].retry_state
    assert retry_state.failed_attempt_count == expected_calls
    assert retry_state.max_retries == max_retries
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
            suppress_parent_result=False,
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )

    assert engine.calls == 3
    assert result.terminal_run_status == AgentRunStatus.FAILED
    assert len(lifecycle.retry_states) == 3
    final_retry_state = lifecycle.retry_states[2]
    assert final_retry_state is not None
    assert final_retry_state.failed_attempt_count == 3
    assert [attempt.attempt_number for attempt in final_retry_state.attempts] == [
        1,
        2,
        3,
    ]
    assert len(finalizer.inputs) == 1
    assert [
        attempt.attempt_number for attempt in finalizer.inputs[0].retry_state.attempts
    ] == [1, 2, 3]


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
            suppress_parent_result=False,
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
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
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
