"""Session wake-up run execution."""

import asyncio
import contextlib
import dataclasses
import datetime
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Annotated, Any

from azcommon.datetime import tznow
from fastapi import Depends
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.types import (
    PublishedEvent,
    SessionBroker,
    SessionWakeUp,
)
from azents.core.enums import (
    ActionExecutionStatus,
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionKind,
    EventKind,
)
from azents.core.inference_profile import (
    InferenceProfileFailureCode,
    InferenceProfileSource,
    RequestedInferenceProfile,
    SessionInferenceState,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.tools import (
    SessionType,
    ToolkitContext,
    ToolkitExecutionMode,
    ToolkitProvider,
)
from azents.engine.context.window import compute_auto_compaction_threshold_tokens
from azents.engine.events.action_messages import ChatAction, CreateGitWorktreeAction
from azents.engine.events.builders import make_system_error_event
from azents.engine.events.engine_adapter import AgentEngineAdapter
from azents.engine.events.engine_events import (
    RunComplete,
    RunPhaseChanged,
    RunStarted,
    RunStopped,
    SubagentTreeChanged,
)
from azents.engine.events.types import Event
from azents.engine.hooks.dispatcher import (
    RuntimeHookDispatcher,
    RuntimeHookProviderRef,
)
from azents.engine.hooks.types import (
    RunEndHookContext,
    RunEndReason,
    RunStartHookContext,
    SessionStartHookContext,
)
from azents.engine.io.user_input import RunUserMessage
from azents.engine.run.commands import CommandHandler
from azents.engine.run.contracts import (
    AgentEngineProtocol,
    RunContext,
    RunRequest,
    ToolkitBinding,
)
from azents.engine.run.emit import Emit, handle_engine_event
from azents.engine.run.errors import UserVisibleRuntimeError
from azents.engine.run.failure import (
    FailedRunAttempt,
    FailedRunAttemptSource,
    FailedRunFinalizationReason,
    FailedRunRetryability,
    FailedRunRetryState,
)
from azents.engine.run.input import InvokeInput
from azents.engine.run.resolve import (
    ModelTargetNotFound,
    ReasoningEffortUnsupported,
    resolve_agent_tools,
    resolve_invoke_input_with_profile,
    resolve_invoke_input_with_resolved_profile,
)
from azents.engine.run.types import CheckStop, PollMessages, PollMessagesResult
from azents.engine.tools.builtin import BuiltinToolkitProvider, RuntimeToolkit
from azents.engine.tools.claude_rules import ClaudeRulesToolkitProvider
from azents.engine.tools.deps import (
    get_goal_toolkit_provider,
    get_todo_toolkit_provider,
    get_toolkit_registry,
)
from azents.engine.tools.goal import GoalToolkitProvider
from azents.engine.tools.skill import SkillToolkitProvider
from azents.engine.tools.subagent import SubagentToolkitProvider
from azents.engine.tools.todo import TodoToolkitProvider
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.action_execution.data import (
    ActionExecution,
    ActionExecutionProjection,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import PendingSessionCommand
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)
from azents.repos.toolkit import AgentToolkitRepository, ToolkitRepository
from azents.runtime.types import RuntimeDomainConfig
from azents.services.chat.data import (
    ChatLiveRunRetryAttempt,
    ChatLiveRunRetryState,
    ChatLiveRunState,
)
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import (
    InputBufferPreparationStaleError,
    InputBufferService,
    PromotedInputBuffers,
    TurnEffect,
    WorktreeActionInput,
    fold_turn_eligibility,
)
from azents.services.model_file import ModelFileService
from azents.services.session_git_worktree import (
    GitWorktreeActionExecutionResult,
    SessionGitWorktreeService,
)
from azents.services.session_title import SessionTitleService
from azents.transport.chat import (
    chat_action_execution_updated_dump,
    chat_history_event_appended_dump,
    chat_live_event_removed_dump,
)
from azents.worker.config import AgentWorkerConfig
from azents.worker.deps import (
    get_broadcast,
    get_builtin_toolkit_provider,
    get_claude_rules_toolkit_provider,
    get_command_registry,
    get_exchange_file_service,
    get_skill_toolkit_provider,
    get_subagent_toolkit_provider,
    get_toolkit_repository,
    get_worker_broker,
    get_worker_config,
)
from azents.worker.live.event_projector import LiveEventProjector
from azents.worker.run.finalizer import (
    FailedRunErrorFinalizer,
    FailedRunFinalizationInput,
)
from azents.worker.run.helpers import (
    apply_active_tool_call_event,
    observed_terminal_run_event,
    user_stop_cancelled,
)
from azents.worker.run.results import RunExecutionResult
from azents.worker.session.contracts import PrepareToolkits
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.user_stop_finalizer import UserStopFinalizer

logger = logging.getLogger(__name__)
_CHAT_ACTION_ADAPTER = TypeAdapter(ChatAction)
_INTERNAL_ERROR_MESSAGE = "An internal error occurred."
_RUN_HEARTBEAT_INTERVAL_SECONDS = 30.0
_FAILED_RUN_RETRY_WAIT_POLL_SECONDS = 0.2
_FAILED_RUN_NO_FIXTURE_MATCH_CODE = "no_fixture_match"
_NON_ACTIONABLE_TAIL_EVENT_KINDS = {
    EventKind.RUN_MARKER,
    EventKind.TURN_MARKER,
    EventKind.COMPACTION_MARKER,
    EventKind.COMPACTION_SUMMARY,
    EventKind.ACTION_MESSAGE,
    EventKind.ACTION_EXECUTION_RESULT,
    EventKind.SYSTEM_ERROR,
}


@dataclasses.dataclass(frozen=True)
class RunInputPollResult:
    """Input poll result shared by wake-up entry and model boundaries."""

    user_messages: list[RunUserMessage]
    requested_inference_profile: RequestedInferenceProfile | None
    promoted_event_ids: list[str]
    has_actionable_work: bool
    context_invalidated: bool
    complete_run: bool


@dataclasses.dataclass(frozen=True)
class RequestedProfileSelection:
    """Requested profile and its durable source for a new run."""

    profile: RequestedInferenceProfile
    source: InferenceProfileSource


@dataclasses.dataclass(frozen=True)
class ProfileResolutionFailure:
    """Safe durable profile-resolution failure projection."""

    code: InferenceProfileFailureCode
    message: str


@dataclasses.dataclass(frozen=True)
class OperationActionProcessResult:
    """Result of processing promoted operation actions."""

    context_invalidated: bool


def _runtime_hook_provider_refs(
    toolkits: list[ToolkitBinding],
) -> list[RuntimeHookProviderRef]:
    """Convert toolkit bindings to runtime hook provider references."""
    return [
        RuntimeHookProviderRef(slug=binding.slug, toolkit=binding.toolkit)
        for binding in toolkits
    ]


def _refresh_runtime_peer_toolkits(toolkits: Sequence[ToolkitBinding]) -> None:
    """Attach the current managed peer snapshot to runtime shell toolkits."""
    peer_toolkits = [binding.toolkit for binding in toolkits]
    for binding in toolkits:
        if isinstance(binding.toolkit, RuntimeToolkit):
            binding.toolkit.set_peer_toolkits(
                [toolkit for toolkit in peer_toolkits if toolkit is not binding.toolkit]
            )


@dataclasses.dataclass
class RunExecutor:
    """Resolve a session wake-up and execute the engine run lifecycle."""

    broker: Annotated[SessionBroker, Depends(get_worker_broker)]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    engine: Annotated[AgentEngineProtocol, Depends(AgentEngineAdapter)]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    command_registry: Annotated[
        Mapping[str, CommandHandler], Depends(get_command_registry)
    ]
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]
    toolkit_registry: Annotated[
        dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)
    ]
    agent_toolkit_repository: Annotated[
        AgentToolkitRepository, Depends(AgentToolkitRepository)
    ]
    toolkit_repository: Annotated[ToolkitRepository, Depends(get_toolkit_repository)]
    agent_runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    session_lifecycle: Annotated[
        SessionLifecycleService, Depends(SessionLifecycleService)
    ]
    worker_config: Annotated[AgentWorkerConfig, Depends(get_worker_config)]
    exchange_file_service: Annotated[
        ExchangeFileService, Depends(get_exchange_file_service)
    ]
    model_file_service: Annotated[ModelFileService, Depends(ModelFileService)]
    input_buffer_service: Annotated[InputBufferService, Depends(InputBufferService)]
    session_git_worktree_service: Annotated[
        SessionGitWorktreeService, Depends(SessionGitWorktreeService)
    ]
    session_title_service: Annotated[SessionTitleService, Depends(SessionTitleService)]
    live_event_projector: Annotated[LiveEventProjector, Depends(LiveEventProjector)]
    user_stop_finalizer: Annotated[UserStopFinalizer, Depends(UserStopFinalizer)]
    builtin_toolkit_provider: Annotated[
        BuiltinToolkitProvider, Depends(get_builtin_toolkit_provider)
    ]
    claude_rules_toolkit_provider: Annotated[
        ClaudeRulesToolkitProvider, Depends(get_claude_rules_toolkit_provider)
    ]
    todo_toolkit_provider: Annotated[
        TodoToolkitProvider, Depends(get_todo_toolkit_provider)
    ]
    goal_toolkit_provider: Annotated[
        GoalToolkitProvider, Depends(get_goal_toolkit_provider)
    ]
    skill_toolkit_provider: Annotated[
        SkillToolkitProvider, Depends(get_skill_toolkit_provider)
    ]
    subagent_toolkit_provider: Annotated[
        SubagentToolkitProvider, Depends(get_subagent_toolkit_provider)
    ]
    broadcast: Annotated[WebSocketBroadcast, Depends(get_broadcast)]
    failed_run_finalizer: Annotated[
        FailedRunErrorFinalizer, Depends(FailedRunErrorFinalizer)
    ]
    _session_title_tasks: set[asyncio.Task[object]] = dataclasses.field(
        default_factory=set,
        init=False,
    )

    async def execute(
        self,
        message: SessionWakeUp,
        *,
        poll_fn: PollMessages | None,
        check_stop: CheckStop | None,
        prepare_toolkits: PrepareToolkits | None,
        shutdown_event: asyncio.Event,
        dispatch_event: Callable[[str, PublishedEvent], Awaitable[None]],
        command: PendingSessionCommand | None = None,
    ) -> RunExecutionResult:
        """Handle one session wake-up.

        :param message: Incoming session wake-up.
        :param poll_fn: Callback that polls for new user messages during a run.
        :param check_stop: Callback that checks whether execution should stop.
        :param prepare_toolkits: Callback that prepares session-managed toolkits.
        :param shutdown_event: Worker shutdown event.
        :param dispatch_event: Event publication callback.
        :param command: Pending runtime command to execute instead of normal model run.
        :return: Session-managed toolkits used by execution.
        """
        command_handler: CommandHandler | None = None
        if command is not None:
            command_handler = self.command_registry.get(command.name)
            if command_handler is None:
                logger.warning("Unknown command", extra={"command": command.name})
                await self._clear_pending_command(
                    message.session_id, command_id=command.id
                )
                return RunExecutionResult(
                    toolkits=[],
                    terminal_event_observed=False,
                    no_actionable_work=False,
                )

        loop = asyncio.get_running_loop()
        preparation_started_at = loop.time()
        boundary_started_at = preparation_started_at
        recoverable_run = await self.session_lifecycle.claim_recoverable_agent_run(
            message.session_id
        )
        created_run = recoverable_run is None
        async with self.session_manager() as db_session:
            session_state = await self.agent_session_repository.get_by_id(
                db_session, message.session_id
            )
        if session_state is None:
            raise ValueError("AgentSession not found")

        if (
            recoverable_run is not None
            and recoverable_run.status == AgentRunStatus.RUNNING
        ):
            if session_state.inference_state is None:
                raise ValueError(
                    "Running AgentRun has no prepared Session inference state"
                )
            turn_inference_state = session_state.inference_state
            selected_profile = RequestedProfileSelection(
                profile=RequestedInferenceProfile(
                    model_target_label=turn_inference_state.model_target_label,
                    reasoning_effort=turn_inference_state.reasoning_effort,
                ),
                source=InferenceProfileSource.SESSION_LAST_USED,
            )
            if command is None:
                pending_input = (
                    await self.input_buffer_service.peek_pending_inference_profile(
                        message.session_id
                    )
                )
                if (
                    pending_input.requested_inference_profile is not None
                    and pending_input.requested_inference_profile
                    != selected_profile.profile
                ):
                    selected_profile = RequestedProfileSelection(
                        profile=pending_input.requested_inference_profile,
                        source=InferenceProfileSource.EXPLICIT_INPUT,
                    )
                    turn_inference_state = None
            agent_run = recoverable_run
        else:
            explicit_profile: RequestedInferenceProfile | None = None
            if command is None:
                pending_input = (
                    await self.input_buffer_service.peek_pending_inference_profile(
                        message.session_id
                    )
                )
                if not pending_input.exists and recoverable_run is None:
                    logger.info(
                        "Session wake-up ignored because no runtime input is pending",
                        extra={
                            "session_id": message.session_id,
                            "agent_id": message.agent_id,
                        },
                    )
                    return RunExecutionResult(
                        toolkits=[],
                        terminal_event_observed=False,
                        no_actionable_work=True,
                    )
                explicit_profile = pending_input.requested_inference_profile

            if explicit_profile is None and session_state.inference_state is not None:
                turn_inference_state = session_state.inference_state
                selected_profile = RequestedProfileSelection(
                    profile=RequestedInferenceProfile(
                        model_target_label=turn_inference_state.model_target_label,
                        reasoning_effort=turn_inference_state.reasoning_effort,
                    ),
                    source=InferenceProfileSource.SESSION_LAST_USED,
                )
            else:
                selected_profile = await self._select_requested_profile(
                    agent_id=message.agent_id,
                    session_id=message.session_id,
                    explicit_profile=explicit_profile,
                )
                turn_inference_state = None

            agent_run = recoverable_run or (
                await self.session_lifecycle.create_or_claim_pending_agent_run(
                    message.session_id,
                    input_event_ids=[],
                )
            )

        run_id = agent_run.id
        if command is None:
            initial_input = await self.poll_run_inputs(
                agent_id=message.agent_id,
                session_id=message.session_id,
                model=None,
                required_inference_profile=selected_profile.profile,
                active_run_id=run_id,
                initial_turn_eligible=(
                    recoverable_run is not None
                    and recoverable_run.status == AgentRunStatus.RUNNING
                ),
                poll_fn=None,
                process_actions=True,
            )
            if initial_input.requested_inference_profile is not None:
                selected_profile = RequestedProfileSelection(
                    profile=initial_input.requested_inference_profile,
                    source=InferenceProfileSource.EXPLICIT_INPUT,
                )
            if initial_input.complete_run:
                if agent_run.status is AgentRunStatus.PENDING:
                    await self.session_lifecycle.cancel_pending_agent_run(
                        message.session_id,
                        run_id=run_id,
                    )
                    terminal_run_status = AgentRunStatus.CANCELLED
                else:
                    await self.session_lifecycle.mark_agent_run_terminal_if_running(
                        message.session_id,
                        run_id=run_id,
                        status=AgentRunStatus.COMPLETED,
                    )
                    terminal_run_status = AgentRunStatus.COMPLETED
                await dispatch_event(message.session_id, RunComplete())
                return RunExecutionResult(
                    toolkits=[],
                    terminal_event_observed=True,
                    no_actionable_work=True,
                    run_id=run_id,
                    terminal_run_status=terminal_run_status,
                )
            if created_run and not initial_input.has_actionable_work:
                await self.session_lifecycle.cancel_pending_agent_run(
                    message.session_id,
                    run_id=run_id,
                )
            if initial_input.context_invalidated:
                async with self.session_manager() as db_session:
                    prepared_session = await self.agent_session_repository.get_by_id(
                        db_session,
                        message.session_id,
                    )
                if prepared_session is None or prepared_session.inference_state is None:
                    await self.session_lifecycle.send_session_wake_up(message)
                    return RunExecutionResult(
                        toolkits=[],
                        terminal_event_observed=False,
                        no_actionable_work=True,
                        run_id=None if created_run else run_id,
                    )
                turn_inference_state = prepared_session.inference_state
            if created_run and not initial_input.has_actionable_work:
                return RunExecutionResult(
                    toolkits=[],
                    terminal_event_observed=False,
                    no_actionable_work=True,
                )

        logger.info(
            "Run execution started",
            extra={
                "session_id": message.session_id,
                "agent_id": message.agent_id,
                "run_id": run_id,
                "user_id": message.user_id,
                "model_target_label": selected_profile.profile.model_target_label,
                "inference_profile_source": selected_profile.source.value,
                "interface_type": message.interface.type
                if message.interface is not None
                else None,
                "has_additional_system_prompt": bool(message.additional_system_prompt),
            },
        )
        invoke_input = InvokeInput(
            agent_id=message.agent_id,
            session_id=message.session_id,
            messages=[],
            user_id=message.user_id,
        )

        run_request: RunRequest | None = None
        if turn_inference_state is None:
            resolved = await resolve_invoke_input_with_profile(
                invoke_input,
                requested_profile=selected_profile.profile,
                agent_repository=self.agent_repository,
                integration_repository=self.integration_repository,
                session_manager=self.session_manager,
                exchange_file_service=self.exchange_file_service,
                model_file_service=self.model_file_service,
            )
            if resolved.failure:
                failure = _profile_resolution_failure(resolved.error)
                if agent_run.status == AgentRunStatus.PENDING:
                    await self.session_lifecycle.cancel_pending_agent_run(
                        message.session_id, run_id=run_id
                    )
                await dispatch_event(
                    message.session_id,
                    make_system_error_event(
                        session_id=message.session_id,
                        content=failure.message,
                    ),
                )
                await dispatch_event(message.session_id, RunComplete())
                return RunExecutionResult(
                    toolkits=[],
                    terminal_event_observed=True,
                    no_actionable_work=False,
                    run_id=run_id,
                    terminal_run_status=AgentRunStatus.CANCELLED,
                )
            resolved_profile = resolved.value
            run_request = resolved_profile.run_request
            turn_inference_state = SessionInferenceState(
                model_target_label=selected_profile.profile.model_target_label,
                model_selection=resolved_profile.model_selection,
                reasoning_effort=resolved_profile.reasoning_effort,
                effective_context_window_tokens=run_request.effective_max_input_tokens,
                effective_auto_compaction_threshold_tokens=(
                    compute_auto_compaction_threshold_tokens(
                        run_request.effective_max_input_tokens
                    )
                ),
                resolved_at=datetime.datetime.now(datetime.UTC),
            )
            async with self.session_manager() as db_session:
                await self.agent_session_repository.set_inference_state(
                    db_session,
                    session_id=message.session_id,
                    inference_state=turn_inference_state,
                )
                await db_session.commit()
        else:
            recovered = await resolve_invoke_input_with_resolved_profile(
                invoke_input,
                resolved_model_selection=turn_inference_state.model_selection,
                resolved_reasoning_effort=turn_inference_state.reasoning_effort,
                agent_repository=self.agent_repository,
                integration_repository=self.integration_repository,
                session_manager=self.session_manager,
                exchange_file_service=self.exchange_file_service,
                model_file_service=self.model_file_service,
            )
            if recovered.failure:
                failure = _profile_resolution_failure(recovered.error)
                if agent_run.status == AgentRunStatus.PENDING:
                    await self.session_lifecycle.cancel_pending_agent_run(
                        message.session_id,
                        run_id=run_id,
                    )
                    terminal_status = AgentRunStatus.CANCELLED
                else:
                    await self.session_lifecycle.mark_agent_run_terminal_if_running(
                        message.session_id,
                        run_id=run_id,
                        status=AgentRunStatus.FAILED,
                    )
                    terminal_status = AgentRunStatus.FAILED
                await dispatch_event(
                    message.session_id,
                    make_system_error_event(
                        session_id=message.session_id,
                        content=failure.message,
                    ),
                )
                await dispatch_event(message.session_id, RunComplete())
                return RunExecutionResult(
                    toolkits=[],
                    terminal_event_observed=True,
                    no_actionable_work=False,
                    run_id=run_id,
                    terminal_run_status=terminal_status,
                )
            run_request = recovered.value

        run_request = dataclasses.replace(
            run_request,
            max_input_tokens=turn_inference_state.effective_context_window_tokens,
            context_window_tokens=turn_inference_state.effective_context_window_tokens,
            compaction_max_input_tokens=(
                turn_inference_state.effective_context_window_tokens
            ),
            auto_compaction_threshold_tokens=(
                turn_inference_state.effective_auto_compaction_threshold_tokens
            ),
        )
        if agent_run.status == AgentRunStatus.PENDING:
            agent_run = await self.session_lifecycle.activate_pending_agent_run(
                message.session_id, run_id=run_id
            )
        elif agent_run.status != AgentRunStatus.RUNNING:
            raise ValueError("Recoverable AgentRun is already terminal")

        inference_profile = turn_inference_state.applied_profile
        now = loop.time()
        logger.info(
            "Run invoke input resolved",
            extra={
                "session_id": message.session_id,
                "agent_id": message.agent_id,
                "run_id": run_id,
                "workspace_id": run_request.workspace_id,
                "model": run_request.model,
                "duration_seconds": round(now - boundary_started_at, 3),
                "total_duration_seconds": round(now - preparation_started_at, 3),
            },
        )
        boundary_started_at = now

        async def dispatch_tree_change_to_tree(
            event: SubagentTreeChanged,
        ) -> None:
            """Forward a tree invalidation to every other SessionAgent view."""
            async with self.session_manager() as session:
                tree_agents = (
                    await self.agent_session_repository.list_session_agent_tree(
                        session,
                        root_session_agent_id=event.root_session_agent_id,
                    )
                )
            target_session_ids = {
                agent.agent_session_id
                for agent in tree_agents
                if agent.agent_session_id != message.session_id
            }
            for target_session_id in sorted(target_session_ids):
                await dispatch_event(target_session_id, event)

        async def publish_session_tree_changed() -> None:
            """Publish current run status changes to current and root tree viewers."""
            async with self.session_manager() as session:
                current_agent = (
                    await self.agent_session_repository.get_session_agent_by_session_id(
                        session,
                        message.session_id,
                    )
                )
            if current_agent is None:
                return
            event = SubagentTreeChanged(
                root_session_agent_id=current_agent.root_session_agent_id,
                changed_session_agent_id=current_agent.id,
            )
            await dispatch_event(message.session_id, event)
            await dispatch_tree_change_to_tree(event)

        async def publish_event(event: PublishedEvent) -> None:
            await dispatch_event(message.session_id, event)
            if isinstance(event, SubagentTreeChanged):
                await dispatch_tree_change_to_tree(event)

        iface = message.interface
        iface_type = iface.type if iface is not None else None
        iface_channel_id = getattr(iface, "channel_id", None)
        run_context = RunContext(
            user_id=message.user_id,
            run_id=run_id,
            publish_event=publish_event,
        )
        context = ToolkitContext(
            session_id=message.session_id,
            workspace_id=run_request.workspace_id,
            agent_id=invoke_input.agent_id,
            user_id=message.user_id,
            run_id=run_id,
            publish_event=publish_event,
            session_type=SessionType.USER,
            interface_type=iface_type,
            interface_channel_id=iface_channel_id,
        )

        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(
                session, invoke_input.agent_id
            )
            agent_session = await self.agent_session_repository.get_by_id(
                session, message.session_id
            )
            execution_mode = (
                ToolkitExecutionMode.SUBAGENT
                if agent_session is not None
                and agent_session.session_kind == AgentSessionKind.SUBAGENT
                else ToolkitExecutionMode.ROOT
            )
            agent_memory_enabled = agent.memory_enabled if agent else True
            runtime_tools_enabled = agent.shell_enabled if agent else False
            runtime_domain_config = RuntimeDomainConfig(
                allowed_domains=(), denied_domains=()
            )

            logger.info(
                "Run agent tools resolve started",
                extra={
                    "session_id": message.session_id,
                    "agent_id": invoke_input.agent_id,
                    "run_id": run_id,
                    "workspace_id": run_request.workspace_id,
                    "model": run_request.model,
                    "execution_mode": execution_mode.value,
                    "memory_enabled": agent_memory_enabled,
                    "runtime_tools_enabled": runtime_tools_enabled,
                },
            )
            toolkits = await resolve_agent_tools(
                invoke_input.agent_id,
                context,
                execution_mode=execution_mode,
                toolkit_registry=self.toolkit_registry,
                agent_toolkit_repository=self.agent_toolkit_repository,
                toolkit_repository=self.toolkit_repository,
                session=session,
                web_url=self.worker_config.web_url,
                oauth_secret_key=self.worker_config.oauth_secret_key,
                mcp_proxy_url=self.worker_config.mcp_proxy_url,
                runtime_domain_config=runtime_domain_config,
                workspace_handle=message.workspace_handle or "",
                builtin_toolkit_provider=self.builtin_toolkit_provider,
                claude_rules_toolkit_provider=self.claude_rules_toolkit_provider,
                todo_toolkit_provider=self.todo_toolkit_provider,
                goal_toolkit_provider=self.goal_toolkit_provider,
                skill_toolkit_provider=self.skill_toolkit_provider,
                subagent_toolkit_provider=self.subagent_toolkit_provider,
                memory_enabled=agent_memory_enabled,
                runtime_tools_enabled=runtime_tools_enabled,
            )

        now = loop.time()
        logger.info(
            "Run agent tools resolved",
            extra={
                "session_id": message.session_id,
                "agent_id": invoke_input.agent_id,
                "run_id": run_id,
                "workspace_id": run_request.workspace_id,
                "model": run_request.model,
                "toolkit_count": len(toolkits),
                "duration_seconds": round(now - boundary_started_at, 3),
                "total_duration_seconds": round(now - preparation_started_at, 3),
                "memory_enabled": agent_memory_enabled,
                "runtime_tools_enabled": runtime_tools_enabled,
            },
        )
        boundary_started_at = now

        run_request = dataclasses.replace(run_request, toolkits=toolkits)

        if prepare_toolkits is not None:
            logger.info(
                "Run session toolkits prepare started",
                extra={
                    "session_id": message.session_id,
                    "agent_id": invoke_input.agent_id,
                    "run_id": run_id,
                    "workspace_id": run_request.workspace_id,
                    "model": run_request.model,
                    "toolkit_count": len(run_request.toolkits),
                },
            )
            prepared_toolkits = await prepare_toolkits(
                run_request.toolkits,
                message.user_id,
            )
            run_request = dataclasses.replace(run_request, toolkits=prepared_toolkits)
            _refresh_runtime_peer_toolkits(prepared_toolkits)

        now = loop.time()
        logger.info(
            "Run session toolkits prepared",
            extra={
                "session_id": message.session_id,
                "agent_id": invoke_input.agent_id,
                "run_id": run_id,
                "workspace_id": run_request.workspace_id,
                "model": run_request.model,
                "toolkit_count": len(run_request.toolkits),
                "prepared": prepare_toolkits is not None,
                "duration_seconds": round(now - boundary_started_at, 3),
                "total_duration_seconds": round(now - preparation_started_at, 3),
            },
        )
        boundary_started_at = now

        if message.additional_system_prompt:
            run_request = dataclasses.replace(
                run_request,
                agent_prompt=(run_request.agent_prompt or "")
                + "\n\n"
                + message.additional_system_prompt,
            )

        hook_dispatcher = RuntimeHookDispatcher()
        hook_providers = _runtime_hook_provider_refs(run_request.toolkits)
        logger.info(
            "Run lifecycle hooks dispatch started",
            extra={
                "session_id": message.session_id,
                "agent_id": invoke_input.agent_id,
                "run_id": run_id,
                "workspace_id": run_request.workspace_id,
                "model": run_request.model,
                "hook_provider_count": len(hook_providers),
            },
        )
        async with self.session_manager() as session:
            session_start_claimed = (
                await self.agent_session_repository.claim_lifecycle_start(
                    session,
                    message.session_id,
                    now=tznow(),
                )
            )
        if session_start_claimed:
            await hook_dispatcher.dispatch_observation(
                hook_providers,
                "on_session_start",
                SessionStartHookContext(
                    workspace_id=run_request.workspace_id,
                    agent_id=run_request.agent_id,
                    session_id=message.session_id,
                    run_id=run_id,
                ),
            )

        await hook_dispatcher.dispatch_observation(
            hook_providers,
            "on_run_start",
            RunStartHookContext(
                workspace_id=run_request.workspace_id,
                agent_id=run_request.agent_id,
                session_id=message.session_id,
                run_id=run_id,
            ),
        )

        now = loop.time()
        logger.info(
            "Run lifecycle hooks dispatched",
            extra={
                "session_id": message.session_id,
                "agent_id": invoke_input.agent_id,
                "run_id": run_id,
                "workspace_id": run_request.workspace_id,
                "model": run_request.model,
                "hook_provider_count": len(hook_providers),
                "session_start_claimed": session_start_claimed,
                "duration_seconds": round(now - boundary_started_at, 3),
                "total_duration_seconds": round(now - preparation_started_at, 3),
            },
        )
        boundary_started_at = now

        recovering_running_run = (
            recoverable_run is not None
            and recoverable_run.status == AgentRunStatus.RUNNING
        )
        active_tool_calls = (
            list(agent_run.active_tool_calls) if recovering_running_run else []
        )
        active_phase: AgentRunPhase | None = (
            agent_run.phase
            if recovering_running_run
            else AgentRunPhase.COMPACTING
            if command is not None
            else None
        )
        current_retry_state = agent_run.retry_state if recovering_running_run else None
        live_retry_state = current_retry_state

        async def publish_live_run() -> None:
            """Publish the current live run snapshot to WebSocket clients."""
            await self.live_event_projector.publish_live_run_updated(
                message.session_id,
                ChatLiveRunState(
                    run_id=run_id,
                    phase=active_phase or AgentRunPhase.IDLE,
                    status=AgentRunStatus.RUNNING,
                    inference_profile=inference_profile,
                    retry=_chat_live_retry_state(live_retry_state),
                ),
            )

        async def clear_live_retry_state() -> None:
            """Clear live retry UI while retaining durable takeover progress.

            The durable state keeps the failed-attempt count until the next failure or
            terminal transition. Its expired ``next_retry_at`` lets takeover replay the
            in-flight attempt without repeating backoff or resetting the retry budget.
            """
            nonlocal live_retry_state
            if live_retry_state is None:
                return
            live_retry_state = None
            await publish_live_run()

        async def refresh_session_activity() -> None:
            """Publish the current run phase and active tool calls to the broker."""
            await self.session_lifecycle.set_session_activity(
                message.session_id,
                run_id=run_id,
                phase=active_phase,
                active_tool_calls=active_tool_calls,
            )
            await publish_live_run()

        await refresh_session_activity()
        await dispatch_event(
            message.session_id,
            RunStarted(run_id=run_id, phase=active_phase),
        )
        await publish_session_tree_changed()
        now = loop.time()
        logger.info(
            "Run started dispatched",
            extra={
                "session_id": message.session_id,
                "agent_id": invoke_input.agent_id,
                "run_id": run_id,
                "workspace_id": run_request.workspace_id,
                "model": run_request.model,
                "duration_seconds": round(now - boundary_started_at, 3),
                "total_duration_seconds": round(now - preparation_started_at, 3),
            },
        )
        run_completed = False
        run_end_reason: RunEndReason = "unknown"
        terminal_run_status: AgentRunStatus | None = None
        turn_boundary_context_invalidated = False

        def mark_turn_boundary_context_invalidated() -> None:
            nonlocal turn_boundary_context_invalidated
            turn_boundary_context_invalidated = True

        async def consume_emit(item: Emit) -> None:
            """Apply run lifecycle side effects for one engine emit."""
            nonlocal active_phase, run_completed, run_end_reason, terminal_run_status
            match item.event:
                case RunStarted():
                    return
                case RunComplete():
                    run_completed = True
                    run_end_reason = "completed"
                    terminal_run_status = AgentRunStatus.COMPLETED
                case RunStopped():
                    run_end_reason = "cancelled"
                    terminal_run_status = AgentRunStatus.STOPPED
                case RunPhaseChanged(phase=phase):
                    active_phase = phase
                    await refresh_session_activity()
                case _:
                    pass
            updated_tool_calls = apply_active_tool_call_event(
                active_tool_calls, item.event
            )
            if updated_tool_calls != active_tool_calls:
                active_tool_calls[:] = updated_tool_calls
                await refresh_session_activity()
                await self.live_event_projector.replace_active_tool_calls(
                    message.session_id,
                    active_tool_calls,
                )
            await handle_engine_event(
                item,
                publish=lambda ev: dispatch_event(message.session_id, ev),
            )

        heartbeat_task = asyncio.create_task(
            self._run_session_heartbeat_loop(message.session_id)
        )
        failed_attempt_source: FailedRunAttemptSource = (
            "command" if command_handler is not None else "model"
        )

        try:
            attempt_number = 1
            if current_retry_state is not None:
                attempt_number = current_retry_state.failed_attempt_count + 1
                finalization_reason = _failed_run_finalization_reason(
                    current_retry_state
                )
                if finalization_reason is not None:
                    run_end_reason = "error"
                    terminal_run_status = AgentRunStatus.FAILED
                    await self.failed_run_finalizer.finalize(
                        FailedRunFinalizationInput(
                            session_id=message.session_id,
                            run_id=run_id,
                            user_message=current_retry_state.last_user_message,
                            retry_state=current_retry_state,
                            reason=finalization_reason,
                        ),
                        dispatch_event=dispatch_event,
                    )
                    run_completed = True
                else:
                    retry_stopped = await self._wait_for_failed_run_retry(
                        session_id=message.session_id,
                        retry_state=current_retry_state,
                        check_stop=check_stop,
                        shutdown_event=shutdown_event,
                    )
                    if retry_stopped:
                        run_end_reason = "error"
                        terminal_run_status = AgentRunStatus.FAILED
                        await self.failed_run_finalizer.finalize(
                            FailedRunFinalizationInput(
                                session_id=message.session_id,
                                run_id=run_id,
                                user_message=current_retry_state.last_user_message,
                                retry_state=current_retry_state,
                                reason="retry_stopped_by_user",
                            ),
                            dispatch_event=dispatch_event,
                        )
                        run_completed = True
                    else:
                        await clear_live_retry_state()
            while not run_completed:
                try:
                    if command_handler is None:
                        boundary_poll = self.make_boundary_poll(
                            message=message,
                            model=run_request.model,
                            requested_inference_profile=selected_profile.profile,
                            run_id=run_id,
                            poll_fn=poll_fn,
                            mark_context_invalidated=mark_turn_boundary_context_invalidated,
                        )
                        engine_iter = self.engine.run(
                            run_request,
                            run_context,
                            poll_messages=boundary_poll,
                            check_stop=check_stop,
                        )
                    else:
                        engine_iter = command_handler.execute(
                            self.engine,
                            run_request,
                            run_context,
                        )

                    async for item in engine_iter:
                        await consume_emit(item)
                    if turn_boundary_context_invalidated:
                        async with self.session_manager() as db_session:
                            prepared_session = (
                                await self.agent_session_repository.get_by_id(
                                    db_session,
                                    message.session_id,
                                )
                            )
                        if (
                            prepared_session is None
                            or prepared_session.inference_state is None
                        ):
                            raise RuntimeError(
                                "Turn-boundary preparation has no prepared "
                                "Session inference state"
                            )
                        next_inference_state = prepared_session.inference_state
                        rebuilt = await resolve_invoke_input_with_resolved_profile(
                            invoke_input,
                            resolved_model_selection=(
                                next_inference_state.model_selection
                            ),
                            resolved_reasoning_effort=(
                                next_inference_state.reasoning_effort
                            ),
                            agent_repository=self.agent_repository,
                            integration_repository=self.integration_repository,
                            session_manager=self.session_manager,
                            exchange_file_service=self.exchange_file_service,
                            model_file_service=self.model_file_service,
                        )
                        if rebuilt.failure:
                            raise UserVisibleRuntimeError(
                                _profile_resolution_failure(rebuilt.error).message
                            )
                        run_request = dataclasses.replace(
                            rebuilt.value,
                            toolkits=run_request.toolkits,
                            agent_prompt=run_request.agent_prompt,
                            max_input_tokens=(
                                next_inference_state.effective_context_window_tokens
                            ),
                            context_window_tokens=(
                                next_inference_state.effective_context_window_tokens
                            ),
                            compaction_max_input_tokens=(
                                next_inference_state.effective_context_window_tokens
                            ),
                            auto_compaction_threshold_tokens=(
                                next_inference_state.effective_auto_compaction_threshold_tokens
                            ),
                        )
                        selected_profile = RequestedProfileSelection(
                            profile=RequestedInferenceProfile(
                                model_target_label=(
                                    next_inference_state.model_target_label
                                ),
                                reasoning_effort=(
                                    next_inference_state.reasoning_effort
                                ),
                            ),
                            source=InferenceProfileSource.EXPLICIT_INPUT,
                        )
                        inference_profile = next_inference_state.applied_profile
                        turn_boundary_context_invalidated = False
                        await publish_live_run()
                        continue
                    if command_handler is not None:
                        await dispatch_event(message.session_id, RunComplete())
                        run_completed = True
                        run_end_reason = "completed"
                        terminal_run_status = AgentRunStatus.COMPLETED
                    break
                except UserVisibleRuntimeError as exc:
                    retry_state = await self._record_failed_run_attempt(
                        session_id=message.session_id,
                        run_id=run_id,
                        attempt=self._failed_run_attempt_from_user_visible_error(
                            exc,
                            attempt_number=attempt_number,
                            source=failed_attempt_source,
                        ),
                        previous_retry_state=current_retry_state,
                    )
                    current_retry_state = retry_state
                    live_retry_state = retry_state
                    await publish_live_run()
                    finalization_reason = _failed_run_finalization_reason(retry_state)
                    if finalization_reason is not None:
                        run_end_reason = "error"
                        terminal_run_status = AgentRunStatus.FAILED
                        await self.failed_run_finalizer.finalize(
                            FailedRunFinalizationInput(
                                session_id=message.session_id,
                                run_id=run_id,
                                user_message=retry_state.last_user_message,
                                retry_state=retry_state,
                                reason=finalization_reason,
                            ),
                            dispatch_event=dispatch_event,
                        )
                        run_completed = True
                        break
                    retry_stopped = await self._wait_for_failed_run_retry(
                        session_id=message.session_id,
                        retry_state=retry_state,
                        check_stop=check_stop,
                        shutdown_event=shutdown_event,
                    )
                    if retry_stopped:
                        run_end_reason = "error"
                        terminal_run_status = AgentRunStatus.FAILED
                        await self.failed_run_finalizer.finalize(
                            FailedRunFinalizationInput(
                                session_id=message.session_id,
                                run_id=run_id,
                                user_message=retry_state.last_user_message,
                                retry_state=retry_state,
                                reason="retry_stopped_by_user",
                            ),
                            dispatch_event=dispatch_event,
                        )
                        run_completed = True
                        break
                    await clear_live_retry_state()
                    attempt_number += 1
                except Exception as exc:
                    retry_state = await self._record_failed_run_attempt(
                        session_id=message.session_id,
                        run_id=run_id,
                        attempt=FailedRunAttempt(
                            user_message=_INTERNAL_ERROR_MESSAGE,
                            internal_message=str(exc),
                            error_type=exc.__class__.__name__,
                            source=(
                                "command" if command_handler is not None else "engine"
                            ),
                            visibility="internal",
                            attempt_number=attempt_number,
                            occurred_at=datetime.datetime.now(datetime.UTC),
                        ),
                        previous_retry_state=current_retry_state,
                    )
                    current_retry_state = retry_state
                    live_retry_state = retry_state
                    await publish_live_run()
                    logger.exception(
                        "Internal error during engine run attempt",
                        extra={
                            "session_id": message.session_id,
                            "run_id": run_id,
                            "attempt_number": attempt_number,
                            "error_type": exc.__class__.__name__,
                        },
                    )
                    finalization_reason = _failed_run_finalization_reason(retry_state)
                    if finalization_reason is not None:
                        run_end_reason = "error"
                        terminal_run_status = AgentRunStatus.FAILED
                        await self.failed_run_finalizer.finalize(
                            FailedRunFinalizationInput(
                                session_id=message.session_id,
                                run_id=run_id,
                                user_message=retry_state.last_user_message,
                                retry_state=retry_state,
                                reason=finalization_reason,
                            ),
                            dispatch_event=dispatch_event,
                        )
                        run_completed = True
                        break
                    retry_stopped = await self._wait_for_failed_run_retry(
                        session_id=message.session_id,
                        retry_state=retry_state,
                        check_stop=check_stop,
                        shutdown_event=shutdown_event,
                    )
                    if retry_stopped:
                        run_end_reason = "error"
                        terminal_run_status = AgentRunStatus.FAILED
                        await self.failed_run_finalizer.finalize(
                            FailedRunFinalizationInput(
                                session_id=message.session_id,
                                run_id=run_id,
                                user_message=retry_state.last_user_message,
                                retry_state=retry_state,
                                reason="retry_stopped_by_user",
                            ),
                            dispatch_event=dispatch_event,
                        )
                        run_completed = True
                        break
                    await clear_live_retry_state()
                    attempt_number += 1
        except asyncio.CancelledError as exc:
            run_end_reason = "cancelled"
            if user_stop_cancelled(exc):
                terminal_run_status = AgentRunStatus.STOPPED
                await self.user_stop_finalizer.record_interrupted_run(
                    message.session_id,
                    run_id=run_id,
                )
            else:
                terminal_run_status = AgentRunStatus.CANCELLED
            raise
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
            await self.live_event_projector.flush_session(message.session_id)
            terminal_event_observed = observed_terminal_run_event(
                run_completed=run_completed,
                terminal_run_status=terminal_run_status,
            )
            if not terminal_event_observed:
                logger.info(
                    "Leaving agent run RUNNING until terminal event recovery",
                    extra={
                        "session_id": message.session_id,
                        "run_id": run_id,
                    },
                )
            else:
                await self.session_lifecycle.mark_agent_run_terminal_if_running(
                    message.session_id,
                    run_id=run_id,
                    status=terminal_run_status or AgentRunStatus.CANCELLED,
                )
            await hook_dispatcher.dispatch_observation(
                hook_providers,
                "on_run_end",
                RunEndHookContext(
                    workspace_id=run_request.workspace_id,
                    agent_id=run_request.agent_id,
                    session_id=message.session_id,
                    run_id=run_id,
                    reason=run_end_reason,
                ),
            )
            if not terminal_event_observed:
                logger.info(
                    "Keeping session activity until terminal event recovery",
                    extra={"session_id": message.session_id},
                )
            else:
                await self.session_lifecycle.clear_session_activity(message.session_id)
                await self.live_event_projector.publish_live_run_cleared(
                    message.session_id
                )
                await publish_session_tree_changed()
            if command is not None:
                await self._clear_pending_command(
                    message.session_id, command_id=command.id
                )

        return RunExecutionResult(
            toolkits=run_request.toolkits,
            terminal_event_observed=terminal_event_observed,
            no_actionable_work=False,
            run_id=run_id,
            terminal_run_status=terminal_run_status,
        )

    async def _clear_pending_command(
        self,
        session_id: str,
        *,
        command_id: str,
    ) -> None:
        """Remove processed pending command."""
        async with self.session_manager() as session:
            await self.agent_session_repository.clear_pending_command(
                session,
                session_id=session_id,
                command_id=command_id,
            )

    def _failed_run_attempt_from_user_visible_error(
        self,
        exc: UserVisibleRuntimeError,
        *,
        attempt_number: int,
        source: FailedRunAttemptSource,
    ) -> FailedRunAttempt:
        """Convert a user-visible exception into a failed-run attempt."""
        message = str(exc)
        retryability: FailedRunRetryability = "unknown"
        failure_code: str | None = None
        if _FAILED_RUN_NO_FIXTURE_MATCH_CODE in message:
            retryability = "non_retryable"
            failure_code = _FAILED_RUN_NO_FIXTURE_MATCH_CODE
        return FailedRunAttempt(
            user_message=exc.user_message,
            internal_message=message,
            error_type=exc.__class__.__name__,
            source=source,
            visibility="user_visible",
            attempt_number=attempt_number,
            occurred_at=datetime.datetime.now(datetime.UTC),
            retryability=retryability,
            failure_code=failure_code,
        )

    async def _record_failed_run_attempt(
        self,
        *,
        session_id: str,
        run_id: str,
        attempt: FailedRunAttempt,
        previous_retry_state: FailedRunRetryState | None,
    ) -> FailedRunRetryState:
        """Persist retry state for a failed run attempt."""
        backoff_seconds = (
            0
            if attempt.retryability == "non_retryable"
            else _failed_run_backoff_seconds(
                attempt.attempt_number,
                base_seconds=self.worker_config.failed_run_base_backoff_seconds,
                multiplier=self.worker_config.failed_run_backoff_multiplier,
                max_seconds=self.worker_config.failed_run_max_backoff_seconds,
            )
        )
        next_retry_at = attempt.occurred_at + datetime.timedelta(
            seconds=backoff_seconds
        )
        retry_state = FailedRunRetryState.from_attempt(
            attempt,
            max_retries=self.worker_config.failed_run_max_retries,
            backoff_seconds=backoff_seconds,
            next_retry_at=next_retry_at,
            previous=previous_retry_state,
        )
        await self.session_lifecycle.update_agent_run_retry_state(
            session_id,
            run_id=run_id,
            retry_state=retry_state,
        )
        await self.session_lifecycle.set_session_activity(
            session_id,
            run_id=run_id,
            phase=None,
            active_tool_calls=[],
        )
        return retry_state

    async def _wait_for_failed_run_retry(
        self,
        *,
        session_id: str,
        retry_state: FailedRunRetryState,
        check_stop: CheckStop | None,
        shutdown_event: asyncio.Event,
    ) -> bool:
        """Wait until retry time. Return True if the user requested stop."""
        while True:
            if shutdown_event.is_set():
                raise asyncio.CancelledError
            if check_stop is not None and await check_stop():
                return True
            delay = (
                retry_state.next_retry_at - datetime.datetime.now(datetime.UTC)
            ).total_seconds()
            if delay <= 0:
                return False
            await asyncio.sleep(min(delay, _FAILED_RUN_RETRY_WAIT_POLL_SECONDS))

    def _schedule_initial_prompt_title_generation(
        self,
        session_id: str,
        event: Event,
    ) -> None:
        """Start best-effort automatic title generation from the first prompt."""
        task = asyncio.create_task(
            self.session_title_service.generate_from_initial_prompt(session_id, event),
            name=f"session_title_{session_id}_{event.id}",
        )
        self._session_title_tasks.add(task)

        def on_done(done: asyncio.Task[object]) -> None:
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning(
                    "Automatic session title task failed",
                    extra={"session_id": session_id, "event_id": event.id},
                    exc_info=True,
                )

        task.add_done_callback(self._session_title_tasks.discard)
        task.add_done_callback(on_done)

    async def _run_session_heartbeat_loop(self, session_id: str) -> None:
        """Refresh session heartbeat while the engine run is active."""
        while True:
            try:
                await self.session_lifecycle.heartbeat_session(session_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Failed to update run heartbeat",
                    extra={"session_id": session_id},
                    exc_info=True,
                )
            await asyncio.sleep(_RUN_HEARTBEAT_INTERVAL_SECONDS)

    async def _select_requested_profile(
        self,
        *,
        agent_id: str,
        session_id: str,
        explicit_profile: RequestedInferenceProfile | None,
    ) -> RequestedProfileSelection:
        """Apply explicit, session-last, then Agent-default profile precedence."""
        if explicit_profile is not None:
            return RequestedProfileSelection(
                profile=explicit_profile,
                source=InferenceProfileSource.EXPLICIT_INPUT,
            )
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if agent_session is not None and agent_session.inference_state is not None:
                return RequestedProfileSelection(
                    profile=RequestedInferenceProfile(
                        model_target_label=(
                            agent_session.inference_state.model_target_label
                        ),
                        reasoning_effort=(
                            agent_session.inference_state.reasoning_effort
                        ),
                    ),
                    source=InferenceProfileSource.SESSION_LAST_USED,
                )
            agent = await self.agent_repository.get_by_id(session, agent_id)
        return RequestedProfileSelection(
            profile=RequestedInferenceProfile(
                model_target_label=(agent.main_model_label if agent else "default"),
                reasoning_effort=(
                    ModelReasoningEffort(agent.model_parameters.reasoning_effort)
                    if agent is not None
                    and agent.model_parameters is not None
                    and agent.model_parameters.reasoning_effort is not None
                    else None
                ),
            ),
            source=InferenceProfileSource.AGENT_DEFAULT,
        )

    def make_boundary_poll(
        self,
        *,
        message: SessionWakeUp,
        model: str | None,
        requested_inference_profile: RequestedInferenceProfile,
        run_id: str,
        poll_fn: PollMessages | None,
        mark_context_invalidated: Callable[[], None],
    ) -> PollMessages:
        """Combine model-call boundary polling with turn action processing."""

        async def poll() -> PollMessagesResult:
            result = await self.poll_run_inputs(
                agent_id=message.agent_id,
                session_id=message.session_id,
                model=model,
                required_inference_profile=requested_inference_profile,
                active_run_id=run_id,
                initial_turn_eligible=True,
                poll_fn=poll_fn,
                process_actions=True,
            )
            if result.context_invalidated:
                mark_context_invalidated()
                if await self.input_buffer_service.has_pending_session_input_buffers(
                    message.session_id
                ):
                    await self.session_lifecycle.send_session_wake_up(message)
            return PollMessagesResult(
                user_messages=result.user_messages,
                context_invalidated=result.context_invalidated,
                complete_run=result.complete_run,
            )

        return poll

    async def poll_run_inputs(
        self,
        *,
        agent_id: str,
        session_id: str,
        model: str | None,
        required_inference_profile: RequestedInferenceProfile | None,
        active_run_id: str | None,
        initial_turn_eligible: bool,
        poll_fn: PollMessages | None,
        process_actions: bool,
    ) -> RunInputPollResult:
        """Consume pending run inputs and report whether a wake-up has work."""
        user_messages: list[RunUserMessage] = []
        promoted_event_ids: list[str] = []
        selected_profile = required_inference_profile
        context_invalidated = False
        turn_eligible = initial_turn_eligible
        preparation_failed = False
        while True:
            pending_profile = (
                await self.input_buffer_service.peek_pending_inference_profile(
                    session_id
                )
            )
            profile_changed = (
                initial_turn_eligible
                and pending_profile.exists
                and pending_profile.requested_inference_profile is not None
                and selected_profile is not None
                and pending_profile.requested_inference_profile != selected_profile
            )
            promoted = await self._promote_input_buffers(
                agent_id=agent_id,
                session_id=session_id,
                model=model,
                required_inference_profile=selected_profile,
                active_run_id=active_run_id,
                include_action_messages=process_actions,
            )
            if not promoted.deleted_buffer_ids:
                break
            if promoted.requested_inference_profile is not None:
                selected_profile = promoted.requested_inference_profile
            turn_eligible = fold_turn_eligibility(
                turn_eligible,
                promoted.turn_effect,
            )
            preparation_failed = (
                preparation_failed or promoted.turn_effect is TurnEffect.FAILED
            )
            promoted_event_ids.extend(promoted.promoted_event_ids)
            user_messages.extend(promoted.user_messages)
            action_result = (
                await self._process_operation_actions(
                    agent_id=agent_id,
                    session_id=session_id,
                    worktree_action=promoted.worktree_action,
                )
                if process_actions
                else OperationActionProcessResult(context_invalidated=False)
            )
            context_invalidated = (
                context_invalidated
                or action_result.context_invalidated
                or (profile_changed and promoted.turn_effect is not TurnEffect.FAILED)
            )
            if context_invalidated:
                break

        queued_result = (
            await poll_fn()
            if poll_fn is not None and not context_invalidated
            else PollMessagesResult(
                user_messages=[],
                context_invalidated=False,
                complete_run=False,
            )
        )
        user_messages.extend(queued_result.user_messages)
        context_invalidated = context_invalidated or queued_result.context_invalidated
        has_actionable_work = turn_eligible and (
            bool(user_messages) or await self._has_actionable_model_input(session_id)
        )
        complete_run = (
            preparation_failed and not turn_eligible and not context_invalidated
        )
        return RunInputPollResult(
            user_messages=user_messages,
            requested_inference_profile=selected_profile,
            promoted_event_ids=list(dict.fromkeys(promoted_event_ids)),
            has_actionable_work=has_actionable_work,
            context_invalidated=context_invalidated,
            complete_run=complete_run,
        )

    async def _process_operation_actions(
        self,
        *,
        agent_id: str,
        session_id: str,
        worktree_action: WorktreeActionInput | None,
    ) -> OperationActionProcessResult:
        """Execute durably claimed operation TurnActions before model dispatch."""
        context_invalidated = False
        processed_input_buffer_ids: set[str] = set()
        if worktree_action is not None:
            if worktree_action.execution is None:
                raise RuntimeError("Worktree action has no durable execution claim")
            result = await self._process_operation_action(
                agent_id=agent_id,
                session_id=session_id,
                execution=worktree_action.execution,
                action=worktree_action.action,
            )
            processed_input_buffer_ids.add(worktree_action.buffer.id)
            context_invalidated = result.context_invalidated

        if context_invalidated:
            return OperationActionProcessResult(context_invalidated=True)

        async with self.session_manager() as session:
            list_projections = (
                self.session_git_worktree_service.list_action_execution_projections
            )
            projections = await list_projections(
                session,
                session_id=session_id,
            )
        pending = [
            projection.execution
            for projection in projections
            if projection.execution.status
            in {ActionExecutionStatus.PENDING, ActionExecutionStatus.RUNNING}
            and projection.execution.input_buffer_id not in processed_input_buffer_ids
        ]
        for execution in pending:
            action = _CHAT_ACTION_ADAPTER.validate_python(execution.action)
            match action:
                case CreateGitWorktreeAction():
                    result = await self._process_operation_action(
                        agent_id=agent_id,
                        session_id=session_id,
                        execution=execution,
                        action=action,
                    )
                case _:
                    continue
            context_invalidated = context_invalidated or result.context_invalidated
            if context_invalidated:
                break
        return OperationActionProcessResult(
            context_invalidated=context_invalidated,
        )

    async def _process_operation_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        action: CreateGitWorktreeAction,
    ) -> GitWorktreeActionExecutionResult:
        """Execute one durably claimed operation action."""

        async def publish_projection(
            projection: ActionExecutionProjection,
        ) -> None:
            try:
                await self.broadcast.publish(
                    session_id,
                    chat_action_execution_updated_dump(projection),
                )
            except Exception:
                logger.exception(
                    "Failed to broadcast action execution projection",
                    extra={
                        "session_id": session_id,
                        "action_execution_id": projection.execution.id,
                    },
                )

        async def publish_history_event(event: Event) -> None:
            try:
                await self.broadcast.publish(
                    session_id,
                    chat_history_event_appended_dump(event),
                )
            except Exception:
                logger.exception(
                    "Failed to broadcast action execution history event",
                    extra={"session_id": session_id, "event_id": event.id},
                )

        return await self.session_git_worktree_service.run_git_worktree_action(
            agent_id=agent_id,
            session_id=session_id,
            execution=execution,
            action=action,
            on_projection_updated=publish_projection,
            on_history_event_appended=publish_history_event,
        )

    async def _promote_input_buffers(
        self,
        *,
        agent_id: str,
        session_id: str,
        model: str | None,
        required_inference_profile: RequestedInferenceProfile | None,
        active_run_id: str | None,
        include_action_messages: bool,
    ) -> PromotedInputBuffers:
        """Promote input buffers and publish the matching live-state changes."""
        started_at = asyncio.get_running_loop().time()
        logger.info(
            "Input buffer flush started before model boundary",
            extra={"session_id": session_id, "model": model},
        )
        while True:
            pending = await self.input_buffer_service.peek_pending_inference_profile(
                session_id
            )
            prepared_inference_state: SessionInferenceState | None = None
            profile_resolution_failure: str | None = None
            if pending.requires_inference:
                requested_profile = (
                    pending.requested_inference_profile or required_inference_profile
                )
                if requested_profile is None:
                    raise RuntimeError(
                        "Inference-producing input has no requested profile"
                    )
                async with self.session_manager() as session:
                    session_state = await self.agent_session_repository.get_by_id(
                        session,
                        session_id,
                    )
                current_inference_state = (
                    session_state.inference_state if session_state is not None else None
                )
                if (
                    current_inference_state is None
                    or current_inference_state.model_target_label
                    != requested_profile.model_target_label
                    or current_inference_state.reasoning_effort
                    != requested_profile.reasoning_effort
                ):
                    resolved = await resolve_invoke_input_with_profile(
                        InvokeInput(
                            agent_id=agent_id,
                            session_id=session_id,
                            messages=[],
                            user_id=None,
                        ),
                        requested_profile=requested_profile,
                        agent_repository=self.agent_repository,
                        integration_repository=self.integration_repository,
                        session_manager=self.session_manager,
                        exchange_file_service=self.exchange_file_service,
                        model_file_service=self.model_file_service,
                    )
                    if resolved.failure:
                        profile_resolution_failure = _profile_resolution_failure(
                            resolved.error
                        ).message
                    else:
                        resolved_profile = resolved.value
                        effective_tokens = (
                            resolved_profile.run_request.effective_max_input_tokens
                        )
                        prepared_inference_state = SessionInferenceState(
                            model_target_label=requested_profile.model_target_label,
                            model_selection=resolved_profile.model_selection,
                            reasoning_effort=resolved_profile.reasoning_effort,
                            effective_context_window_tokens=effective_tokens,
                            effective_auto_compaction_threshold_tokens=(
                                compute_auto_compaction_threshold_tokens(
                                    effective_tokens
                                )
                            ),
                            resolved_at=datetime.datetime.now(datetime.UTC),
                        )
            try:
                promoted = await self.input_buffer_service.flush_session_input_buffers(
                    session_id=session_id,
                    model=model,
                    required_inference_profile=required_inference_profile,
                    expected_buffer_id=pending.input_buffer_id,
                    prepared_inference_state=prepared_inference_state,
                    profile_resolution_failure=profile_resolution_failure,
                    active_run_id=active_run_id,
                    include_action_messages=include_action_messages,
                )
            except InputBufferPreparationStaleError:
                continue
            break
        logger.info(
            "Input buffer flush completed before model boundary",
            extra={
                "session_id": session_id,
                "model": model,
                "duration_seconds": round(
                    asyncio.get_running_loop().time() - started_at,
                    3,
                ),
                "promoted_event_count": len(promoted.events),
                "promoted_user_message_count": len(promoted.user_messages),
                "deleted_buffer_count": len(promoted.deleted_buffer_ids),
            },
        )
        for event in promoted.events:
            self._schedule_initial_prompt_title_generation(session_id, event)
        try:
            for event in promoted.events:
                await self.broadcast.publish(
                    session_id,
                    chat_history_event_appended_dump(event),
                )
            for buffer_id in promoted.deleted_buffer_ids:
                await self.broadcast.publish(
                    session_id,
                    chat_live_event_removed_dump(session_id, buffer_id),
                )
        except Exception:
            logger.exception(
                "Failed to broadcast promoted input buffer events",
                extra={"session_id": session_id},
            )
        return promoted

    async def _has_actionable_model_input(self, session_id: str) -> bool:
        """Return whether transcript state after the latest run marker needs a run."""
        async with self.session_manager() as session:
            session_state = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            head_event_id = (
                session_state.model_input_head_event_id
                if session_state is not None
                else None
            )
            events = await self.event_transcript_repository.list_for_model_input(
                session,
                session_id,
                head_event_id=head_event_id,
            )
        return has_actionable_tail(events)


