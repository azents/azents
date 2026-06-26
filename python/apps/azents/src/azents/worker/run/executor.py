"""Session wake-up run execution."""

import asyncio
import contextlib
import dataclasses
import logging
from collections.abc import Awaitable, Callable, Sequence
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
from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.core.tools import (
    SessionType,
    Toolkit,
    ToolkitContext,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
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
from azents.engine.run.contracts import AgentEngineProtocol, RunContext, ToolkitBinding
from azents.engine.run.emit import handle_engine_event
from azents.engine.run.errors import UserVisibleRuntimeError
from azents.engine.run.input import InvokeInput
from azents.engine.run.resolve import (
    resolve_agent_tools,
    resolve_invoke_input,
    resolve_subagent_tools,
)
from azents.engine.run.types import CheckStop, PollMessages
from azents.engine.tools.builtin import BuiltinToolkitProvider, RuntimeToolkit
from azents.engine.tools.deps import (
    get_goal_toolkit_provider,
    get_todo_toolkit_provider,
    get_toolkit_registry,
)
from azents.engine.tools.goal import GoalToolkitProvider
from azents.engine.tools.subagent import (
    SubagentToolContext,
    create_unified_subagent_tool,
)
from azents.engine.tools.task import (
    BACKGROUND_TASK_TOOLKIT_SLUG,
    BackgroundTaskToolkit,
)
from azents.engine.tools.todo import TodoToolkitProvider
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_subagent import AgentSubagentRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.toolkit import AgentToolkitRepository, ToolkitRepository
from azents.runtime.types import RuntimeDomainConfig
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import InputBufferService, PromotedInputBuffers
from azents.services.model_file import ModelFileService
from azents.services.session_title import SessionTitleService
from azents.transport.chat import (
    chat_history_event_appended_dump,
    chat_live_event_removed_dump,
)
from azents.worker.config import AgentWorkerConfig
from azents.worker.deps import (
    get_background_registry,
    get_broadcast,
    get_builtin_toolkit_provider,
    get_exchange_file_service,
    get_llm_provider_integration_repository,
    get_toolkit_repository,
    get_worker_broker,
    get_worker_config,
)
from azents.worker.live.event_projector import LiveEventProjector
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
_NON_ACTIONABLE_TAIL_EVENT_KINDS = {
    EventKind.RUN_MARKER,
    EventKind.TURN_MARKER,
    EventKind.COMPACTION_MARKER,
    EventKind.COMPACTION_SUMMARY,
}


@dataclasses.dataclass(frozen=True)
class RunInputPollResult:
    """Input poll result shared by wake-up entry and model boundaries."""

    user_messages: list[RunUserMessage]
    has_actionable_work: bool


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
    agent_subagent_repository: Annotated[
        AgentSubagentRepository, Depends(AgentSubagentRepository)
    ]
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
    session_title_service: Annotated[SessionTitleService, Depends(SessionTitleService)]
    live_event_projector: Annotated[LiveEventProjector, Depends(LiveEventProjector)]
    user_stop_finalizer: Annotated[UserStopFinalizer, Depends(UserStopFinalizer)]
    background_registry: Annotated[
        BackgroundTaskRegistry, Depends(get_background_registry)
    ]
    builtin_toolkit_provider: Annotated[
        BuiltinToolkitProvider, Depends(get_builtin_toolkit_provider)
    ]
    todo_toolkit_provider: Annotated[
        TodoToolkitProvider, Depends(get_todo_toolkit_provider)
    ]
    goal_toolkit_provider: Annotated[
        GoalToolkitProvider, Depends(get_goal_toolkit_provider)
    ]
    broadcast: Annotated[WebSocketBroadcast, Depends(get_broadcast)]
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
    ) -> RunExecutionResult:
        """Handle one session wake-up.

        :param message: Incoming session wake-up.
        :param poll_fn: Callback that polls for new user messages during a run.
        :param check_stop: Callback that checks whether execution should stop.
        :param prepare_toolkits: Callback that prepares session-managed toolkits.
        :param shutdown_event: Worker shutdown event.
        :param dispatch_event: Event publication callback.
        :return: Session-managed toolkits used by execution.
        """
        initial_input = await self.poll_run_inputs(
            session_id=message.session_id,
            model=None,
            poll_fn=None,
        )
        if not initial_input.has_actionable_work:
            logger.info(
                "Session wake-up ignored because no runtime input is pending",
                extra={"session_id": message.session_id, "agent_id": message.agent_id},
            )
            return RunExecutionResult(
                toolkits=[],
                terminal_event_observed=False,
                no_actionable_work=True,
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
                todo_toolkit_provider=self.todo_toolkit_provider,
                goal_toolkit_provider=self.goal_toolkit_provider,
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

        async with self.session_manager() as session:
            subagent_junctions = await resolve_subagent_tools(
                invoke_input.agent_id,
                agent_subagent_repository=self.agent_subagent_repository,
                agent_repository=self.agent_repository,
                session=session,
            )

        now = loop.time()
        logger.info(
            "Run subagent tools resolved",
            extra={
                "session_id": message.session_id,
                "agent_id": invoke_input.agent_id,
                "run_id": run_id,
                "workspace_id": run_request.workspace_id,
                "model": run_request.model,
                "subagent_tool_count": len(subagent_junctions),
                "duration_seconds": round(now - boundary_started_at, 3),
                "total_duration_seconds": round(now - preparation_started_at, 3),
            },
        )
        boundary_started_at = now

        if subagent_junctions:
            subagent_ctx = SubagentToolContext(
                engine=self.engine,
                parent_session_id=message.session_id,
                parent_agent_id=invoke_input.agent_id,
                parent_runtime_domain_config=runtime_domain_config,
                workspace_id=run_request.workspace_id,
                user_id=message.user_id,
                agent_repository=self.agent_repository,
                integration_repository=self.integration_repository,
                exchange_file_service=self.exchange_file_service,
                model_file_service=self.model_file_service,
                session_manager=self.session_manager,
                toolkit_registry=self.toolkit_registry,
                agent_toolkit_repository=self.agent_toolkit_repository,
                toolkit_repository=self.toolkit_repository,
                agent_runtime_repository=self.agent_runtime_repository,
                agent_session_repository=self.agent_session_repository,
                publish_event=publish_event,
                broker=self.broker,
                builtin_toolkit_provider=self.builtin_toolkit_provider,
                todo_toolkit_provider=self.todo_toolkit_provider,
                goal_toolkit_provider=self.goal_toolkit_provider,
                web_url=self.worker_config.web_url,
                oauth_secret_key=self.worker_config.oauth_secret_key,
                mcp_proxy_url=self.worker_config.mcp_proxy_url,
                session_type=SessionType.USER,
                parent_run_id=run_id,
                parent_check_stop=None,
                shutdown_event=shutdown_event,
            )

            class _SubagentToolkit(Toolkit[Any]):
                """Toolkit that builds subagent tools from the current turn context."""

                async def update_context(self, context: TurnContext) -> ToolkitState:
                    current_ctx = dataclasses.replace(
                        subagent_ctx,
                        user_id=context.user_id,
                        publish_event=context.publish_event,
                        parent_run_id=context.run_id,
                        parent_check_stop=context.check_stop,
                    )
                    subagent_tool = create_unified_subagent_tool(
                        subagent_junctions,
                        current_ctx,
                    )
                    return ToolkitState(
                        status=ToolkitStatus.ENABLED,
                        tools=[subagent_tool],
                        prompt="",
                    )

            background_task_toolkit = BackgroundTaskToolkit(
                registry=self.background_registry,
                session_id=message.session_id,
            )

            run_request = dataclasses.replace(
                run_request,
                toolkits=[
                    *run_request.toolkits,
                    ToolkitBinding(_SubagentToolkit(), "subagent", False),
                    ToolkitBinding(
                        background_task_toolkit,
                        BACKGROUND_TASK_TOOLKIT_SLUG,
                        False,
                    ),
                ],
            )

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
        active_phase: AgentRunPhase | None = None

        async def refresh_session_activity() -> None:
            """Publish the current run phase and active tool calls to the broker."""
            await self.session_lifecycle.set_session_activity(
                message.session_id,
                run_id=run_id,
                phase=active_phase,
                active_tool_calls=active_tool_calls,
            )

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
        heartbeat_task = asyncio.create_task(
            self._run_session_heartbeat_loop(message.session_id)
        )

        try:
            boundary_poll = self.make_boundary_poll(
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

            async for item in engine_iter:
                match item.event:
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
                    active_tool_calls = updated_tool_calls
                    await refresh_session_activity()
                    await self.live_event_projector.replace_active_tool_calls(
                        message.session_id,
                        active_tool_calls,
                    )
                await handle_engine_event(
                    item,
                    publish=lambda ev: dispatch_event(message.session_id, ev),
                )
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
        except UserVisibleRuntimeError as exc:
            run_end_reason = "error"
            terminal_run_status = AgentRunStatus.FAILED
            error_msg = exc.user_message
            logger.warning(
                "Engine run failed with user-visible error",
                extra={
                    "session_id": message.session_id,
                    "error": error_msg,
                    "error_type": exc.__class__.__name__,
                },
            )
            try:
                error_event = await self.engine.save_error_message(
                    message.session_id,
                    error_msg,
                )
            except Exception:
                logger.exception(
                    "Failed to save compaction error message",
                    extra={"session_id": message.session_id},
                )
                error_event = make_system_error_event(
                    session_id=message.session_id,
                    content=error_msg,
                )
            await dispatch_event(message.session_id, error_event)
            await dispatch_event(message.session_id, RunComplete())
            run_completed = True
        except Exception as exc:
            run_end_reason = "error"
            terminal_run_status = AgentRunStatus.FAILED
            error_msg = _INTERNAL_ERROR_MESSAGE
            logger.exception(
                "Internal error during engine run",
                extra={
                    "session_id": message.session_id,
                    "error_type": exc.__class__.__name__,
                },
            )
            try:
                error_event = await self.engine.save_error_message(
                    message.session_id,
                    error_msg,
                )
            except Exception:
                logger.exception(
                    "Failed to save error message",
                    extra={"session_id": message.session_id},
                )
                error_event = make_system_error_event(
                    session_id=message.session_id,
                    content=error_msg,
                )
            await dispatch_event(message.session_id, error_event)
            await dispatch_event(message.session_id, RunComplete())
            run_completed = True
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
                self._schedule_session_title_generation(message.session_id)

        return RunExecutionResult(
            toolkits=run_request.toolkits,
            terminal_event_observed=terminal_event_observed,
            no_actionable_work=False,
            run_id=run_id,
        )

    def _schedule_session_title_generation(self, session_id: str) -> None:
        """Start best-effort automatic title generation after terminal runs."""
        task = asyncio.create_task(
            self.session_title_service.generate_after_first_run(session_id),
            name=f"session_title_{session_id}",
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
                    extra={"session_id": session_id},
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
        session_id: str,
        model: str | None,
        poll_fn: PollMessages | None,
    ) -> PollMessages:
        """Combine model-call boundary polling with input-buffer promotion."""

        async def poll() -> list[RunUserMessage]:
            return (
                await self.poll_run_inputs(
                    session_id=session_id,
                    model=model,
                    poll_fn=poll_fn,
                )
            ).user_messages

        return poll

    async def poll_run_inputs(
        self,
        *,
        session_id: str,
        model: str | None,
        poll_fn: PollMessages | None,
    ) -> RunInputPollResult:
        """Consume pending run inputs and report whether a wake-up has work."""
        promoted = await self._promote_input_buffers(
            session_id=session_id,
            model=model,
        )
        queued_events = await poll_fn() if poll_fn is not None else []
        user_messages = [*promoted.user_messages, *queued_events]
        has_actionable_work = bool(
            user_messages
        ) or await self._has_actionable_model_input(session_id)
        return RunInputPollResult(
            user_messages=user_messages,
            has_actionable_work=has_actionable_work,
        )

    async def _promote_input_buffers(
        self,
        *,
        session_id: str,
        model: str | None,
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
