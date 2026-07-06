"""Session wake-up run execution."""

import asyncio
import contextlib
import dataclasses
import datetime
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Annotated, Any

from azcommon.datetime import tznow
from azcommon.uuid import uuid7
from fastapi import Depends
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
    EventKind,
)
from azents.core.tools import (
    SessionType,
    ToolkitContext,
    ToolkitProvider,
)
from azents.engine.events.action_messages import (
    ActionMessagePayload,
    CreateGitWorktreeAction,
)
from azents.engine.events.builders import make_system_error_event
from azents.engine.events.engine_adapter import AgentEngineAdapter
from azents.engine.events.engine_events import (
    RunComplete,
    RunPhaseChanged,
    RunStarted,
    RunStopped,
)
from azents.engine.events.types import ActiveToolCall, Event
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
from azents.engine.run.background import BackgroundTaskRegistry
from azents.engine.run.commands import CommandHandler
from azents.engine.run.contracts import AgentEngineProtocol, RunContext, ToolkitBinding
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
    resolve_agent_tools,
    resolve_invoke_input,
)
from azents.engine.run.types import CheckStop, PollMessages
from azents.engine.tools.builtin import BuiltinToolkitProvider, RuntimeToolkit
from azents.engine.tools.claude_rules import ClaudeRulesToolkitProvider
from azents.engine.tools.deps import (
    get_goal_toolkit_provider,
    get_todo_toolkit_provider,
    get_toolkit_registry,
)
from azents.engine.tools.goal import GoalToolkitProvider
from azents.engine.tools.skill import SkillToolkitProvider
from azents.engine.tools.todo import TodoToolkitProvider
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.action_execution.data import ActionExecutionProjection
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
from azents.services.input_buffer import InputBufferService, PromotedInputBuffers
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
    get_background_registry,
    get_broadcast,
    get_builtin_toolkit_provider,
    get_claude_rules_toolkit_provider,
    get_command_registry,
    get_exchange_file_service,
    get_skill_toolkit_provider,
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
    format_resolve_error,
    observed_terminal_run_event,
    user_stop_cancelled,
)
from azents.worker.run.results import RunExecutionResult
from azents.worker.session.contracts import PrepareToolkits
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.user_stop_finalizer import UserStopFinalizer

logger = logging.getLogger(__name__)
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
    has_actionable_work: bool
    context_invalidated: bool = False
    action_blocked: bool = False


