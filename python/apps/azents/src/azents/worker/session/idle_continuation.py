"""Session idle continuation handling."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated, assert_never

from fastapi import Depends

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.enums import (
    MailboxItemKind,
)
from azents.core.json_value import JSONValue
from azents.core.mailbox_data import (
    MailboxPresentationItem,
    ScheduledTaskContinuationMailboxPayload,
)
from azents.engine.hooks.dispatcher import (
    RuntimeHookDispatcher,
    RuntimeHookProviderRef,
)
from azents.engine.hooks.types import (
    ExternalChannelSessionContinuationInput,
    GoalSessionContinuationInput,
    ScheduledTaskSessionContinuationInput,
    SessionContinuationInput,
    SessionIdleHookContext,
)
from azents.engine.run.contracts import ToolkitBinding
from azents.repos.idle_continuation import (
    IdleContinuationInput,
    IdleContinuationRepository,
)
from azents.repos.session_execution.data import (
    CanonicalExecutionSnapshot,
)
from azents.services.chat.live_events import mailbox_item_to_live_event
from azents.worker.deps import get_worker_broker
from azents.worker.events.publisher import WorkerEventPublisher


@dataclasses.dataclass(frozen=True)
class IdleContinuationService:
    """Store idle hook continuations as pending session input."""

    repository: Annotated[
        IdleContinuationRepository,
        Depends(IdleContinuationRepository),
    ]
    event_publisher: Annotated[WorkerEventPublisher, Depends(WorkerEventPublisher)]
    broker: Annotated[SessionBroker, Depends(get_worker_broker)]

    async def consume(
        self,
        snapshot: CanonicalExecutionSnapshot,
        *,
        toolkits: Sequence[ToolkitBinding],
        run_id: str,
    ) -> bool:
        """Commit the idle outcome for one durable completed Run boundary."""
        eligibility = await self.repository.get_eligibility(
            snapshot.session_id,
            run_id,
            owner_generation=snapshot.owner_generation,
        )
        if not eligibility.eligible:
            return False
        providers = [
            RuntimeHookProviderRef(slug=binding.slug, toolkit=binding.toolkit)
            for binding in toolkits
        ]
        result = await RuntimeHookDispatcher().dispatch_session_idle(
            providers,
            SessionIdleHookContext(
                workspace_id=snapshot.workspace_id,
                agent_id=snapshot.agent_id,
                session_id=snapshot.session_id,
                run_id=run_id,
                reason="completed",
            ),
        )
        continuation_inputs = [
            self._continuation_input(
                snapshot.session_id,
                run_id,
                continuation,
            )
            for continuation in result.continuations
        ]
        finalization = await self.repository.finalize(
            session_id=snapshot.session_id,
            run_id=run_id,
            owner_generation=snapshot.owner_generation,
            inputs=continuation_inputs,
        )
        if not finalization.consumed:
            return False
        for admission in finalization.admissions:
            if not admission.created:
                continue
            event = mailbox_item_to_live_event(admission.mailbox_item)
            if event is not None:
                await self.event_publisher.dispatch_event(
                    snapshot.session_id,
                    event,
                    owner_generation=snapshot.owner_generation,
                )
        if finalization.continuation_count:
            await self.broker.send_message(
                SessionWakeUp(session_id=snapshot.session_id)
            )
        return True

    def _continuation_input(
        self,
        session_id: str,
        run_id: str,
        continuation: SessionContinuationInput,
    ) -> IdleContinuationInput:
        """Convert one hook continuation to pending input."""
        match continuation:
            case GoalSessionContinuationInput():
                mailbox_kind = MailboxItemKind.GOAL_CONTINUATION
            case ExternalChannelSessionContinuationInput():
                mailbox_kind = MailboxItemKind.EXTERNAL_CHANNEL_CONTINUATION
            case ScheduledTaskSessionContinuationInput():
                mailbox_kind = MailboxItemKind.SCHEDULED_TASK_CONTINUATION
            case _:
                assert_never(continuation)
        metadata: dict[str, JSONValue] = dict(continuation.metadata)
        if continuation.hook_provider_slug is not None:
            metadata["provider_slug"] = continuation.hook_provider_slug
        payload = None
        if isinstance(continuation, ScheduledTaskSessionContinuationInput):
            metadata["cycle_id"] = continuation.cycle_id
            metadata["title"] = continuation.title
            payload = ScheduledTaskContinuationMailboxPayload(
                type="scheduled_task_continuation",
                cycle_id=continuation.cycle_id,
                items=[
                    MailboxPresentationItem(
                        item_key="scheduled_task_continuation:0",
                        presentation_kind="scheduled_task_continuation",
                        content=continuation.content,
                        metadata={"title": continuation.title},
                    )
                ],
            )
        return IdleContinuationInput(
            session_id=session_id,
            kind=mailbox_kind,
            content=continuation.content,
            idempotency_key=_continuation_idempotency_key(
                run_id,
                provider_slug=continuation.hook_provider_slug,
                continuation_index=continuation.hook_continuation_index,
            ),
            metadata={str(k): str(v) for k, v in metadata.items()},
            payload=payload,
            scheduled_cycle_id=(
                continuation.cycle_id
                if isinstance(
                    continuation,
                    ScheduledTaskSessionContinuationInput,
                )
                else None
            ),
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