def has_actionable_tail(events: Sequence[Event]) -> bool:
    """Return whether events contain work not covered by a terminal run marker."""
    latest_run_marker_index: int | None = None
    for index, event in enumerate(events):
        if event.kind == EventKind.RUN_MARKER:
            latest_run_marker_index = index
    tail = (
        events[latest_run_marker_index + 1 :]
        if latest_run_marker_index is not None
        else events
    )
    return any(event.kind not in _NON_ACTIONABLE_TAIL_EVENT_KINDS for event in tail)


def _profile_resolution_failure(error: object) -> ProfileResolutionFailure:
    """Map internal routing errors to safe durable failure details."""
    if isinstance(error, ModelTargetNotFound):
        return ProfileResolutionFailure(
            code=InferenceProfileFailureCode.MODEL_TARGET_NOT_FOUND,
            message="The selected model is no longer available.",
        )
    if isinstance(error, ReasoningEffortUnsupported):
        return ProfileResolutionFailure(
            code=InferenceProfileFailureCode.REASONING_EFFORT_UNSUPPORTED,
            message="The selected reasoning effort is not supported by this model.",
        )
    return ProfileResolutionFailure(
        code=InferenceProfileFailureCode.MODEL_TARGET_RESOLUTION_FAILED,
        message="The selected model could not be prepared for this run.",
    )


