"""Session idle continuation handling."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.enums import InputBufferKind
from azents.engine.hooks.dispatcher import (
    RuntimeHookDispatcher,
    RuntimeHookProviderRef,
)
from azents.engine.hooks.types import (
    SessionContinuationInput,
    SessionIdleHookContext,
)
from azents.engine.run.contracts import ToolkitBinding
from azents.rdb.models.event import JSONValue
from azents.services.chat.live_events import input_buffer_to_live_event
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService
from azents.worker.deps import get_worker_broker
from azents.worker.events.publisher import WorkerEventPublisher


@dataclasses.dataclass(frozen=True)
class IdleContinuationService:
    """Store idle hook continuations as pending session input."""

    input_buffer_service: Annotated[InputBufferService, Depends(InputBufferService)]
    event_publisher: Annotated[WorkerEventPublisher, Depends(WorkerEventPublisher)]
    broker: Annotated[SessionBroker, Depends(get_worker_broker)]

    async def enqueue(
        self,
        message: SessionWakeUp,
        *,
        toolkits: Sequence[ToolkitBinding],
        run_id: str | None,
    ) -> bool:
        """Store Idle continuation if present and return whether wake-up is needed."""
        providers = [
            RuntimeHookProviderRef(slug=binding.slug, toolkit=binding.toolkit)
            for binding in toolkits
        ]
        result = await RuntimeHookDispatcher().dispatch_session_idle(
            providers,
            SessionIdleHookContext(
                workspace_id=message.workspace_id or "",
                agent_id=message.agent_id,
                session_id=message.session_id,
                run_id=run_id or "",
                reason="completed",
            ),
        )
        if not result.continuations:
            return False

        enqueue_results = await self.input_buffer_service.enqueue_many_in_transaction(
            [
                self._continuation_input(message, continuation)
                for continuation in result.continuations
            ],
        )
        for enqueue_result in enqueue_results:
            await self.event_publisher.dispatch_event(
                message.session_id,
                input_buffer_to_live_event(enqueue_result.input_buffer),
            )
        await self.broker.send_message(message)
        return True

    def _continuation_input(
        self,
        message: SessionWakeUp,
        continuation: SessionContinuationInput,
    ) -> InputBufferEnqueue:
        """Convert one hook continuation to pending input."""
        metadata: dict[str, JSONValue] = dict(continuation.metadata)
        if continuation.hook_provider_slug is not None:
            metadata["provider_slug"] = continuation.hook_provider_slug
        return InputBufferEnqueue(
            session_id=message.session_id,
            kind=InputBufferKind.GOAL_CONTINUATION,
            actor_user_id=None,
            content=continuation.content,
            idempotency_key=None,
            metadata={str(k): str(v) for k, v in metadata.items()},
            attachments=[],
            file_parts=[],
        )
