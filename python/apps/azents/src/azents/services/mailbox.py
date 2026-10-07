"""Session input buffer service."""

import asyncio
import dataclasses
import enum
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Protocol, assert_never

from fastapi import Depends
from pydantic import TypeAdapter

from azents.core.action_execution_data import ActionExecution
from azents.core.enums import (
    EventKind,
    ExternalChannelPrincipalAuthorType,
    MailboxItemKind,
)
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    RequestedInferenceProfile,
    SessionInferenceState,
)
from azents.core.json_value import JSONValue
from azents.core.mailbox_data import (
    AgentCreateGitWorktreeContinuationResult,
    AgentRemoveGitWorktreeContinuationResult,
    ExternalChannelMessageMailboxPayload,
    MailboxItem,
    ScheduledTaskContinuationMailboxPayload,
    ScheduledTaskTriggerMailboxPayload,
    TurnActionContinuationMailboxPayload,
)
from azents.core.mailbox_errors import (
    MailboxOwnerGenerationStaleError,
    MailboxPreparationStaleError,
)
from azents.engine.events.action_messages import (
    OperationAction,
    TurnAction,
)
from azents.engine.events.types import (
    AgentMessagePayload,
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
from azents.repos.mailbox.promotion import (
    MailboxActionExecutionCreate,
    MailboxPromotionConflict,
    MailboxPromotionConflictError,
    MailboxPromotionEvent,
    MailboxPromotionPlan,
    MailboxPromotionRepository,
)
from azents.repos.mailbox_runtime_operations import MailboxRuntimeOperations
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.services.session_title import (
    initial_title_from_user_text,
)
from azents.services.turn_action import (
    TurnActionCapabilityRegistry,
    TurnActionPreparationContext,
    TurnActionPreparationEffect,
    TurnActionPreparationResult,
)

logger = logging.getLogger(__name__)
_JSON_OBJECT_ADAPTER = TypeAdapter[dict[str, JSONValue]](dict[str, JSONValue])
_AGENT_MESSAGE_ADAPTER = TypeAdapter(AgentMessagePayload)
_EXTERNAL_CHANNEL_CONTEXT_OMITTED_REMINDER = (
    "Earlier messages from this external conversation were omitted. "
    "Only the newest 20 provider messages are included below."
)


@dataclasses.dataclass(frozen=True)
class PendingInputInferenceProfile:
    """Inference requirements projected from the next pending input."""

    mailbox_item_id: str | None
    exists: bool
    requires_inference: bool
    requested_inference_profile: RequestedInferenceProfile | None


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
class PreparedMailboxPromotion:
    """Detached FIFO snapshot and all external preparation results."""

    agent_id: str
    workspace_id: str
    buffer: MailboxItem | None
    files: PreparedMailboxFiles
    turn_action: TurnActionPreparationResult | None


@dataclasses.dataclass(frozen=True)
class MailboxPreparationContext:
    """Shared context passed to one closed input-buffer processor."""

    session_id: str
    active_run_id: str | None
    required_inference_profile: RequestedInferenceProfile | None
    prepared_inference_state: SessionInferenceState | None
    prepared_files: PreparedMailboxFiles
    prepared_turn_action: TurnActionPreparationResult | None


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

    runtime_operations: Annotated[
        MailboxRuntimeOperations, Depends(MailboxRuntimeOperations)
    ]
    exchange_file_service: Annotated[ExchangeFileService, Depends(ExchangeFileService)]
    model_file_service: Annotated[ModelFileService, Depends(ModelFileService)]
    turn_action_capabilities: Annotated[TurnActionCapabilityRegistry, Depends()]
    promotion_repository: Annotated[MailboxPromotionRepository, Depends()]

    async def peek_pending_inference_profile(
        self,
        session_id: str,
    ) -> PendingInputInferenceProfile:
        """Read the next pending input profile without consuming the buffer."""
        buffer = await self.runtime_operations.first_promotable(session_id)
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
        """Check whether the current FIFO head remains pending."""
        return await self.runtime_operations.first_promotable(session_id) is not None

    async def has_pending_wake_session_mailbox_items(self, session_id: str) -> bool:
        """Check whether pending input can start or resume an idle session."""
        return await self.runtime_operations.has_pending_wake_items(session_id)

    async def has_pending_agent_messages(self, session_id: str) -> bool:
        """Check whether the session mailbox has pending agent input."""
        return await self.runtime_operations.has_pending_agent_messages(session_id)

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
        """Prepare external input state, then atomically promote one FIFO head."""
        del model, limit
        preflight = await self._prepare_mailbox_item_attachments(
            session_id=session_id,
            expected_buffer_id=expected_buffer_id,
            include_action_messages=include_action_messages,
            owner_generation=owner_generation,
            active_run_id=active_run_id,
        )
        async with self._discard_prepared_model_files_on_failure(preflight.files):
            claimed = [preflight.buffer] if preflight.buffer is not None else []
            outcome = await self._promote_claimed_buffers(
                session_id=session_id,
                claimed=claimed,
                required_inference_profile=required_inference_profile,
                prepared_inference_state=prepared_inference_state,
                prepared_files=preflight.files,
                prepared_turn_action=preflight.turn_action,
                profile_resolution_failure=profile_resolution_failure,
                include_action_messages=include_action_messages,
                active_run_id=active_run_id,
            )
            failure_promoted: list[_PromotedMailboxItem] = []
            finalization_failure = (
                preflight.turn_action.finalization_failure
                if preflight.turn_action is not None
                else None
            )
            if preflight.buffer is not None and finalization_failure is not None:
                failure_promoted = [
                    _system_error_promoted_buffer(
                        preflight.buffer, finalization_failure
                    )
                ]
            operation = outcome.operation_action
            action_execution = None
            if operation is not None:
                action_execution = MailboxActionExecutionCreate(
                    action_type=operation.action.type,
                    action=_JSON_OBJECT_ADAPTER.validate_python(
                        operation.action.model_dump(mode="json")
                    ),
                )
            predecessor_run_id = None
            if preflight.buffer is not None and isinstance(
                preflight.buffer.payload, TurnActionContinuationMailboxPayload
            ):
                predecessor_run_id = preflight.buffer.payload.predecessor_run_id
            try:
                committed = await self.promotion_repository.promote(
                    MailboxPromotionPlan(
                        session_id=session_id,
                        owner_generation=owner_generation,
                        expected_buffer_id=expected_buffer_id,
                        active_run_id=active_run_id,
                        consume_buffer=bool(outcome.promoted or operation is not None),
                        success_events=[
                            _mailbox_promotion_event(item) for item in outcome.promoted
                        ],
                        failure_events=[
                            _mailbox_promotion_event(item) for item in failure_promoted
                        ],
                        goal_create=(
                            preflight.turn_action.goal_create
                            if (
                                preflight.turn_action is not None
                                and profile_resolution_failure is None
                                and not failure_promoted
                            )
                            else None
                        ),
                        skill_revalidation=(
                            preflight.turn_action.skill_revalidation
                            if preflight.turn_action is not None
                            else None
                        ),
                        action_execution=action_execution,
                        continuation_predecessor_run_id=predecessor_run_id,
                    )
                )
            except MailboxPromotionConflictError as exc:
                if exc.conflict is MailboxPromotionConflict.OWNER_GENERATION:
                    raise MailboxOwnerGenerationStaleError(
                        "Session owner generation changed before input promotion"
                    ) from exc
                raise MailboxPreparationStaleError(
                    "Input buffer FIFO head changed during preparation"
                ) from exc

        if committed.deferred:
            complete_run = (
                predecessor_run_id is not None and active_run_id == predecessor_run_id
            )
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
                complete_run=complete_run,
                suppress_parent_result=complete_run,
            )
        if operation is not None:
            operation = dataclasses.replace(
                operation, execution=committed.action_execution
            )
        return PromotedMailboxItems(
            turn_effect=(
                TurnEffect.FAILED
                if committed.handled_failure
                else outcome.turn_effect
                if committed.promoted_event_ids
                else TurnEffect.NEUTRAL
            ),
            operation_action=operation,
            requested_inference_profile=(
                _requested_inference_profile(preflight.buffer)
                if preflight.buffer is not None and outcome.promoted
                else None
            ),
            user_messages=(
                []
                if committed.handled_failure
                else [
                    item.user_message
                    for item in outcome.promoted
                    if item.user_message is not None and committed.promoted_event_ids
                ]
            ),
            events=committed.events,
            promoted_event_ids=committed.promoted_event_ids,
            deleted_buffer_ids=committed.deleted_buffer_ids,
            changed_session_agent_ids=committed.changed_session_agent_ids,
            claimed_count=len(committed.deleted_buffer_ids),
            inserted_count=len(committed.events),
            deduped_count=committed.deduped_count,
            complete_run=outcome.complete_run,
            suppress_parent_result=outcome.suppress_parent_result,
        )

    def _scheduled_promoted_item(
        self,
        buffer: MailboxItem,
    ) -> _PromotedMailboxItem:
        """Convert the admitted Scheduled envelope to ordinary typed turn input."""
        scheduled = buffer.payload
        if not isinstance(
            scheduled,
            ScheduledTaskTriggerMailboxPayload
            | ScheduledTaskContinuationMailboxPayload,
        ):
            raise ValueError("Scheduled Task mailbox payload is malformed.")
        content = buffer.presentation.content
        title = buffer.presentation.metadata["title"]
        if not isinstance(title, str):
            raise ValueError("Scheduled Task mailbox title is malformed.")
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
                cycle_id=scheduled.cycle_id,
                title=title,
                content=content,
            )
        else:
            event_kind = EventKind.SCHEDULED_TASK_CONTINUATION
            payload = ScheduledTaskContinuationPayload(
                cycle_id=scheduled.cycle_id,
                title=title,
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
    ) -> PreparedMailboxPromotion:
        """Resolve FIFO attachments and TurnAction I/O without an active transaction."""
        preparation = await self.runtime_operations.read_preparation(session_id)
        agent_session = preparation.agent_session
        buffer = preparation.buffer
        if agent_session is None:
            raise ValueError("AgentSession not found")
        actual_buffer_id = buffer.id if buffer is not None else None
        if actual_buffer_id != expected_buffer_id:
            raise MailboxPreparationStaleError(
                "Input buffer FIFO head changed during preparation"
            )
        files = PreparedMailboxFiles(
            attachments=[], file_parts=[], created_model_file_ids=[]
        )
        if buffer is not None:
            file_parts = list(buffer.presentation.file_parts)
            if (
                not (
                    buffer.kind is MailboxItemKind.ACTION_MESSAGE
                    and not include_action_messages
                )
                and not file_parts
                and buffer.presentation.attachments
            ):
                if active_run_id is None:
                    raise MailboxPreparationStaleError(
                        "Attachment materialization requires an active AgentRun"
                    )
                authority = await self.runtime_operations.attachment_authority(
                    session_id=session_id,
                    active_run_id=active_run_id,
                    agent_id=agent_session.agent_id,
                    workspace_id=agent_session.workspace_id,
                    owner_generation=owner_generation,
                )
                if authority is None:
                    raise MailboxPreparationStaleError(
                        "Canonical resource authority changed before attachment "
                        "materialization"
                    )
                materialized = (
                    await materialize_admitted_input_exchange_file_attachments(
                        buffer.presentation.attachments,
                        authority=authority,
                        exchange_file_service=self.exchange_file_service,
                        model_file_service=self.model_file_service,
                    )
                )
                file_parts.extend(materialized.file_parts)
                files = PreparedMailboxFiles(
                    attachments=materialized.attachments,
                    file_parts=file_parts,
                    created_model_file_ids=[
                        part.model_file_id for part in materialized.file_parts
                    ],
                )
            else:
                files = PreparedMailboxFiles(
                    attachments=[],
                    file_parts=file_parts,
                    created_model_file_ids=[],
                )
        prepared_action = None
        if (
            buffer is not None
            and buffer.kind is MailboxItemKind.ACTION_MESSAGE
            and include_action_messages
        ):
            if buffer.presentation.action is None:
                raise ValueError("Action message input buffer requires action payload")
            action = self.turn_action_capabilities.decode(buffer.presentation.action)
            prepared_action = await self.turn_action_capabilities.prepare(
                action=action,
                context=TurnActionPreparationContext(
                    agent_id=agent_session.agent_id,
                    session_id=session_id,
                    workspace_id=agent_session.workspace_id,
                    active_run_id=active_run_id,
                    mailbox_item_id=buffer.id,
                    content=buffer.presentation.content,
                ),
            )
        return PreparedMailboxPromotion(
            agent_id=agent_session.agent_id,
            workspace_id=agent_session.workspace_id,
            buffer=buffer,
            files=files,
            turn_action=prepared_action,
        )

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
        *,
        session_id: str,
        claimed: list[MailboxItem],
        required_inference_profile: RequestedInferenceProfile | None,
        prepared_inference_state: SessionInferenceState | None,
        prepared_files: PreparedMailboxFiles,
        prepared_turn_action: TurnActionPreparationResult | None,
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
            session_id=session_id,
            active_run_id=active_run_id,
            required_inference_profile=required_inference_profile,
            prepared_inference_state=prepared_inference_state,
            prepared_files=prepared_files,
            prepared_turn_action=prepared_turn_action,
        )
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
                enabled_execution_options=(requested_profile.enabled_execution_options),
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
    """Promote Scheduled input through the common FIFO turn path."""

    service: MailboxService

    async def process(
        self,
        context: MailboxPreparationContext,
        buffer: MailboxItem,
    ) -> MailboxPreparationOutcome:
        del context
        return _preparation_outcome(
            [self.service._scheduled_promoted_item(buffer)], TurnEffect.ELIGIBLE
        )


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
        prepared = context.prepared_turn_action
        if prepared is None:
            raise RuntimeError("TurnAction promotion requires prepared action state")
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


