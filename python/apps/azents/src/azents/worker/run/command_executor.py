"""Session command execution."""

import asyncio
import dataclasses
import datetime
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Annotated

from azcommon.result import Failure
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import (
    PublishedEvent,
)
from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.engine.events.builders import make_system_error_event
from azents.engine.events.engine_adapter import AgentEngineAdapter
from azents.engine.events.engine_events import (
    RunComplete,
    RunPhaseChanged,
    RunStarted,
)
from azents.engine.events.types import ActiveToolCall
from azents.engine.run.commands import CommandHandler
from azents.engine.run.contracts import AgentEngineProtocol
from azents.engine.run.errors import UserVisibleRuntimeError
from azents.engine.run.failure import (
    FailedRunAttempt,
    FailedRunAttemptVisibility,
    FailedRunRetryState,
)
from azents.engine.run.input import InvokeInput
from azents.engine.run.resolve import resolve_invoke_input
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import PendingSessionCommand
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.worker.deps import (
    get_command_registry,
    get_exchange_file_service,
)
from azents.worker.live.event_projector import LiveEventProjector
from azents.worker.run.finalizer import (
    FailedRunErrorFinalizer,
    FailedRunFinalizationInput,
)
from azents.worker.run.helpers import (
    apply_active_tool_call_event,
    format_resolve_error,
)
from azents.worker.run.results import RunExecutionResult
from azents.worker.session.lifecycle import SessionLifecycleService

logger = logging.getLogger(__name__)
_INTERNAL_ERROR_MESSAGE = "An internal error occurred."


