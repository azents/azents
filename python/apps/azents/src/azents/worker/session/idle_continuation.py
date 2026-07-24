"""Session idle continuation handling."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.enums import InputBufferKind, InputBufferSchedulingMode
from azents.engine.hooks.dispatcher import (
    RuntimeHookDispatcher,
    RuntimeHookProviderRef,
)
from azents.engine.hooks.types import (
    SessionContinuationInput,
    SessionIdleHookContext,
)
from azents.engine.run.contracts import ToolkitBinding
from azents.rdb.deps import get_session_manager
from azents.rdb.models.event import JSONValue
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.input_buffer import InputBufferRepository
from azents.services.chat.live_events import input_buffer_to_live_event
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService
from azents.worker.deps import get_worker_broker
from azents.worker.events.publisher import WorkerEventPublisher


@dataclasses.dataclass(frozen=True)
class IdleContinuationService:
    """Store idle hook continuations as pending session input."""

    input_buffer_service: Annotated[InputBufferService, Depends(InputBufferService)]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    agent_run_repository: Annotated[
        AgentRunRepository,
        Depends(AgentRunRepository),
    ]
    input_buffer_repository: Annotated[
        InputBufferRepository,
        Depends(InputBufferRepository),
    ]
    event_publisher: Annotated[WorkerEventPublisher, Depends(WorkerEventPublisher)]
    broker: Annotated[SessionBroker, Depends(get_worker_broker)]
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]

    async def consume(
        self,
        message: SessionWakeUp,
        *,
        toolkits: Sequence[ToolkitBinding],
        run_id: str,
    ) -> bool:
        """Commit the idle outcome for one durable completed Run boundary."""
        workspace_id = await self._eligible_idle_boundary_workspace_id(
            message,
            run_id,
        )
        if workspace_id is None:
            return False
        providers = [
            RuntimeHookProviderRef(slug=binding.slug, toolkit=binding.toolkit)
            for binding in toolkits
        ]
        result = await RuntimeHookDispatcher().dispatch_session_idle(
            providers,
            SessionIdleHookContext(
                workspace_id=workspace_id,
                agent_id=message.agent_id,
                session_id=message.session_id,
                run_id=run_id,
                reason="completed",
            ),
        )
        continuation_inputs = [
            self._continuation_input(message, run_id, continuation)
            for continuation in result.continuations
        ]
        async with self.session_manager() as session:
            if (
                await self._eligible_idle_boundary_workspace_id_in_session(
                    session,
                    message,
                    run_id,
                )
            ) is None:
                return False
            enqueue_results = await self.input_buffer_service.enqueue_many(
                session,
                continuation_inputs,
            )
            consumed = (
                await self.agent_session_repository.consume_pending_idle_continuation(
                    session,
                    session_id=message.session_id,
                    run_id=run_id,
                    continue_running=bool(continuation_inputs),
                )
            )
            if not consumed:
                return False
        for enqueue_result in enqueue_results:
            if not enqueue_result.created:
                continue
            event = input_buffer_to_live_event(enqueue_result.input_buffer)
            if event is not None:
                await self.event_publisher.dispatch_event(
                    message.session_id,
                    event,
                )
        if continuation_inputs:
            await self.broker.send_message(message)
        return True

    async def _eligible_idle_boundary_workspace_id(
        self,
        message: SessionWakeUp,
        run_id: str,
    ) -> str | None:
        """Return persisted workspace ID when a boundary can enter hook evaluation."""
        async with self.session_manager() as session:
            return await self._eligible_idle_boundary_workspace_id_in_session(
                session,
                message,
                run_id,
            )

    async def _eligible_idle_boundary_workspace_id_in_session(
        self,
        session: AsyncSession,
        message: SessionWakeUp,
        run_id: str,
    ) -> str | None:
        """Return persisted workspace ID after rechecking the true-idle fence."""
        locked = await self.agent_session_repository.lock_by_id(
            session,
            message.session_id,
        )
        if locked is None:
            raise ValueError("AgentSession not found")
        if locked.pending_idle_continuation_run_id != run_id:
            return None
        if locked.pending_command_id is not None:
            return None
        input_buffer_repository = self.input_buffer_repository
        pending_wake_input = (
            await input_buffer_repository.has_by_session_id_and_scheduling_mode(
                session,
                session_id=message.session_id,
                scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
            )
        )
        if pending_wake_input:
            return None
        active_run = await self.agent_run_repository.get_active_by_session_id(
            session,
            session_id=message.session_id,
        )
        if active_run is not None:
            return None
        return locked.workspace_id

    def _continuation_input(
        self,
        message: SessionWakeUp,
        run_id: str,
        continuation: SessionContinuationInput,
    ) -> InputBufferEnqueue:
        """Convert one hook continuation to pending input."""
        metadata: dict[str, JSONValue] = dict(continuation.metadata)
        if continuation.hook_provider_slug is not None:
            metadata["provider_slug"] = continuation.hook_provider_slug
        return InputBufferEnqueue(
            session_id=message.session_id,
            kind=InputBufferKind.GOAL_CONTINUATION,
            scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            actor_user_id=None,
            content=continuation.content,
            idempotency_key=_continuation_idempotency_key(
                run_id,
                provider_slug=continuation.hook_provider_slug,
                continuation_index=continuation.hook_continuation_index,
            ),
            metadata={str(k): str(v) for k, v in metadata.items()},
            action=None,
            attachments=[],
            file_parts=[],
        )


def _continuation_idempotency_key(
    run_id: str,
    *,
    provider_slug: str | None,
    continuation_index: int | None,
) -> str:
    """Build a stable identity for one provider continuation outcome."""
    provider = provider_slug or "unknown"
    index = 0 if continuation_index is None else continuation_index
    return f"idle_continuation:{run_id}:{provider}:{index}"