def _mailbox_promotion_event(
    item: _PromotedMailboxItem,
) -> MailboxPromotionEvent:
    """Convert one prepared item to a repository promotion command."""
    title_candidate = None
    if item.event_kind is EventKind.USER_MESSAGE and item.user_message is not None:
        title_candidate = initial_title_from_user_text(item.buffer.presentation.content)
    elif item.initial_title_eligible:
        payload = ExternalChannelMessagePayload.model_validate(item.payload)
        title_candidate = initial_title_from_user_text(payload.body or "")
    return MailboxPromotionEvent(
        kind=item.event_kind,
        payload=item.payload,
        external_id=item.external_id,
        item_key=item.item_key or item.buffer.presentation.item_key,
        initial_title_candidate=title_candidate,
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
            | MailboxItemKind.SCHEDULED_TASK_TRIGGER
            | MailboxItemKind.SCHEDULED_TASK_CONTINUATION
        ):
            return True
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
        if (
            buffer.requested_reasoning_effort is not None
            or buffer.requested_enabled_execution_options
        ):
            raise ValueError("Inference settings require a model target")
        return None
    return RequestedInferenceProfile(
        model_target_label=buffer.requested_model_target_label,
        reasoning_effort=buffer.requested_reasoning_effort,
        enabled_execution_options=buffer.requested_enabled_execution_options,
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