def _chat_live_retry_state(
    retry_state: FailedRunRetryState | None,
) -> ChatLiveRunRetryState | None:
    """Convert durable retry state to chat live transport state."""
    if retry_state is None:
        return None
    return ChatLiveRunRetryState(
        status=retry_state.status,
        last_error_message=retry_state.last_user_message,
        failed_attempt_count=retry_state.failed_attempt_count,
        max_retries=retry_state.max_retries,
        backoff_seconds=retry_state.backoff_seconds,
        next_retry_at=retry_state.next_retry_at.isoformat(),
        attempts=[
            ChatLiveRunRetryAttempt(
                attempt_number=attempt.attempt_number,
                user_message=attempt.user_message,
                error_type=attempt.error_type,
                source=attempt.source,
                failed_at=attempt.failed_at.isoformat(),
                backoff_seconds=attempt.backoff_seconds,
                next_retry_at=attempt.next_retry_at.isoformat(),
                retryability=attempt.retryability,
                failure_code=attempt.failure_code,
                truncated=attempt.truncated,
            )
            for attempt in retry_state.attempts
        ],
    )


def _failed_run_finalization_reason(
    retry_state: FailedRunRetryState,
) -> FailedRunFinalizationReason | None:
    """Return terminal retry finalization reason, if retry should stop."""
    if retry_state.retryability == "non_retryable":
        return "non_retryable"
    if retry_state.failed_attempt_count >= retry_state.max_retries:
        return "retry_exhausted"
    return None


def _failed_run_backoff_seconds(
    attempt_number: int,
    *,
    base_seconds: int,
    multiplier: int,
    max_seconds: int,
) -> int:
    """Return bounded exponential failed-run retry backoff."""
    raw = base_seconds * (multiplier ** (attempt_number - 1))
    return min(max_seconds, raw)