@dataclasses.dataclass(frozen=True)
class OperationActionProcessResult:
    """Result of processing promoted operation actions."""

    context_invalidated: bool
    blocked: bool


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
    background_registry: Annotated[
        BackgroundTaskRegistry, Depends(get_background_registry)
    ]
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
        if command is None:
            initial_input = await self.poll_run_inputs(
                agent_id=message.agent_id,
                session_id=message.session_id,
                model=None,
                poll_fn=None,
                process_actions=True,
            )
            if initial_input.action_blocked:
                await self.session_lifecycle.mark_session_idle(message.session_id)
                await self.session_lifecycle.clear_session_activity(message.session_id)
                return RunExecutionResult(
                    toolkits=[],
                    terminal_event_observed=False,
                    no_actionable_work=False,
                )
            if initial_input.context_invalidated:
                if await self.input_buffer_service.has_pending_session_input_buffers(
                    message.session_id
                ):
                    await self.session_lifecycle.send_session_wake_up(message)
                return RunExecutionResult(
                    toolkits=[],
                    terminal_event_observed=False,
                    no_actionable_work=True,
                )
            if not initial_input.has_actionable_work:
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
        else:
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
        run_id = uuid7().hex
        logger.info(
            "Run execution started",
            extra={
                "session_id": message.session_id,
                "agent_id": message.agent_id,
                "run_id": run_id,
                "user_id": message.user_id,
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

        resolved = await resolve_invoke_input(
            invoke_input,
            agent_repository=self.agent_repository,
            integration_repository=self.integration_repository,
            session_manager=self.session_manager,
            exchange_file_service=self.exchange_file_service,
            model_file_service=self.model_file_service,
        )

        if resolved.failure:
            error_message = format_resolve_error(resolved.error)
            logger.warning(
                "Failed to resolve invoke input",
                extra={
                    "session_id": message.session_id,
                    "error": error_message,
                },
            )
            await dispatch_event(
                message.session_id,
                make_system_error_event(
                    session_id=message.session_id,
                    content=error_message,
                ),
            )
            await dispatch_event(message.session_id, RunComplete())
            return RunExecutionResult(
                toolkits=[],
                terminal_event_observed=True,
                no_actionable_work=False,
                run_id=run_id,
                terminal_run_status=AgentRunStatus.FAILED,
            )

        run_request = resolved.value
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

        async def publish_event(event: PublishedEvent) -> None:
            await dispatch_event(message.session_id, event)

        iface = message.interface
        iface_type = iface.type if iface is not None else None
        iface_channel_id = getattr(iface, "channel_id", None)
        run_context = RunContext(
            user_id=message.user_id,
            run_id=run_id,
            publish_event=publish_event,
            background_registry=self.background_registry,
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
                    "memory_enabled": agent_memory_enabled,
                    "runtime_tools_enabled": runtime_tools_enabled,
                },
            )
            toolkits = await resolve_agent_tools(
                invoke_input.agent_id,
                context,
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

        active_tool_calls: list[ActiveToolCall] = []
        active_phase: AgentRunPhase | None = (
            AgentRunPhase.COMPACTING if command is not None else None
        )
        current_retry_state: FailedRunRetryState | None = None

        async def publish_live_run(
            retry_state: FailedRunRetryState | None = None,
        ) -> None:
            """Publish the current live run snapshot to WebSocket clients."""
            await self.live_event_projector.publish_live_run_updated(
                message.session_id,
                ChatLiveRunState(
                    run_id=run_id,
                    phase=active_phase or AgentRunPhase.IDLE,
                    status=AgentRunStatus.RUNNING,
                    retry=_chat_live_retry_state(retry_state),
                ),
            )

        async def refresh_session_activity() -> None:
            """Publish the current run phase and active tool calls to the broker."""
            await self.session_lifecycle.set_session_activity(
                message.session_id,
                run_id=run_id,
                phase=active_phase,
                active_tool_calls=active_tool_calls,
            )
            await publish_live_run(current_retry_state)

        await refresh_session_activity()
        await dispatch_event(
            message.session_id,
            RunStarted(run_id=run_id, phase=active_phase),
        )
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
            while True:
                try:
                    if command_handler is None:
                        boundary_poll = self.make_boundary_poll(
                            agent_id=message.agent_id,
                            session_id=message.session_id,
                            model=run_request.model,
                            poll_fn=poll_fn,
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
                    await publish_live_run(retry_state)
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
                    await publish_live_run(retry_state)
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

    def make_boundary_poll(
        self,
        *,
        agent_id: str,
        session_id: str,
        model: str | None,
        poll_fn: PollMessages | None,
    ) -> PollMessages:
        """Combine model-call boundary polling with input-buffer promotion."""

        async def poll() -> list[RunUserMessage]:
            return (
                await self.poll_run_inputs(
                    agent_id=agent_id,
                    session_id=session_id,
                    model=model,
                    poll_fn=poll_fn,
                    process_actions=False,
                )
            ).user_messages

        return poll

    async def poll_run_inputs(
        self,
        *,
        agent_id: str,
        session_id: str,
        model: str | None,
        poll_fn: PollMessages | None,
        process_actions: bool,
    ) -> RunInputPollResult:
        """Consume pending run inputs and report whether a wake-up has work."""
        promoted = await self._promote_input_buffers(
            session_id=session_id,
            model=model,
            include_action_messages=process_actions,
        )
        action_result = (
            await self._process_operation_actions(
                agent_id=agent_id,
                session_id=session_id,
                events=promoted.events,
            )
            if process_actions
            else OperationActionProcessResult(
                context_invalidated=False,
                blocked=False,
            )
        )
        queued_events = await poll_fn() if poll_fn is not None else []
        user_messages = [*promoted.user_messages, *queued_events]
        has_actionable_work = bool(
            user_messages
        ) or await self._has_actionable_model_input(session_id)
        return RunInputPollResult(
            user_messages=user_messages,
            has_actionable_work=has_actionable_work,
            context_invalidated=action_result.context_invalidated,
            action_blocked=action_result.blocked,
        )

    async def _process_operation_actions(
        self,
        *,
        agent_id: str,
        session_id: str,
        events: Sequence[Event],
    ) -> OperationActionProcessResult:
        """Execute operation TurnActions before model dispatch."""
        context_invalidated = False
        processed_action_event_ids: set[str] = set()
        for event in events:
            if event.kind is not EventKind.ACTION_MESSAGE:
                continue
            result = await self._process_operation_action_event(
                agent_id=agent_id,
                session_id=session_id,
                event=event,
            )
            processed_action_event_ids.add(event.id)
            if not result.completed:
                return OperationActionProcessResult(
                    context_invalidated=context_invalidated,
                    blocked=True,
                )
            context_invalidated = context_invalidated or result.context_invalidated

        async with self.session_manager() as session:
            list_projections = (
                self.session_git_worktree_service.list_action_execution_projections
            )
            projections = await list_projections(
                session,
                session_id=session_id,
            )
            pending_action_event_ids = [
                projection.execution.action_event_id
                for projection in projections
                if projection.execution.status is ActionExecutionStatus.PENDING
                and projection.execution.action_event_id
                not in processed_action_event_ids
            ]
            retry_events = [
                event
                for action_event_id in pending_action_event_ids
                if (
                    event := await self.event_transcript_repository.get_by_id(
                        session,
                        event_id=action_event_id,
                    )
                )
                is not None
            ]

        for event in retry_events:
            result = await self._process_operation_action_event(
                agent_id=agent_id,
                session_id=session_id,
                event=event,
            )
            if not result.completed:
                return OperationActionProcessResult(
                    context_invalidated=context_invalidated,
                    blocked=True,
                )
            context_invalidated = context_invalidated or result.context_invalidated
        return OperationActionProcessResult(
            context_invalidated=context_invalidated,
            blocked=False,
        )

    async def _process_operation_action_event(
        self,
        *,
        agent_id: str,
        session_id: str,
        event: Event,
    ) -> GitWorktreeActionExecutionResult:
        """Execute one operation action event."""
        payload = event.payload
        if not isinstance(payload, ActionMessagePayload):
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
            )

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

        action = payload.action
        match action:
            case CreateGitWorktreeAction():
                return await self.session_git_worktree_service.run_git_worktree_action(
                    agent_id=agent_id,
                    session_id=session_id,
                    action_event_id=event.id,
                    action=action,
                    on_projection_updated=publish_projection,
                    on_history_event_appended=publish_history_event,
                )
            case _:
                return GitWorktreeActionExecutionResult(
                    completed=True,
                    context_invalidated=False,
                )

    async def _promote_input_buffers(
        self,
        *,
        session_id: str,
        model: str | None,
        include_action_messages: bool,
    ) -> PromotedInputBuffers:
        """Promote input buffers and publish the matching live-state changes."""
        started_at = asyncio.get_running_loop().time()
        logger.info(
            "Input buffer flush started before model boundary",
            extra={"session_id": session_id, "model": model},
        )
        promoted = await self.input_buffer_service.flush_session_input_buffers(
            session_id=session_id,
            model=model,
            include_action_messages=include_action_messages,
        )
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
