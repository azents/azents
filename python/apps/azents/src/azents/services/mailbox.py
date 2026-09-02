"""Session input buffer service."""

import asyncio
import dataclasses
import datetime
import enum
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Annotated, Protocol, assert_never

from fastapi import Depends
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ActionExecutionStatus,
    AgentRunStatus,
    AgentSessionStatus,
    EventKind,
    ExternalChannelPrincipalAuthorType,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.external_channel_file import add_external_channel_file_locators
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    RequestedInferenceProfile,
    SessionInferenceState,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.engine.events.action_messages import (
    OperationAction,
    TurnAction,
)
from azents.engine.events.types import (
    AgentMessagePayload,
    AgentRunState,
    Event,
    ExternalChannelMessagePayload,
    FileOutputPart,
    ScheduledTaskContinuationPayload,
    ScheduledTaskTriggerPayload,
    SystemErrorPayload,
    SystemReminderPayload,
)
from azents.engine.events.user_messages import make_run_user_message
from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.io.user_input import RunUserMessage
from azents.engine.run.resolve import (
    materialize_admitted_input_exchange_file_attachments,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.models.event import JSONValue
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.action_execution.data import ActionExecution, ActionExecutionCreate
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.data import ExternalChannelMailboxProjectionItem
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.data import (
    AgentCreateGitWorktreeContinuationResult,
    AgentRemoveGitWorktreeContinuationResult,
    ExternalChannelMessageMailboxPayload,
    MailboxEnvelopePayload,
    MailboxItem,
    MailboxItemCreate,
    MailboxPresentationItem,
    ScheduledTaskContinuationMailboxPayload,
    ScheduledTaskTriggerMailboxPayload,
    TurnActionContinuationMailboxPayload,
)
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import ScheduledTaskCycleRecord
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.services.scheduled_task.rendering import (
    render_scheduled_task_runtime_message,
)
from azents.services.session_resource_authority import SessionResourceAuthority
from azents.services.session_title import (
    initial_title_from_event,
    initial_title_from_external_channel_event,
)
from azents.services.turn_action import (
    TurnActionCapabilityRegistry,
    TurnActionPreparationContext,
    TurnActionPreparationEffect,
)

logger = logging.getLogger(__name__)
_JSON_OBJECT_ADAPTER = TypeAdapter[dict[str, JSONValue]](dict[str, JSONValue])
_AGENT_MESSAGE_ADAPTER = TypeAdapter(AgentMessagePayload)
_EXTERNAL_CHANNEL_CONTEXT_OMITTED_REMINDER = (
    "Earlier messages from this external conversation were omitted. "
    "Only the newest 20 provider messages are included below."
)


@dataclasses.dataclass(frozen=True)
class MailboxEnqueue:
    """Input buffer enqueue request."""

    session_id: str
    kind: MailboxItemKind
    scheduling_mode: MailboxSchedulingMode
    requested_model_target_label: str | None
    requested_reasoning_effort: ModelReasoningEffort | None
    sender_user_id: str | None
    order_group: str | None
    order_sequence: int
    content: str
    idempotency_key: str | None
    metadata: dict[str, str]
    attachments: list[str]
    file_parts: list[FileOutputPart]
    action: dict[str, JSONValue] | None = None
    payload: MailboxEnvelopePayload | None = None


@dataclasses.dataclass(frozen=True)
class MailboxAdmissionResult:
    """Input buffer enqueue result."""

    mailbox_item: MailboxItem
    created: bool


@dataclasses.dataclass(frozen=True)
class PendingInputInferenceProfile:
    """Inference requirements projected from the next pending input."""

    mailbox_item_id: str | None
    exists: bool
    requires_inference: bool
    requested_inference_profile: RequestedInferenceProfile | None


class MailboxPreparationStaleError(RuntimeError):
    """The FIFO head changed after its preparation snapshot was read."""


class MailboxOwnerGenerationStaleError(RuntimeError):
    """The Session owner generation changed before FIFO promotion."""


class TurnEffect(enum.StrEnum):
    """Effect of one prepared MailboxItem on the next model turn."""

    ELIGIBLE = "eligible"
    NEUTRAL = "neutral"
    FAILED = "failed"


def fold_turn_eligibility(eligible: bool, effect: TurnEffect) -> bool:
    """Fold one FIFO processor effect into turn eligibility."""
    match effect:
        case TurnEffect.ELIGIBLE:
            return True
        case TurnEffect.NEUTRAL:
            return eligible
        case TurnEffect.FAILED:
            return False
        case _:
            assert_never(effect)


@dataclasses.dataclass(frozen=True)
class OperationActionInput:
    """Durably claimed buffer-only operation action awaiting external execution."""

    buffer: MailboxItem
    action: OperationAction
    execution: ActionExecution | None


@dataclasses.dataclass(frozen=True)
class PromotedMailboxItems:
    """Result of preparing one FIFO MailboxItem."""

    turn_effect: TurnEffect
    operation_action: OperationActionInput | None
    requested_inference_profile: RequestedInferenceProfile | None
    user_messages: list[RunUserMessage]
    events: list[Event]
    promoted_event_ids: list[str]
    deleted_buffer_ids: list[str]
    changed_session_agent_ids: list[str]
    claimed_count: int
    inserted_count: int
    deduped_count: int
    complete_run: bool
    suppress_parent_result: bool


@dataclasses.dataclass(frozen=True)
class ScheduledMailboxAdmission:
    """Result of one atomic Scheduled trigger/continuation admission."""

    run: AgentRunState | None
    promoted: PromotedMailboxItems | None
    stale: bool


@dataclasses.dataclass(frozen=True)
class _PromotedMailboxItem:
    """Result of converting MailboxItem to model input and durable event kind."""

    buffer: MailboxItem
    user_message: RunUserMessage | None
    event_kind: EventKind
    payload: dict[str, JSONValue]
    external_id: str
    item_key: str | None = None
    initial_title_eligible: bool = False


@dataclasses.dataclass(frozen=True)
class PreparedMailboxFiles:
    """Attachment metadata and creation-boundary FileParts prepared for promotion."""

    attachments: list[RuntimeAttachment]
    file_parts: list[FileOutputPart]
    created_model_file_ids: list[str]


@dataclasses.dataclass(frozen=True)
class MailboxPreparationContext:
    """Shared context passed to one closed input-buffer processor."""

    session: AsyncSession
    session_id: str
    active_run_id: str | None
    required_inference_profile: RequestedInferenceProfile | None
    prepared_inference_state: SessionInferenceState | None
    prepared_files: PreparedMailboxFiles


@dataclasses.dataclass(frozen=True)
class MailboxPreparationOutcome:
    """Semantic events and turn effect produced by one processor."""

    promoted: list[_PromotedMailboxItem]
    turn_effect: TurnEffect
    operation_action: OperationActionInput | None
    complete_run: bool
    suppress_parent_result: bool


class MailboxProcessor(Protocol):
    """Prepare one concrete MailboxItem kind."""

    async def process(
        self,
        context: MailboxPreparationContext,
        buffer: MailboxItem,
    ) -> MailboxPreparationOutcome:
        """Prepare one FIFO buffer inside the caller transaction."""
        ...


@dataclasses.dataclass(frozen=True)
class MailboxService:
    """Own session-bound input buffer reads, writes, and promotion."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    mailbox_item_repository: Annotated[MailboxRepository, Depends(MailboxRepository)]
    exchange_file_service: Annotated[ExchangeFileService, Depends(ExchangeFileService)]
    model_file_service: Annotated[ModelFileService, Depends(ModelFileService)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    scheduled_task_repository: Annotated[
        ScheduledTaskRepository, Depends(ScheduledTaskRepository)
    ]
    scheduled_task_cycle_repository: Annotated[
        ScheduledTaskCycleRepository, Depends(ScheduledTaskCycleRepository)
    ]
    action_execution_repository: Annotated[
        ActionExecutionRepository, Depends(ActionExecutionRepository)
    ]
    turn_action_capabilities: Annotated[TurnActionCapabilityRegistry, Depends()]
    external_channel_repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]

    async def enqueue(
        self,
        session: AsyncSession,
        input: MailboxEnqueue,
    ) -> MailboxAdmissionResult:
        """Create one pending input and persist its wake transition."""
        result = await self._enqueue_without_running_transition(session, input)
        if input.scheduling_mode is MailboxSchedulingMode.WAKE_SESSION:
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                input.session_id,
            )
        return result

    async def _enqueue_without_running_transition(
        self,
        session: AsyncSession,
        input: MailboxEnqueue,
    ) -> MailboxAdmissionResult:
        """Create one pending input before applying its Session transition."""
        existing = None
        if input.idempotency_key is not None:
            existing = await self.mailbox_item_repository.get_by_idempotency_key(
                session,
                session_id=input.session_id,
                kind=input.kind,
                idempotency_key=input.idempotency_key,
            )
        if existing is None:
            created = True
            create = MailboxItemCreate(
                session_id=input.session_id,
                kind=input.kind,
                scheduling_mode=input.scheduling_mode,
                requested_model_target_label=input.requested_model_target_label,
                requested_reasoning_effort=input.requested_reasoning_effort,
                sender_user_id=input.sender_user_id,
                order_group=input.order_group,
                order_sequence=input.order_sequence,
                content=input.content,
                idempotency_key=input.idempotency_key,
                metadata=input.metadata,
                action=input.action,
                attachments=input.attachments,
                file_parts=input.file_parts,
                payload=input.payload,
            )
            if input.idempotency_key is None:
                mailbox_item = await self.mailbox_item_repository.create(
                    session,
                    create,
                )
            else:
                mailbox_item = await self.mailbox_item_repository.create_idempotent(
                    session,
                    create,
                    idempotency_key=input.idempotency_key,
                )
        else:
            created = False
            mailbox_item = existing
        if mailbox_item.scheduling_mode != input.scheduling_mode:
            raise ValueError(
                "Input idempotency key already used for another scheduling mode"
            )
        if (
            mailbox_item.requested_model_target_label
            != input.requested_model_target_label
            or mailbox_item.requested_reasoning_effort
            != input.requested_reasoning_effort
        ):
            raise ValueError(
                "Input idempotency key already used for another inference profile"
            )
        return MailboxAdmissionResult(mailbox_item=mailbox_item, created=created)

    async def enqueue_many(
        self,
        session: AsyncSession,
        inputs: Sequence[MailboxEnqueue],
    ) -> list[MailboxAdmissionResult]:
        """Create pending inputs and persist each distinct wake transition."""
        results = [
            await self._enqueue_without_running_transition(session, input)
            for input in inputs
        ]
        wake_session_ids = {
            input.session_id
            for input in inputs
            if input.scheduling_mode is MailboxSchedulingMode.WAKE_SESSION
        }
        for session_id in sorted(wake_session_ids):
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                session_id,
            )
        return results

    async def enqueue_idle_continuations(
        self,
        session: AsyncSession,
        inputs: Sequence[MailboxEnqueue],
    ) -> list[MailboxAdmissionResult]:
        """Create idle-hook inputs whose caller owns the resulting Session state."""
        return [
            await self._enqueue_without_running_transition(session, input)
            for input in inputs
        ]

    async def enqueue_many_in_transaction(
        self,
        inputs: Sequence[MailboxEnqueue],
    ) -> list[MailboxAdmissionResult]:
        """Create pending inputs in one transaction."""
        async with self.session_manager() as session:
            return await self.enqueue_many(session, inputs)

    async def list_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> list[MailboxItem]:
        """Fetch pending input buffers for a session."""
        return await self.mailbox_item_repository.list_by_session_id(
            session,
            session_id,
        )

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        buffer_id: str,
    ) -> MailboxItem | None:
        """Fetch a pending MailboxItem by its durable acceptance identity."""
        return await self.mailbox_item_repository.get_by_id(session, buffer_id)

    async def get_by_idempotency_key(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        kind: MailboxItemKind,
        idempotency_key: str,
    ) -> MailboxItem | None:
        """Fetch one pending mailbox item by its producer identity."""
        return await self.mailbox_item_repository.get_by_idempotency_key(
            session,
            session_id=session_id,
            kind=kind,
            idempotency_key=idempotency_key,
        )

    async def has_seen_action_type(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        action_type: str,
    ) -> bool:
        """Return whether an action type is pending, live, or terminally recorded."""
        pending = await self.mailbox_item_repository.list_by_session_id(
            session,
            session_id,
        )
        if any(
            item.kind is MailboxItemKind.ACTION_MESSAGE
            and item.presentation.action is not None
            and item.presentation.action.get("type") == action_type
            for item in pending
        ):
            return True
        if await self.action_execution_repository.has_action_type_by_session_id(
            session,
            session_id=session_id,
            action_type=action_type,
        ):
            return True
        repository = self.event_transcript_repository
        return await repository.has_action_execution_result_with_type(
            session,
            session_id=session_id,
            action_type=action_type,
        )

    async def delete_by_session_and_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        buffer_id: str,
    ) -> bool:
        """Delete one pending input buffer by session and ID."""
        return await self.mailbox_item_repository.delete_by_session_and_id(
            session,
            session_id,
            buffer_id,
        )

    async def delete_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> int:
        """Delete all pending input buffers for a session."""
        return await self.mailbox_item_repository.delete_by_session_id(
            session,
            session_id,
        )

    async def move_by_session_id(
        self,
        session: AsyncSession,
        *,
        from_session_id: str,
        to_session_id: str,
    ) -> int:
        """Move pending input buffers between sessions."""
        return await self.mailbox_item_repository.move_by_session_id(
            session,
            from_session_id=from_session_id,
            to_session_id=to_session_id,
        )

    async def peek_pending_inference_profile(
        self,
        session_id: str,
    ) -> PendingInputInferenceProfile:
        """Read the next pending input profile without consuming the buffer."""
        async with self.session_manager() as session:
            buffer = await self._first_promotable_mailbox_item(session, session_id)
        return PendingInputInferenceProfile(
            mailbox_item_id=buffer.id if buffer is not None else None,
            exists=buffer is not None,
            requires_inference=(
                _buffer_requires_inference(buffer, self.turn_action_capabilities)
                if buffer is not None
                else False
            ),
            requested_inference_profile=(
                _requested_inference_profile(buffer) if buffer is not None else None
            ),
        )

    async def has_pending_session_mailbox_items(self, session_id: str) -> bool:
        """Check whether session still has unflushed MailboxItem."""
        async with self.session_manager() as session:
            return (
                await self._first_promotable_mailbox_item(session, session_id)
                is not None
            )

    async def has_pending_wake_session_mailbox_items(self, session_id: str) -> bool:
        """Check whether pending input can start or resume an idle session."""
        async with self.session_manager() as session:
            pending = await self.mailbox_item_repository.list_for_flush(
                session,
                session_id,
            )
            for buffer in pending:
                if buffer.scheduling_mode is MailboxSchedulingMode.WAKE_SESSION:
                    return True
            return False

    async def has_pending_agent_messages(self, session_id: str) -> bool:
        """Check whether the session mailbox has pending agent input."""
        async with self.session_manager() as session:
            return await self.mailbox_item_repository.has_by_session_id_and_kind(
                session,
                session_id=session_id,
                kind=MailboxItemKind.AGENT_MESSAGE,
            )

    async def admit_scheduled_mailbox_head(
        self,
        *,
        session_id: str,
        owner_generation: int,
        expected_buffer_id: str | None,
    ) -> ScheduledMailboxAdmission | None:
        """Atomically admit one Scheduled FIFO head into a cycle-bound pending Run."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.lock_by_id(
                session, session_id
            )
            if agent_session is None:
                raise ValueError("AgentSession not found")
            if agent_session.owner_generation != owner_generation:
                raise MailboxOwnerGenerationStaleError(
                    "Session owner generation changed before Scheduled admission"
                )
            buffer = await self.mailbox_item_repository.lock_oldest_by_session_id(
                session, session_id
            )
            if buffer is None or buffer.id != expected_buffer_id:
                return None
            if buffer.kind not in {
                MailboxItemKind.SCHEDULED_TASK_TRIGGER,
                MailboxItemKind.SCHEDULED_TASK_CONTINUATION,
            }:
                return None
            payload = buffer.payload
            if isinstance(
                payload,
                ScheduledTaskTriggerMailboxPayload
                | ScheduledTaskContinuationMailboxPayload,
            ):
                cycle_id = payload.cycle_id
            else:
                raise ValueError("Scheduled Task mailbox payload is malformed.")
            cycle = await self.scheduled_task_cycle_repository.lock(
                session,
                agent_id=agent_session.agent_id,
                session_id=session_id,
                cycle_id=cycle_id,
            )
            if cycle is None:
                await self.mailbox_item_repository.delete_claimed_by_ids(
                    session, session_id, [buffer.id]
                )
                await session.commit()
                return ScheduledMailboxAdmission(run=None, promoted=None, stale=True)

            if buffer.kind is MailboxItemKind.SCHEDULED_TASK_TRIGGER:
                task = await self.scheduled_task_repository.get_by_session_and_id(
                    session,
                    session_id=session_id,
                    task_id=cycle.state.task_id,
                    lock=True,
                )
                if (
                    cycle.state.phase != "admitted"
                    or task is None
                    or task.active_cycle_id != cycle_id
                    or task.active_scheduled_for != cycle.state.scheduled_for
                ):
                    await self.scheduled_task_cycle_repository.delete_if_admitted(
                        session,
                        agent_id=agent_session.agent_id,
                        session_id=session_id,
                        cycle_id=cycle_id,
                    )
                    await self.mailbox_item_repository.delete_claimed_by_ids(
                        session, session_id, [buffer.id]
                    )
                    await session.commit()
                    return ScheduledMailboxAdmission(
                        run=None, promoted=None, stale=True
                    )
            elif cycle.state.phase != "started":
                await self.mailbox_item_repository.delete_claimed_by_ids(
                    session, session_id, [buffer.id]
                )
                await session.commit()
                return ScheduledMailboxAdmission(run=None, promoted=None, stale=True)

            run = await self.agent_run_repository.create_pending(
                session,
                session_id=session_id,
                parent_agent_run_id=None,
                scheduled_task_cycle_id=cycle_id,
            )
            started_at = datetime.datetime.now(datetime.UTC)
            if buffer.kind is MailboxItemKind.SCHEDULED_TASK_TRIGGER:
                await self.scheduled_task_cycle_repository.start(
                    session, record=cycle, run_id=run.id, started_at=started_at
                )
            else:
                await self.scheduled_task_cycle_repository.bind_run(
                    session, record=cycle, run_id=run.id
                )
            promoted = self._scheduled_promoted_item(buffer, cycle)
            inserted = await self._append_mailbox_item_events(
                session, session_id, [promoted]
            )
            event_ids = [event.id for event in inserted]
            await self.agent_run_repository.associate_input_events(
                session, run_id=run.id, event_ids=event_ids
            )
            deleted = await self.mailbox_item_repository.delete_claimed_by_ids(
                session, session_id, [buffer.id]
            )
            if deleted != 1:
                raise RuntimeError("Scheduled Task mailbox admission lost its FIFO row")
            await session.commit()
            return ScheduledMailboxAdmission(
                run=run,
                promoted=PromotedMailboxItems(
                    turn_effect=TurnEffect.ELIGIBLE,
                    operation_action=None,
                    requested_inference_profile=None,
                    user_messages=[promoted.user_message]
                    if promoted.user_message is not None
                    else [],
                    events=inserted,
                    promoted_event_ids=event_ids,
                    deleted_buffer_ids=[buffer.id],
                    changed_session_agent_ids=[],
                    claimed_count=1,
                    inserted_count=len(inserted),
                    deduped_count=0,
                    complete_run=False,
                    suppress_parent_result=False,
                ),
                stale=False,
            )

    async def flush_session_mailbox_items(
        self,
        *,
        session_id: str,
        owner_generation: int,
        model: str | None,
        required_inference_profile: RequestedInferenceProfile | None,
        expected_buffer_id: str | None,
        prepared_inference_state: SessionInferenceState | None,
        profile_resolution_failure: str | None,
        active_run_id: str | None,
        limit: int | None = None,
        include_action_messages: bool = True,
    ) -> PromotedMailboxItems:
        """Flush pending buffers of session in claim, append, delete order."""
        del model
        del limit
        prepared_files = await self._prepare_mailbox_item_attachments(
            session_id=session_id,
            expected_buffer_id=expected_buffer_id,
            include_action_messages=include_action_messages,
            owner_generation=owner_generation,
            active_run_id=active_run_id,
        )
        async with (
            self._discard_prepared_model_files_on_failure(prepared_files),
            self.session_manager() as session,
        ):
            agent_session = await self.agent_session_repository.lock_by_id(
                session,
                session_id,
            )
            if agent_session is None:
                raise ValueError("AgentSession not found")
            if agent_session.owner_generation != owner_generation:
                raise MailboxOwnerGenerationStaleError(
                    "Session owner generation changed before input promotion"
                )
            oldest = await self.mailbox_item_repository.lock_oldest_by_session_id(
                session,
                session_id,
            )
            actual_buffer_id = oldest.id if oldest is not None else None
            if actual_buffer_id != expected_buffer_id:
                raise MailboxPreparationStaleError(
                    "Input buffer FIFO head changed during preparation"
                )
            claimed = [oldest] if oldest is not None else []
            if not claimed:
                return PromotedMailboxItems(
                    turn_effect=TurnEffect.NEUTRAL,
                    operation_action=None,
                    requested_inference_profile=None,
                    user_messages=[],
                    events=[],
                    promoted_event_ids=[],
                    deleted_buffer_ids=[],
                    changed_session_agent_ids=[],
                    claimed_count=0,
                    inserted_count=0,
                    deduped_count=0,
                    complete_run=False,
                    suppress_parent_result=False,
                )

            outcome = await self._promote_claimed_buffers(
                session,
                session_id=session_id,
                claimed=claimed,
                required_inference_profile=required_inference_profile,
                prepared_inference_state=prepared_inference_state,
                prepared_files=prepared_files,
                profile_resolution_failure=profile_resolution_failure,
                include_action_messages=include_action_messages,
                active_run_id=active_run_id,
            )
            promoted = outcome.promoted
            operation_action = outcome.operation_action
            if operation_action is not None:
                execution = await self.action_execution_repository.create(
                    session,
                    ActionExecutionCreate(
                        id=None,
                        session_id=session_id,
                        mailbox_item_id=operation_action.buffer.id,
                        sender_user_id=operation_action.buffer.sender_user_id,
                        action_type=operation_action.action.type,
                        action=_JSON_OBJECT_ADAPTER.validate_python(
                            operation_action.action.model_dump(mode="json")
                        ),
                        status=ActionExecutionStatus.PENDING,
                        owner_generation=agent_session.owner_generation,
                    ),
                )
                operation_action = dataclasses.replace(
                    operation_action,
                    execution=execution,
                )
            event_inserted = await self._append_mailbox_item_events(
                session,
                session_id,
                promoted,
            )
            for event in event_inserted:
                title = initial_title_from_event(event)
                if title is not None:
                    await self.agent_session_repository.set_initial_auto_title_if_unset(
                        session,
                        session_id=session_id,
                        title=title,
                        event_id=event.id,
                    )
            events_by_external_id = {
                event.external_id: event
                for event in event_inserted
                if event.external_id is not None
            }
            deduped = [
                item
                for item in promoted
                if item.external_id not in events_by_external_id
            ]
            missing: list[str] = []
            for item in deduped:
                existing = await self.event_transcript_repository.get_by_external_id(
                    session,
                    session_id,
                    item.external_id,
                )
                if existing is None:
                    missing.append(item.external_id)
                else:
                    events_by_external_id[item.external_id] = existing
            if missing:
                raise RuntimeError("Conflicted input buffer event was not found")
            for item in promoted:
                if not item.initial_title_eligible:
                    continue
                event = events_by_external_id[item.external_id]
                title = initial_title_from_external_channel_event(event)
                if title is not None:
                    await self.agent_session_repository.set_initial_auto_title_if_unset(
                        session,
                        session_id=session_id,
                        title=title,
                        event_id=event.id,
                    )

            promoted_event_ids = list(
                dict.fromkeys(
                    events_by_external_id[item.external_id].id for item in promoted
                )
            )
            changed_session_agent_ids = await self._acknowledge_promoted_agent_results(
                session,
                session_id=session_id,
                promoted=promoted,
            )
            if active_run_id is not None:
                await self.agent_run_repository.associate_input_events(
                    session,
                    run_id=active_run_id,
                    event_ids=promoted_event_ids,
                )
            buffer_ids = list(dict.fromkeys(item.buffer.id for item in promoted))
            if operation_action is not None:
                buffer_ids.append(operation_action.buffer.id)
            deleted_count = await self.mailbox_item_repository.delete_claimed_by_ids(
                session,
                session_id,
                buffer_ids,
            )
            if deleted_count != len(buffer_ids):
                logger.warning(
                    "Input buffer flush deleted a different row count",
                    extra={
                        "session_id": session_id,
                        "claimed_count": len(buffer_ids),
                        "deleted_count": deleted_count,
                    },
                )

        return PromotedMailboxItems(
            turn_effect=outcome.turn_effect,
            operation_action=operation_action,
            requested_inference_profile=(
                _requested_inference_profile(promoted[0].buffer) if promoted else None
            ),
            user_messages=[
                item.user_message for item in promoted if item.user_message is not None
            ],
            events=event_inserted,
            promoted_event_ids=promoted_event_ids,
            deleted_buffer_ids=buffer_ids,
            changed_session_agent_ids=changed_session_agent_ids,
            claimed_count=len(buffer_ids),
            inserted_count=len(event_inserted),
            deduped_count=len(deduped),
            complete_run=outcome.complete_run,
            suppress_parent_result=outcome.suppress_parent_result,
        )

    async def _acknowledge_promoted_agent_results(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        promoted: list[_PromotedMailboxItem],
    ) -> list[str]:
        """Advance source cursors for terminal results consumed by the model."""
        result_payloads: list[AgentMessagePayload] = []
        for item in promoted:
            if item.event_kind is not EventKind.AGENT_MESSAGE:
                continue
            payload = _AGENT_MESSAGE_ADAPTER.validate_python(item.payload)
            if payload.message_kind == "agent_result":
                result_payloads.append(payload)
        if not result_payloads:
            return []

        repository = self.agent_session_repository
        target = await repository.get_session_agent_by_session_id(session, session_id)
        if target is None:
            return []

        changed_ids: list[str] = []
        for payload in result_payloads:
            if payload.target_session_agent_id != target.id:
                continue
            assert payload.source_run_id is not None
            assert payload.source_run_index is not None
            assert payload.run_status is not None
            source = await repository.get_session_agent_by_id(
                session,
                payload.source_session_agent_id,
            )
            run = await self.agent_run_repository.get_by_id(
                session,
                payload.source_run_id,
            )
            if (
                source is None
                or source.parent_session_agent_id != target.id
                or run is None
                or run.session_id != source.agent_session_id
                or run.run_index != payload.source_run_index
                or run.status != payload.run_status
                or run.terminal_result_event_id
                != payload.source_terminal_result_event_id
            ):
                continue
            updated = await repository.advance_session_agent_observation_cursor(
                session,
                session_agent_id=payload.source_session_agent_id,
                parent_session_agent_id=target.id,
                parent_observed_run_index=payload.source_run_index,
                parent_observed_event_id=payload.source_terminal_result_event_id,
            )
            if updated is not None:
                changed_ids.append(updated.id)
        return list(dict.fromkeys(changed_ids))

    def _scheduled_promoted_item(
        self,
        buffer: MailboxItem,
        cycle: ScheduledTaskCycleRecord,
    ) -> _PromotedMailboxItem:
        """Render Scheduled input from the immutable cycle snapshot."""
        state = cycle.state
        content = render_scheduled_task_runtime_message(
            title=state.title,
            objective=state.objective,
            schedule_type=state.schedule_type,
            scheduled_at=state.scheduled_at,
            cron_expression=state.cron_expression,
            timezone=state.timezone,
            scheduled_for=state.scheduled_for,
        )
        user_message = make_run_user_message(
            sender_user_id=None,
            content=content,
            metadata={"scheduled_task": "true"},
            attachments=[],
            external_id=f"{buffer.id}:scheduled_task",
            attachment_source="mailbox_item",
            requested_inference_profile=None,
        )
        if buffer.kind is MailboxItemKind.SCHEDULED_TASK_TRIGGER:
            event_kind = EventKind.SCHEDULED_TASK_TRIGGER
            payload = ScheduledTaskTriggerPayload(
                cycle_id=state.cycle_id,
                title=state.title,
                content=content,
            )
        else:
            event_kind = EventKind.SCHEDULED_TASK_CONTINUATION
            payload = ScheduledTaskContinuationPayload(
                cycle_id=state.cycle_id,
                title=state.title,
                content=content,
            )
        return _PromotedMailboxItem(
            buffer=buffer,
            user_message=user_message,
            event_kind=event_kind,
            payload=_JSON_OBJECT_ADAPTER.validate_python(
                payload.model_dump(mode="json")
            ),
            external_id=f"{buffer.id}:scheduled_task",
        )

    async def _prepare_mailbox_item_attachments(
        self,
        *,
        session_id: str,
        expected_buffer_id: str | None,
        include_action_messages: bool,
        owner_generation: int,
        active_run_id: str | None,
    ) -> PreparedMailboxFiles:
        """Resolve the FIFO head attachments without holding a database session."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            buffer = await self._first_promotable_mailbox_item(session, session_id)
        if agent_session is None:
            raise ValueError("AgentSession not found")
        actual_buffer_id = buffer.id if buffer is not None else None
        if actual_buffer_id != expected_buffer_id:
            raise MailboxPreparationStaleError(
                "Input buffer FIFO head changed during preparation"
            )
        if buffer is None:
            return PreparedMailboxFiles(
                attachments=[],
                file_parts=[],
                created_model_file_ids=[],
            )

        file_parts = list(buffer.presentation.file_parts)
        if (
            buffer.kind is MailboxItemKind.ACTION_MESSAGE
            and not include_action_messages
        ):
            return PreparedMailboxFiles(
                attachments=[],
                file_parts=file_parts,
                created_model_file_ids=[],
            )
        if file_parts:
            return PreparedMailboxFiles(
                attachments=[],
                file_parts=file_parts,
                created_model_file_ids=[],
            )
        if not buffer.presentation.attachments:
            return PreparedMailboxFiles(
                attachments=[],
                file_parts=file_parts,
                created_model_file_ids=[],
            )
        if active_run_id is None:
            raise MailboxPreparationStaleError(
                "Attachment materialization requires an active AgentRun"
            )
        async with self.session_manager() as session:
            repository = self.agent_session_repository
            current_agent_session = await repository.get_by_id(
                session,
                session_id,
            )
            get_root = repository.get_root_session_agent_by_session_id
            root = await get_root(
                session,
                session_id,
            )
            run = await self.agent_run_repository.get_by_id(session, active_run_id)
        if (
            current_agent_session is None
            or root is None
            or run is None
            or run.session_id != session_id
            or run.status not in {AgentRunStatus.PENDING, AgentRunStatus.RUNNING}
            or current_agent_session.workspace_id != agent_session.workspace_id
            or current_agent_session.agent_id != agent_session.agent_id
            or current_agent_session.status is not AgentSessionStatus.ACTIVE
            or current_agent_session.owner_generation != owner_generation
        ):
            raise MailboxPreparationStaleError(
                "Canonical resource authority changed before attachment materialization"
            )
        authority = SessionResourceAuthority(
            workspace_id=current_agent_session.workspace_id,
            agent_id=current_agent_session.agent_id,
            session_id=session_id,
            root_session_id=root.agent_session_id,
            run_id=run.id,
            run_index=run.run_index,
            owner_generation=owner_generation,
        )
        materialized = await materialize_admitted_input_exchange_file_attachments(
            buffer.presentation.attachments,
            authority=authority,
            exchange_file_service=self.exchange_file_service,
            model_file_service=self.model_file_service,
        )
        file_parts.extend(materialized.file_parts)
        return PreparedMailboxFiles(
            attachments=materialized.attachments,
            file_parts=file_parts,
            created_model_file_ids=[
                part.model_file_id for part in materialized.file_parts
            ],
        )

    async def _first_promotable_mailbox_item(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> MailboxItem | None:
        """Return the current FIFO head without consuming it."""
        pending = await self.mailbox_item_repository.list_for_flush(
            session,
            session_id,
            limit=1,
        )
        return pending[0] if pending else None

    @asynccontextmanager
    async def _discard_prepared_model_files_on_failure(
        self,
        prepared_files: PreparedMailboxFiles,
    ) -> AsyncIterator[None]:
        """Discard newly created ModelFiles if FIFO promotion fails."""
        try:
            yield
        except asyncio.CancelledError:
            if prepared_files.created_model_file_ids:
                try:
                    await asyncio.shield(
                        self.model_file_service.discard_pending_input(
                            model_file_ids=prepared_files.created_model_file_ids,
                        )
                    )
                except Exception:
                    logger.exception(
                        "Failed to discard prepared ModelFiles after cancellation",
                        extra={
                            "model_file_ids": prepared_files.created_model_file_ids,
                        },
                    )
            raise
        except Exception:
            if prepared_files.created_model_file_ids:
                try:
                    await self.model_file_service.discard_pending_input(
                        model_file_ids=prepared_files.created_model_file_ids,
                    )
                except Exception:
                    logger.exception(
                        "Failed to discard prepared ModelFiles after promotion failure",
                        extra={
                            "model_file_ids": prepared_files.created_model_file_ids,
                        },
                    )
            raise

    async def _promote_claimed_buffers(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        claimed: list[MailboxItem],
        required_inference_profile: RequestedInferenceProfile | None,
        prepared_inference_state: SessionInferenceState | None,
        prepared_files: PreparedMailboxFiles,
        profile_resolution_failure: str | None,
        include_action_messages: bool,
        active_run_id: str | None,
    ) -> MailboxPreparationOutcome:
        """Dispatch exactly one FIFO head to the closed processor registry."""
        if not claimed:
            return MailboxPreparationOutcome(
                promoted=[],
                turn_effect=TurnEffect.NEUTRAL,
                operation_action=None,
                complete_run=False,
                suppress_parent_result=False,
            )
        buffer = claimed[0]
        if (
            buffer.kind == MailboxItemKind.ACTION_MESSAGE
            and not include_action_messages
        ):
            return MailboxPreparationOutcome(
                promoted=[],
                turn_effect=TurnEffect.NEUTRAL,
                operation_action=None,
                complete_run=False,
                suppress_parent_result=False,
            )
        context = MailboxPreparationContext(
            session=session,
            session_id=session_id,
            active_run_id=active_run_id,
            required_inference_profile=required_inference_profile,
            prepared_inference_state=prepared_inference_state,
            prepared_files=prepared_files,
        )
        if buffer.kind is MailboxItemKind.TURN_ACTION_CONTINUATION:
            fenced = await _turn_action_continuation_predecessor_fence(
                self,
                context,
                buffer,
            )
            if fenced is not None:
                return fenced
        if (
            _buffer_requires_inference(buffer, self.turn_action_capabilities)
            and profile_resolution_failure is not None
        ):
            return _preparation_outcome(
                [_system_error_promoted_buffer(buffer, profile_resolution_failure)],
                TurnEffect.FAILED,
            )
        processor = self._processor_for(buffer)
        return await processor.process(context, buffer)

    def _processor_for(self, buffer: MailboxItem) -> MailboxProcessor:
        """Resolve one Buffer through the explicit closed processor registry."""
        match buffer.kind:
            case MailboxItemKind.USER_MESSAGE:
                return _UserMessageMailboxProcessor(self)
            case MailboxItemKind.GOAL_CONTINUATION:
                return _GoalContinuationMailboxProcessor(self)
            case MailboxItemKind.EXTERNAL_CHANNEL_CONTINUATION:
                return _ExternalChannelContinuationMailboxProcessor(self)
            case (
                MailboxItemKind.SCHEDULED_TASK_TRIGGER
                | MailboxItemKind.SCHEDULED_TASK_CONTINUATION
            ):
                return _ScheduledTaskMailboxProcessor(self)
            case MailboxItemKind.TURN_ACTION_CONTINUATION:
                return _TurnActionContinuationMailboxProcessor(self)
            case MailboxItemKind.AGENT_MESSAGE:
                return _AgentMessageMailboxProcessor(self)
            case MailboxItemKind.EXTERNAL_CHANNEL_MESSAGE:
                return ExternalChannelMessageMailboxProcessor(self)
            case MailboxItemKind.ACTION_MESSAGE:
                if buffer.presentation.action is None:
                    raise ValueError(
                        "Action message input buffer requires action payload"
                    )
                action = self.turn_action_capabilities.decode(
                    buffer.presentation.action
                )
                return _TurnActionMailboxProcessor(self, action)
            case _:
                assert_never(buffer.kind)

    @staticmethod
    def buffer_to_user_message(
        buffer: MailboxItem,
        *,
        external_id: str | None = None,
        fallback_profile: RequestedInferenceProfile | None,
        prepared_inference_state: SessionInferenceState | None,
        prepared_files: PreparedMailboxFiles,
    ) -> RunUserMessage:
        """Convert a prepared MailboxItem snapshot to a run user message."""
        requested_profile = _requested_inference_profile(buffer) or fallback_profile
        if prepared_inference_state is not None:
            applied_profile = prepared_inference_state.applied_profile
        elif requested_profile is not None:
            applied_profile = AppliedInferenceProfile(
                model_target_label=requested_profile.model_target_label,
                model_display_name=None,
                reasoning_effort=requested_profile.reasoning_effort,
            )
        else:
            applied_profile = None
        user_message = make_run_user_message(
            sender_user_id=buffer.sender_user_id,
            content=buffer.presentation.content,
            metadata={
                key: str(value) for key, value in buffer.presentation.metadata.items()
            },
            attachments=prepared_files.attachments,
            file_parts=prepared_files.file_parts,
            external_id=external_id or buffer.id,
            attachment_source="mailbox_item",
            requested_inference_profile=requested_profile,
        )
        return dataclasses.replace(
            user_message,
            payload=user_message.payload.model_copy(
                update={"applied_inference_profile": applied_profile}
            ),
        )

    async def _append_mailbox_item_events(
        self,
        session: AsyncSession,
        session_id: str,
        promoted: list[_PromotedMailboxItem],
    ) -> list[Event]:
        """Append MailboxItem event input to transcript."""
        inserted: list[Event] = []
        repository = self.event_transcript_repository
        for item in promoted:
            existing = await repository.get_by_external_id(
                session,
                session_id,
                item.external_id,
            )
            if existing is not None:
                continue
            inserted.append(
                await repository.append_with_deferred_session_projections(
                    session,
                    EventCreate(
                        session_id=session_id,
                        kind=item.event_kind,
                        payload={
                            **item.payload,
                            "mailbox_item_id": item.buffer.id,
                            "mailbox_item_key": (
                                item.item_key or item.buffer.presentation.item_key
                            ),
                        },
                        external_id=item.external_id,
                    ),
                )
            )
        if inserted:
            await repository.advance_session_projections(
                session,
                session_id=session_id,
                events=inserted,
            )
        return inserted


@dataclasses.dataclass(frozen=True)
class _UserMessageMailboxProcessor:
    """Prepare a user message as one durable semantic event."""

    service: MailboxService

    async def process(
        self,
        context: MailboxPreparationContext,
        buffer: MailboxItem,
    ) -> MailboxPreparationOutcome:
        user_message = self.service.buffer_to_user_message(
            buffer,
            external_id=f"{buffer.id}:user_message",
            fallback_profile=context.required_inference_profile,
            prepared_inference_state=context.prepared_inference_state,
            prepared_files=context.prepared_files,
        )
        return _preparation_outcome(
            [
                _PromotedMailboxItem(
                    buffer=buffer,
                    user_message=user_message,
                    event_kind=EventKind.USER_MESSAGE,
                    payload=_user_message_payload_json(user_message),
                    external_id=user_message.external_id,
                )
            ],
            TurnEffect.ELIGIBLE,
        )


@dataclasses.dataclass(frozen=True)
class _GoalContinuationMailboxProcessor:
    """Prepare a Goal continuation event."""

    service: MailboxService

    async def process(
        self,
        context: MailboxPreparationContext,
        buffer: MailboxItem,
    ) -> MailboxPreparationOutcome:
        user_message = self.service.buffer_to_user_message(
            buffer,
            external_id=f"{buffer.id}:goal_continuation",
            fallback_profile=context.required_inference_profile,
            prepared_inference_state=context.prepared_inference_state,
            prepared_files=context.prepared_files,
        )
        return _preparation_outcome(
            [
                _PromotedMailboxItem(
                    buffer=buffer,
                    user_message=user_message,
                    event_kind=EventKind.GOAL_CONTINUATION,
                    payload=_user_message_payload_json(user_message),
                    external_id=user_message.external_id,
                )
            ],
            TurnEffect.ELIGIBLE,
        )


@dataclasses.dataclass(frozen=True)
class _ExternalChannelContinuationMailboxProcessor:
    """Prepare an External Channel continuation event."""

    service: MailboxService

    async def process(
        self,
        context: MailboxPreparationContext,
        buffer: MailboxItem,
    ) -> MailboxPreparationOutcome:
        user_message = self.service.buffer_to_user_message(
            buffer,
            external_id=f"{buffer.id}:external_channel_continuation",
            fallback_profile=context.required_inference_profile,
            prepared_inference_state=context.prepared_inference_state,
            prepared_files=context.prepared_files,
        )
        return _preparation_outcome(
            [
                _PromotedMailboxItem(
                    buffer=buffer,
                    user_message=user_message,
                    event_kind=EventKind.EXTERNAL_CHANNEL_CONTINUATION,
                    payload=_user_message_payload_json(user_message),
                    external_id=user_message.external_id,
                )
            ],
            TurnEffect.ELIGIBLE,
        )


@dataclasses.dataclass(frozen=True)
class _ScheduledTaskMailboxProcessor:
    """Promote a Scheduled Task trigger or continuation as typed input."""

    service: MailboxService

    async def process(
        self,
        context: MailboxPreparationContext,
        buffer: MailboxItem,
    ) -> MailboxPreparationOutcome:
        del context, buffer
        return _preparation_outcome([], TurnEffect.NEUTRAL)


@dataclasses.dataclass(frozen=True)
class _TurnActionContinuationMailboxProcessor:
    """Promote one bridge continuation only after its predecessor is terminal."""

    service: MailboxService

    async def process(
        self,
        context: MailboxPreparationContext,
        buffer: MailboxItem,
    ) -> MailboxPreparationOutcome:
        del context
        if not isinstance(buffer.payload, TurnActionContinuationMailboxPayload):
            raise ValueError(
                "TurnAction continuation MailboxItem payload is malformed."
            )
        reminder = SystemReminderPayload(
            text=_turn_action_continuation_text(buffer.payload)
        )
        return _preparation_outcome(
            [
                _PromotedMailboxItem(
                    buffer=buffer,
                    user_message=None,
                    event_kind=EventKind.SYSTEM_REMINDER,
                    payload=_JSON_OBJECT_ADAPTER.validate_python(
                        reminder.model_dump(mode="json")
                    ),
                    external_id=(
                        f"turn_action_continuation:{buffer.payload.action_execution_id}"
                    ),
                )
            ],
            TurnEffect.ELIGIBLE,
        )


async def _turn_action_continuation_predecessor_fence(
    service: MailboxService,
    context: MailboxPreparationContext,
    buffer: MailboxItem,
) -> MailboxPreparationOutcome | None:
    """Keep a bridge continuation durable until its predecessor is terminal."""
    if not isinstance(buffer.payload, TurnActionContinuationMailboxPayload):
        raise ValueError("TurnAction continuation MailboxItem payload is malformed.")
    predecessor = await service.agent_run_repository.get_by_id(
        context.session,
        buffer.payload.predecessor_run_id,
    )
    if predecessor is None or predecessor.session_id != context.session_id:
        raise ValueError("TurnAction continuation predecessor Run is invalid.")
    if predecessor.status not in {
        AgentRunStatus.PENDING,
        AgentRunStatus.RUNNING,
    }:
        return None
    return MailboxPreparationOutcome(
        promoted=[],
        turn_effect=TurnEffect.NEUTRAL,
        operation_action=None,
        complete_run=context.active_run_id == predecessor.id,
        suppress_parent_result=context.active_run_id == predecessor.id,
    )


@dataclasses.dataclass(frozen=True)
class _AgentMessageMailboxProcessor:
    """Prepare one inter-agent mailbox message."""

    service: MailboxService

    async def process(
        self,
        context: MailboxPreparationContext,
        buffer: MailboxItem,
    ) -> MailboxPreparationOutcome:
        user_message = self.service.buffer_to_user_message(
            buffer,
            external_id=f"{buffer.id}:agent_message",
            fallback_profile=context.required_inference_profile,
            prepared_inference_state=context.prepared_inference_state,
            prepared_files=context.prepared_files,
        )
        return _preparation_outcome(
            [
                _PromotedMailboxItem(
                    buffer=buffer,
                    user_message=user_message,
                    event_kind=EventKind.AGENT_MESSAGE,
                    payload=_JSON_OBJECT_ADAPTER.validate_python(
                        _agent_message_payload(buffer).model_dump(mode="json")
                    ),
                    external_id=user_message.external_id,
                )
            ],
            TurnEffect.ELIGIBLE,
        )


def build_external_channel_mailbox_payload(
    item: ExternalChannelMailboxProjectionItem,
    *,
    context_omitted: bool,
    initial_title_eligible: bool,
) -> ExternalChannelMessageMailboxPayload:
    """Materialize one immutable External Channel message at admission."""
    if not item.provider_tenant_id:
        raise ValueError("External Channel message is missing provider tenant ID.")
    payload = ExternalChannelMessagePayload(
        provider=item.provider,
        provider_tenant_id=item.provider_tenant_id,
        resource_id=item.resource_id,
        resource_label=_external_resource_label(item),
        resource_type=item.resource_type,
        binding_id=item.binding_id,
        invocation_batch_id=item.invocation_id,
        external_message_id=item.provider_message_key,
        projection_root_id=(
            f"external-channel:{item.binding_id}:{item.provider_message_key}"
        ),
        provider_message_key=item.provider_message_key,
        provider_position=item.provider_position,
        principal_id=item.principal_id,
        provider_user_id=item.provider_user_id,
        sender_display_name=item.sender_display_name,
        author_type=item.author_type,
        prompt_role=item.prompt_role,
        body=item.body,
        attachment_metadata=add_external_channel_file_locators(
            item.attachment_metadata or {},
            binding_id=item.binding_id,
            provider_message_key=item.provider_message_key,
        ),
        reference_mappings=_external_reference_mappings(item.reference_mappings),
        provider_created_at=item.provider_created_at,
        provider_updated_at=item.provider_updated_at,
        original_url=item.original_url,
        truncated_context_message_count=0,
        truncated_context_size=0,
    )
    return ExternalChannelMessageMailboxPayload(
        type=MailboxItemKind.EXTERNAL_CHANNEL_MESSAGE.value,
        items=[
            MailboxPresentationItem(
                item_key="external_channel_message:0",
                presentation_kind="external_channel_message",
                content=item.body or "",
                metadata={"external_channel_message": payload.model_dump(mode="json")},
            )
        ],
        context_omitted=context_omitted,
        initial_title_eligible=initial_title_eligible,
    )


@dataclasses.dataclass(frozen=True)
class ExternalChannelMessageMailboxProcessor:
    """Prepare one durable External Channel message row."""

    service: MailboxService

    async def process(
        self,
        context: MailboxPreparationContext,
        buffer: MailboxItem,
    ) -> MailboxPreparationOutcome:
        del context
        if not isinstance(buffer.payload, ExternalChannelMessageMailboxPayload):
            raise ValueError("External Channel MailboxItem payload is malformed.")
        embedded = buffer.payload.items[0]
        raw_payload = embedded.metadata.get("external_channel_message")
        if not isinstance(raw_payload, dict):
            raise ValueError("External Channel mailbox message is malformed.")
        payload = ExternalChannelMessagePayload.model_validate(raw_payload)
        promoted: list[_PromotedMailboxItem] = []
        if buffer.payload.context_omitted:
            reminder = SystemReminderPayload(
                text=_EXTERNAL_CHANNEL_CONTEXT_OMITTED_REMINDER
            )
            promoted.append(
                _PromotedMailboxItem(
                    buffer=buffer,
                    user_message=None,
                    event_kind=EventKind.SYSTEM_REMINDER,
                    payload=_JSON_OBJECT_ADAPTER.validate_python(
                        reminder.model_dump(mode="json")
                    ),
                    external_id=f"external-channel:{buffer.id}:context-omitted",
                    item_key="external_channel_message:context-omitted",
                )
            )
        promoted.append(
            _PromotedMailboxItem(
                buffer=buffer,
                user_message=None,
                event_kind=EventKind.EXTERNAL_CHANNEL_MESSAGE,
                payload=_JSON_OBJECT_ADAPTER.validate_python(
                    payload.model_dump(mode="json")
                ),
                external_id=payload.projection_root_id,
                item_key=embedded.item_key,
                initial_title_eligible=(
                    buffer.payload.initial_title_eligible
                    and payload.prompt_role == "invocation"
                    and payload.author_type is ExternalChannelPrincipalAuthorType.HUMAN
                ),
            )
        )
        return _preparation_outcome(promoted, TurnEffect.ELIGIBLE)


@dataclasses.dataclass(frozen=True)
class _TurnActionMailboxProcessor:
    """Prepare one closed TurnAction through its registered capability."""

    service: MailboxService
    action: TurnAction

    async def process(
        self,
        context: MailboxPreparationContext,
        buffer: MailboxItem,
    ) -> MailboxPreparationOutcome:
        prepared = await self.service.turn_action_capabilities.prepare(
            action=self.action,
            context=TurnActionPreparationContext(
                session=context.session,
                session_id=context.session_id,
                active_run_id=context.active_run_id,
                mailbox_item_id=buffer.id,
                content=buffer.presentation.content,
            ),
        )
        if prepared.handled_failure is not None:
            promoted = [_system_error_promoted_buffer(buffer, prepared.handled_failure)]
        else:
            promoted = [
                _PromotedMailboxItem(
                    buffer=buffer,
                    user_message=None,
                    event_kind=event.kind,
                    payload=event.payload,
                    external_id=f"{buffer.id}:{event.external_id_suffix}",
                )
                for event in prepared.events
            ]
            if prepared.append_user_message:
                user_message = self.service.buffer_to_user_message(
                    buffer,
                    external_id=f"{buffer.id}:user_message",
                    fallback_profile=_requested_inference_profile(buffer),
                    prepared_inference_state=context.prepared_inference_state,
                    prepared_files=context.prepared_files,
                )
                promoted.append(
                    _PromotedMailboxItem(
                        buffer=buffer,
                        user_message=user_message,
                        event_kind=EventKind.USER_MESSAGE,
                        payload=_user_message_payload_json(user_message),
                        external_id=user_message.external_id,
                    )
                )
        return MailboxPreparationOutcome(
            promoted=promoted,
            turn_effect=_turn_effect_from_action(prepared.effect),
            operation_action=(
                OperationActionInput(
                    buffer=buffer,
                    action=prepared.operation_action,
                    execution=None,
                )
                if prepared.operation_action is not None
                else None
            ),
            complete_run=False,
            suppress_parent_result=False,
        )


def _preparation_outcome(
    promoted: list[_PromotedMailboxItem],
    turn_effect: TurnEffect,
) -> MailboxPreparationOutcome:
    """Build one immutable processor result."""
    return MailboxPreparationOutcome(
        promoted=promoted,
        turn_effect=turn_effect,
        operation_action=None,
        complete_run=False,
        suppress_parent_result=False,
    )


def _turn_effect_from_action(
    effect: TurnActionPreparationEffect,
) -> TurnEffect:
    """Map the action-owned effect to the mailbox fold effect."""
    match effect:
        case TurnActionPreparationEffect.ELIGIBLE:
            return TurnEffect.ELIGIBLE
        case TurnActionPreparationEffect.NEUTRAL:
            return TurnEffect.NEUTRAL
        case TurnActionPreparationEffect.FAILED:
            return TurnEffect.FAILED
        case _:
            assert_never(effect)


def _external_resource_label(item: ExternalChannelMailboxProjectionItem) -> str:
    """Return the validated provider resource label for one projection item."""
    labels = item.resource_labels
    provider_resource_key = item.provider_resource_key
    if not isinstance(labels, dict) or not labels:
        raise ValueError("External Channel message is missing resource labels.")
    channel_id = (
        labels.get("display_name")
        or labels.get("channel_name")
        or labels.get("channel_id")
        or labels.get("parent_channel_id")
        or labels.get("thread_id")
    )
    if not isinstance(channel_id, str) or not channel_id:
        raise ValueError("External Channel message is missing resource channel label.")
    thread_ts = labels.get("thread_ts")
    if thread_ts is None and labels.get("parent_channel_id") == channel_id:
        thread_ts = labels.get("thread_id")
    if thread_ts is not None and not isinstance(thread_ts, str):
        raise ValueError("External Channel message has an invalid thread label.")
    if not isinstance(provider_resource_key, str) or not provider_resource_key:
        raise ValueError("External Channel message is missing resource identity.")
    return f"{channel_id}:{thread_ts}" if thread_ts else channel_id


def _external_reference_mappings(
    value: dict[str, object] | None,
) -> dict[str, dict[str, str]]:
    """Return a validated provider reference mapping."""
    if not isinstance(value, dict):
        return {}
    mappings: dict[str, dict[str, str]] = {}
    for category in ("users", "channels"):
        raw_entries = value.get(category)
        if not isinstance(raw_entries, dict):
            continue
        entries = {
            identifier: display_name
            for identifier, display_name in raw_entries.items()
            if isinstance(identifier, str)
            and identifier
            and isinstance(display_name, str)
            and display_name
        }
        if entries:
            mappings[category] = entries
    return mappings


def _buffer_requires_inference(
    buffer: MailboxItem,
    capabilities: TurnActionCapabilityRegistry,
) -> bool:
    """Return whether preparing the buffer needs a resolved inference state."""
    match buffer.kind:
        case (
            MailboxItemKind.USER_MESSAGE
            | MailboxItemKind.GOAL_CONTINUATION
            | MailboxItemKind.EXTERNAL_CHANNEL_CONTINUATION
            | MailboxItemKind.TURN_ACTION_CONTINUATION
            | MailboxItemKind.AGENT_MESSAGE
            | MailboxItemKind.EXTERNAL_CHANNEL_MESSAGE
        ):
            return True
        case (
            MailboxItemKind.SCHEDULED_TASK_TRIGGER
            | MailboxItemKind.SCHEDULED_TASK_CONTINUATION
        ):
            return False
        case MailboxItemKind.ACTION_MESSAGE:
            if buffer.presentation.action is None:
                raise ValueError("Action message input buffer requires action payload")
            action = capabilities.decode(buffer.presentation.action)
            return capabilities.preparation_requires_inference(action)
        case _:
            assert_never(buffer.kind)


def _turn_action_continuation_text(
    payload: TurnActionContinuationMailboxPayload,
) -> str:
    """Render bounded registered-bridge outcome text for model continuation."""
    result = payload.result
    terminal = payload.terminal_status.value
    reason = f" Reason code: {payload.reason_code}." if payload.reason_code else ""
    failure = (
        f" Failure summary: {payload.failure_summary}."
        if payload.failure_summary is not None
        else ""
    )
    cancellation = (
        f" Cancellation summary: {payload.cancellation_summary}."
        if payload.cancellation_summary is not None
        else ""
    )
    terminal_context = f"{reason}{failure}{cancellation}"
    match result:
        case AgentCreateGitWorktreeContinuationResult():
            generated = (
                f" Generated worktree path: {result.generated_worktree_path}."
                if result.generated_worktree_path is not None
                else ""
            )
            branch = (
                f" Branch: {result.branch_name}."
                if result.branch_name is not None
                else ""
            )
            commit = (
                f" Resolved base commit: {result.resolved_base_commit}."
                if result.resolved_base_commit is not None
                else ""
            )
            return (
                "The requested Agent-managed Git worktree creation reached "
                f"terminal status {terminal}. Source Project path: "
                f"{result.source_project_path}.{generated}{branch}{commit}"
                f"{terminal_context}"
            )
        case AgentRemoveGitWorktreeContinuationResult():
            branch = (
                f" Preserved branch: {result.preserved_branch_name}."
                if result.preserved_branch_name is not None
                else ""
            )
            retry = (
                f" {result.retry_guidance}" if result.retry_guidance is not None else ""
            )
            return (
                "The requested Agent-managed Git worktree removal reached "
                f"terminal status {terminal}. Worktree path: "
                f"{result.worktree_path}.{branch} Force used: "
                f"{str(result.force).lower()}. Dirty content discarded: "
                f"{str(result.dirty_content_discarded).lower()}."
                f"{terminal_context}{retry}"
            )
        case _:
            assert_never(result)


def _requested_inference_profile(
    buffer: MailboxItem,
) -> RequestedInferenceProfile | None:
    """Build typed requested profile from one durable buffer."""
    if buffer.requested_model_target_label is None:
        if buffer.requested_reasoning_effort is not None:
            raise ValueError("Reasoning effort requires a model target")
        return None
    return RequestedInferenceProfile(
        model_target_label=buffer.requested_model_target_label,
        reasoning_effort=buffer.requested_reasoning_effort,
    )


def _user_message_payload_json(
    user_message: RunUserMessage,
) -> dict[str, JSONValue]:
    """Serialize a UserMessage while preserving explicit nullable efforts."""
    payload = _JSON_OBJECT_ADAPTER.validate_python(
        user_message.payload.model_dump(mode="json", exclude_none=True)
    )
    requested_profile = user_message.payload.requested_inference_profile
    if requested_profile is not None:
        payload["requested_inference_profile"] = _JSON_OBJECT_ADAPTER.validate_python(
            requested_profile.model_dump(mode="json")
        )
    applied_profile = user_message.payload.applied_inference_profile
    if applied_profile is not None:
        payload["applied_inference_profile"] = _JSON_OBJECT_ADAPTER.validate_python(
            applied_profile.model_dump(mode="json")
        )
    return payload


def _agent_message_payload(buffer: MailboxItem) -> AgentMessagePayload:
    """Build agent_message payload from mailbox input buffer metadata."""
    payload: dict[str, object] = {
        "message_kind": buffer.presentation.metadata["message_kind"],
        "source_session_agent_id": buffer.presentation.metadata[
            "source_session_agent_id"
        ],
        "source_path": buffer.presentation.metadata["source_path"],
        "target_session_agent_id": buffer.presentation.metadata[
            "target_session_agent_id"
        ],
        "target_path": buffer.presentation.metadata["target_path"],
        "content": buffer.presentation.content,
    }
    for key in (
        "source_run_id",
        "source_run_index",
        "run_status",
        "source_terminal_result_event_id",
    ):
        value = buffer.presentation.metadata.get(key)
        if value is not None:
            payload[key] = value
    return _AGENT_MESSAGE_ADAPTER.validate_python(payload)


def _system_error_promoted_buffer(
    buffer: MailboxItem,
    content: str,
) -> _PromotedMailboxItem:
    """Create a promoted system_error for one handled preparation failure."""
    payload = SystemErrorPayload(
        content=content,
        severity="error",
        recoverable=True,
    )
    return _PromotedMailboxItem(
        buffer=buffer,
        user_message=None,
        event_kind=EventKind.SYSTEM_ERROR,
        payload=_JSON_OBJECT_ADAPTER.validate_python(
            payload.model_dump(mode="json", exclude_none=True)
        ),
        external_id=f"{buffer.id}:failure",
    )