@dataclasses.dataclass(frozen=True)
class CommandExecutor:
    """Resolve PendingSessionCommand and run command handler."""

    command_registry: Annotated[
        Mapping[str, CommandHandler], Depends(get_command_registry)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    engine: Annotated[AgentEngineProtocol, Depends(AgentEngineAdapter)]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    session_lifecycle: Annotated[
        SessionLifecycleService, Depends(SessionLifecycleService)
    ]
    exchange_file_service: Annotated[
        ExchangeFileService, Depends(get_exchange_file_service)
    ]
    model_file_service: Annotated[ModelFileService, Depends(ModelFileService)]
    live_event_projector: Annotated[LiveEventProjector, Depends(LiveEventProjector)]
    failed_run_finalizer: Annotated[
        FailedRunErrorFinalizer, Depends(FailedRunErrorFinalizer)
    ]

    async def execute(
        self,
        *,
        agent_id: str,
        session_id: str,
        command: PendingSessionCommand,
        dispatch_event: Callable[[str, PublishedEvent], Awaitable[None]],
    ) -> RunExecutionResult:
        """Handle command.

        :param agent_id: Agent ID
        :param session_id: AgentSession ID
        :param command: pending command
        :param dispatch_event: Event publishing callback
        """
        handler = self.command_registry.get(command.name)
        if handler is None:
            logger.warning("Unknown command", extra={"command": command.name})
            await self.clear_pending_command(session_id, command_id=command.id)
            return RunExecutionResult(
                toolkits=[],
                terminal_event_observed=False,
                no_actionable_work=False,
            )

        invoke_input = InvokeInput(
            agent_id=agent_id,
            session_id=session_id,
            messages=[],
            user_id=command.user_id,
        )

        resolved = await resolve_invoke_input(
            invoke_input,
            agent_repository=self.agent_repository,
            integration_repository=self.integration_repository,
            session_manager=self.session_manager,
            exchange_file_service=self.exchange_file_service,
            model_file_service=self.model_file_service,
        )

        if isinstance(resolved, Failure):
            error_message = format_resolve_error(resolved.error)
            logger.warning(
                "Failed to resolve command input",
                extra={
                    "session_id": session_id,
                    "command": command.name,
                    "error": error_message,
                },
            )
            await dispatch_event(
                session_id,
                make_system_error_event(
                    session_id=session_id,
                    content=error_message,
                ),
            )
            await dispatch_event(session_id, RunComplete())
            await self.clear_pending_command(session_id, command_id=command.id)
            return RunExecutionResult(
                toolkits=[],
                terminal_event_observed=True,
                no_actionable_work=False,
                terminal_run_status=AgentRunStatus.FAILED,
            )

        run_request = resolved.value
        run_id = uuid7().hex

        active_tool_calls: list[ActiveToolCall] = []
        active_phase: AgentRunPhase | None = AgentRunPhase.COMPACTING
        terminal_run_status = AgentRunStatus.COMPLETED
        await self.session_lifecycle.create_agent_run_projection(
            session_id,
            run_id=run_id,
            phase=active_phase,
        )
        await self.session_lifecycle.set_session_activity(
            session_id,
            run_id=run_id,
            phase=active_phase,
        )
        await dispatch_event(
            session_id,
            RunStarted(run_id=run_id, phase=active_phase),
        )

        try:
            async for item in handler.execute(self.engine, run_request):
                ev = item.event
                if isinstance(ev, RunPhaseChanged):
                    active_phase = ev.phase
                    await self.session_lifecycle.set_session_activity(
                        session_id,
                        run_id=run_id,
                        phase=active_phase,
                        active_tool_calls=active_tool_calls,
                    )
                updated_tool_calls = apply_active_tool_call_event(active_tool_calls, ev)
                if updated_tool_calls != active_tool_calls:
                    active_tool_calls = updated_tool_calls
                    await self.session_lifecycle.set_session_activity(
                        session_id,
                        run_id=run_id,
                        phase=active_phase,
                        active_tool_calls=active_tool_calls,
                    )
                    await self.live_event_projector.replace_active_tool_calls(
                        session_id,
                        active_tool_calls,
                    )
                await dispatch_event(session_id, ev)
            await dispatch_event(session_id, RunComplete())
        except UserVisibleRuntimeError as exc:
            terminal_run_status = AgentRunStatus.FAILED
            logger.warning(
                "Command execution failed with user-visible error",
                extra={
                    "session_id": session_id,
                    "command": command.name,
                    "error": exc.user_message,
                },
            )
            await self._finalize_failed_command_run(
                session_id=session_id,
                run_id=run_id,
                user_message=exc.user_message,
                internal_message=str(exc),
                error_type=exc.__class__.__name__,
                visibility="user_visible",
                dispatch_event=dispatch_event,
            )
        except Exception as exc:
            terminal_run_status = AgentRunStatus.FAILED
            logger.exception(
                "Command execution failed",
                extra={
                    "session_id": session_id,
                    "command": command.name,
                    "error_type": exc.__class__.__name__,
                },
            )
            await self._finalize_failed_command_run(
                session_id=session_id,
                run_id=run_id,
                user_message=_INTERNAL_ERROR_MESSAGE,
                internal_message=str(exc),
                error_type=exc.__class__.__name__,
                visibility="internal",
                dispatch_event=dispatch_event,
            )
        finally:
            await self.live_event_projector.flush_session(session_id)
            await self.session_lifecycle.clear_session_activity(session_id)
            await self.session_lifecycle.mark_agent_run_terminal_if_running(
                session_id,
                run_id=run_id,
                status=terminal_run_status,
            )
            await self.clear_pending_command(session_id, command_id=command.id)

        return RunExecutionResult(
            toolkits=[],
            terminal_event_observed=True,
            no_actionable_work=False,
            run_id=run_id,
            terminal_run_status=terminal_run_status,
        )

    async def _finalize_failed_command_run(
        self,
        *,
        session_id: str,
        run_id: str,
        user_message: str,
        internal_message: str,
        error_type: str,
        visibility: FailedRunAttemptVisibility,
        dispatch_event: Callable[[str, PublishedEvent], Awaitable[None]],
    ) -> None:
        """Finalize a command run through the shared failed-run finalizer."""
        occurred_at = datetime.datetime.now(datetime.UTC)
        attempt = FailedRunAttempt(
            user_message=user_message,
            internal_message=internal_message,
            error_type=error_type,
            source="command",
            visibility=visibility,
            attempt_number=1,
            occurred_at=occurred_at,
        )
        retry_state = FailedRunRetryState.from_attempt(
            attempt,
            max_retries=1,
            backoff_seconds=0,
            next_retry_at=occurred_at,
        )
        await self.failed_run_finalizer.finalize(
            FailedRunFinalizationInput(
                session_id=session_id,
                run_id=run_id,
                user_message=user_message,
                retry_state=retry_state,
                reason="retry_exhausted",
            ),
            dispatch_event=dispatch_event,
        )

    async def clear_pending_command(self, session_id: str, *, command_id: str) -> None:
        """Remove processed pending command."""
        await self.run_short_db(
            lambda db: self.agent_session_repository.clear_pending_command(
                db,
                session_id=session_id,
                command_id=command_id,
            ),
            error_log="Failed to clear pending command",
            session_id=session_id,
        )

    async def run_short_db(
        self,
        action: Callable[[AsyncSession], Awaitable[object]],
        *,
        error_log: str,
        session_id: str,
    ) -> None:
        """Run ``action`` in short-lived DB transaction."""
        try:
            async with self.session_manager() as db_session:
                await action(db_session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(error_log, extra={"session_id": session_id})
