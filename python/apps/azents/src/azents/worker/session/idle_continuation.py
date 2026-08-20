"""Session idle continuation handling."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated, assert_never

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.enums import (
    AgentSessionStatus,
    MailboxItemKind,
    MailboxSchedulingMode,
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
from azents.rdb.deps import get_session_manager
from azents.rdb.models.event import JSONValue
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.data import (
    MailboxPresentationItem,
    ScheduledTaskContinuationMailboxPayload,
)
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.services.chat.live_events import mailbox_item_to_live_event
from azents.services.mailbox import MailboxEnqueue, MailboxService
from azents.worker.deps import get_worker_broker
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.session.execution_snapshot import (
    CanonicalExecutionOwnerGenerationStaleError,
    CanonicalExecutionSnapshot,
)


@dataclasses.dataclass(frozen=True)
class _IdleBoundaryEligibility:
    """True-idle admission plus the archived Scheduled exception identity."""

    eligible: bool
    archived_cycle_id: str | None


@dataclasses.dataclass(frozen=True)
class IdleContinuationService:
    """Store idle hook continuations as pending session input."""

    mailbox_item_service: Annotated[MailboxService, Depends(MailboxService)]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    agent_run_repository: Annotated[
        AgentRunRepository,
        Depends(AgentRunRepository),
    ]
    mailbox_item_repository: Annotated[
        MailboxRepository,
        Depends(MailboxRepository),
    ]
    scheduled_task_cycle_repository: Annotated[
        ScheduledTaskCycleRepository,
        Depends(ScheduledTaskCycleRepository),
    ]
    event_publisher: Annotated[WorkerEventPublisher, Depends(WorkerEventPublisher)]
    broker: Annotated[SessionBroker, Depends(get_worker_broker)]
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]

    async def consume(
        self,
        snapshot: CanonicalExecutionSnapshot,
        *,
        toolkits: Sequence[ToolkitBinding],
        run_id: str,
    ) -> bool:
        """Commit the idle outcome for one durable completed Run boundary."""
        eligibility = await self._eligible_idle_boundary(
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
        async with self.session_manager() as session:
            eligibility = await self._eligible_idle_boundary_in_session(
                session,
                snapshot.session_id,
                run_id,
                owner_generation=snapshot.owner_generation,
            )
            if not eligibility.eligible:
                return False
            continuations = result.continuations
            if eligibility.archived_cycle_id is not None:
                continuations = [
                    continuation
                    for continuation in continuations
                    if isinstance(
                        continuation,
                        ScheduledTaskSessionContinuationInput,
                    )
                    and continuation.cycle_id == eligibility.archived_cycle_id
                ]
            continuation_inputs = [
                self._continuation_input(
                    snapshot.session_id,
                    run_id,
                    continuation,
                )
                for continuation in continuations
            ]
            enqueue_results = await self.mailbox_item_service.enqueue_many(
                session,
                continuation_inputs,
            )
            consumed = (
                await self.agent_session_repository.consume_pending_idle_continuation(
                    session,
                    session_id=snapshot.session_id,
                    run_id=run_id,
                    continue_running=bool(continuation_inputs),
                    allow_archived_scheduled_continuation=(
                        eligibility.archived_cycle_id is not None
                    ),
                )
            )
            if not consumed:
                return False
        for enqueue_result in enqueue_results:
            if not enqueue_result.created:
                continue
            event = mailbox_item_to_live_event(enqueue_result.mailbox_item)
            if event is not None:
                await self.event_publisher.dispatch_event(
                    snapshot.session_id,
                    event,
                )
        if continuation_inputs:
            await self.broker.send_message(
                SessionWakeUp(session_id=snapshot.session_id)
            )
        return True

    async def _eligible_idle_boundary(
        self,
        session_id: str,
        run_id: str,
        *,
        owner_generation: int,
    ) -> _IdleBoundaryEligibility:
        """Return whether a boundary can enter idle hook evaluation."""
        async with self.session_manager() as session:
            return await self._eligible_idle_boundary_in_session(
                session,
                session_id,
                run_id,
                owner_generation=owner_generation,
            )

    async def _eligible_idle_boundary_in_session(
        self,
        session: AsyncSession,
        session_id: str,
        run_id: str,
        *,
        owner_generation: int,
    ) -> _IdleBoundaryEligibility:
        """Recheck the true-idle fence before committing hook output."""
        locked = await self.agent_session_repository.lock_by_id(
            session,
            session_id,
        )
        if locked is None:
            raise ValueError("AgentSession not found")
        if locked.owner_generation != owner_generation:
            raise CanonicalExecutionOwnerGenerationStaleError(
                "Session owner generation is stale during idle continuation"
            )
        archived_cycle_id: str | None = None
        if locked.status is not AgentSessionStatus.ACTIVE:
            if locked.status is not AgentSessionStatus.ARCHIVED:
                return _IdleBoundaryEligibility(False, None)
            run = await self.agent_run_repository.get_by_id(session, run_id)
            cycle_id = None if run is None else run.scheduled_task_cycle_id
            if cycle_id is None:
                return _IdleBoundaryEligibility(False, None)
            cycle = await self.scheduled_task_cycle_repository.get_started(
                session,
                agent_id=locked.agent_id,
                session_id=session_id,
                cycle_id=cycle_id,
            )
            if cycle is None or cycle.state.current_run_id != run_id:
                return _IdleBoundaryEligibility(False, None)
            archived_cycle_id = cycle_id
        if locked.pending_idle_continuation_run_id != run_id:
            return _IdleBoundaryEligibility(False, None)
        if locked.pending_command_id is not None:
            return _IdleBoundaryEligibility(False, None)
        mailbox_item_repository = self.mailbox_item_repository
        pending_wake_input = (
            await mailbox_item_repository.has_by_session_id_and_scheduling_mode(
                session,
                session_id=session_id,
                scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
            )
        )
        if pending_wake_input:
            return _IdleBoundaryEligibility(False, None)
        active_run = await self.agent_run_repository.get_active_by_session_id(
            session,
            session_id=session_id,
        )
        if active_run is not None:
            return _IdleBoundaryEligibility(False, None)
        return _IdleBoundaryEligibility(True, archived_cycle_id)

    def _continuation_input(
        self,
        session_id: str,
        run_id: str,
        continuation: SessionContinuationInput,
    ) -> MailboxEnqueue:
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
        return MailboxEnqueue(
            session_id=session_id,
            kind=mailbox_kind,
            scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            sender_user_id=None,
            order_group=None,
            order_sequence=0,
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
            payload=payload,
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
