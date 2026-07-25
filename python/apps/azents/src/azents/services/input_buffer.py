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
    EventKind,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    InputBufferKind,
    InputBufferSchedulingMode,
)
from azents.core.external_channel_file import add_external_channel_file_locators
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    RequestedInferenceProfile,
    SessionInferenceState,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.engine.events.action_messages import (
    ChatAction,
    CreateGitWorktreeAction,
    GoalAction,
    SkillAction,
)
from azents.engine.events.types import (
    AgentMessagePayload,
    Event,
    ExternalChannelMessagePayload,
    FileOutputPart,
    SkillLoadedPayload,
    SystemErrorPayload,
)
from azents.engine.events.user_messages import make_run_user_message
from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.io.user_input import RunUserMessage
from azents.engine.run.resolve import (
    materialize_admitted_input_exchange_file_attachments,
)
from azents.engine.tools.deps import get_vfs_projection_service
from azents.engine.tools.goal import GoalState, GoalStateSnapshot, GoalStateStore
from azents.engine.tools.skill import (
    SkillProjectionItem,
    SkillStateStore,
    resolve_active_skill,
    skill_item_from_vfs_entry,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.models.event import JSONValue
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.action_execution.data import ActionExecution, ActionExecutionCreate
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.data import ExternalChannelInvocationProjectionItem
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.input_buffer.data import InputBuffer, InputBufferCreate
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.services.session_title import initial_title_from_event
from azents.services.vfs import VfsFileResolutionError, VfsProjectionService

logger = logging.getLogger(__name__)
_JSON_OBJECT_ADAPTER = TypeAdapter[dict[str, JSONValue]](dict[str, JSONValue])
_CHAT_ACTION_ADAPTER = TypeAdapter(ChatAction)
_AGENT_MESSAGE_ADAPTER = TypeAdapter(AgentMessagePayload)
EXTERNAL_CHANNEL_INVOCATION_BATCH_ID_METADATA_KEY = (
    "external_channel_invocation_batch_id"
)


@dataclasses.dataclass(frozen=True)
class InputBufferEnqueue:
    """Input buffer enqueue request."""

    session_id: str
    kind: InputBufferKind
    scheduling_mode: InputBufferSchedulingMode
    requested_model_target_label: str | None
    requested_reasoning_effort: ModelReasoningEffort | None
    sender_user_id: str | None
    content: str
    idempotency_key: str | None
    metadata: dict[str, str]
    attachments: list[str]
    file_parts: list[FileOutputPart]
    action: dict[str, JSONValue] | None = None


@dataclasses.dataclass(frozen=True)
class InputBufferEnqueueResult:
    """Input buffer enqueue result."""

    input_buffer: InputBuffer
    created: bool


@dataclasses.dataclass(frozen=True)
class PendingInputInferenceProfile:
    """Inference requirements projected from the next pending input."""

    input_buffer_id: str | None
    exists: bool
    requires_inference: bool
    requested_inference_profile: RequestedInferenceProfile | None


class InputBufferPreparationStaleError(RuntimeError):
    """The FIFO head changed after its preparation snapshot was read."""


class TurnEffect(enum.StrEnum):
    """Effect of one prepared InputBuffer on the next model turn."""

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
class WorktreeActionInput:
    """Durably claimed buffer-only worktree action awaiting external execution."""

    buffer: InputBuffer
    action: CreateGitWorktreeAction
    execution: ActionExecution | None


@dataclasses.dataclass(frozen=True)
class PromotedInputBuffers:
    """Result of preparing one FIFO InputBuffer."""

    turn_effect: TurnEffect
    worktree_action: WorktreeActionInput | None
    requested_inference_profile: RequestedInferenceProfile | None
    user_messages: list[RunUserMessage]
    events: list[Event]
    promoted_event_ids: list[str]
    deleted_buffer_ids: list[str]
    changed_session_agent_ids: list[str]
    claimed_count: int
    inserted_count: int
    deduped_count: int


@dataclasses.dataclass(frozen=True)
class _PromotedInputBuffer:
    """Result of converting InputBuffer to model input and durable event kind."""

    buffer: InputBuffer
    user_message: RunUserMessage | None
    event_kind: EventKind
    payload: dict[str, JSONValue]
    external_id: str


@dataclasses.dataclass(frozen=True)
class PreparedInputBufferFiles:
    """Attachment metadata and creation-boundary FileParts prepared for promotion."""

    attachments: list[RuntimeAttachment]
    file_parts: list[FileOutputPart]
    created_model_file_ids: list[str]


@dataclasses.dataclass(frozen=True)
class InputBufferPreparationContext:
    """Shared context passed to one closed input-buffer processor."""

    session: AsyncSession
    session_id: str
    active_run_id: str | None
    required_inference_profile: RequestedInferenceProfile | None
    prepared_inference_state: SessionInferenceState | None
    prepared_files: PreparedInputBufferFiles


@dataclasses.dataclass(frozen=True)
class InputBufferPreparationOutcome:
    """Semantic events and turn effect produced by one processor."""

    promoted: list[_PromotedInputBuffer]
    turn_effect: TurnEffect
    worktree_action: WorktreeActionInput | None


class InputBufferProcessor(Protocol):
    """Prepare one concrete InputBuffer kind."""

    async def process(
        self,
        context: InputBufferPreparationContext,
        buffer: InputBuffer,
    ) -> InputBufferPreparationOutcome:
        """Prepare one FIFO buffer inside the caller transaction."""
        ...


@dataclasses.dataclass(frozen=True)
class InputBufferService:
    """Own session-bound input buffer reads, writes, and promotion."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    input_buffer_repository: Annotated[
        InputBufferRepository, Depends(InputBufferRepository)
    ]
    exchange_file_service: Annotated[ExchangeFileService, Depends(ExchangeFileService)]
    model_file_service: Annotated[ModelFileService, Depends(ModelFileService)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    action_execution_repository: Annotated[
        ActionExecutionRepository, Depends(ActionExecutionRepository)
    ]
    vfs_projection_service: Annotated[
        VfsProjectionService | None,
        Depends(get_vfs_projection_service),
    ]
    external_channel_repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]

    async def enqueue(
        self,
        session: AsyncSession,
        input: InputBufferEnqueue,
    ) -> InputBufferEnqueueResult:
        """Create one pending input buffer without deciding wake semantics."""
        existing = None
        if input.idempotency_key is not None:
            existing = await self.input_buffer_repository.get_by_idempotency_key(
                session,
                session_id=input.session_id,
                kind=input.kind,
                idempotency_key=input.idempotency_key,
            )
        if existing is None:
            created = True
            create = InputBufferCreate(
                session_id=input.session_id,
                kind=input.kind,
                scheduling_mode=input.scheduling_mode,
                requested_model_target_label=input.requested_model_target_label,
                requested_reasoning_effort=input.requested_reasoning_effort,
                sender_user_id=input.sender_user_id,
                content=input.content,
                idempotency_key=input.idempotency_key,
                metadata=input.metadata,
                action=input.action,
                attachments=input.attachments,
                file_parts=input.file_parts,
            )
            if input.idempotency_key is None:
                input_buffer = await self.input_buffer_repository.create(
                    session,
                    create,
                )
            else:
                input_buffer = await self.input_buffer_repository.create_idempotent(
                    session,
                    create,
                    idempotency_key=input.idempotency_key,
                )
        else:
            created = False
            input_buffer = existing
        if input_buffer.scheduling_mode != input.scheduling_mode:
            raise ValueError(
                "Input idempotency key already used for another scheduling mode"
            )
        if (
            input_buffer.requested_model_target_label
            != input.requested_model_target_label
            or input_buffer.requested_reasoning_effort
            != input.requested_reasoning_effort
        ):
            raise ValueError(
                "Input idempotency key already used for another inference profile"
            )
        return InputBufferEnqueueResult(input_buffer=input_buffer, created=created)

    async def enqueue_many(
        self,
        session: AsyncSession,
        inputs: Sequence[InputBufferEnqueue],
    ) -> list[InputBufferEnqueueResult]:
        """Create pending input buffers without deciding wake semantics."""
        results = [await self.enqueue(session, input) for input in inputs]
        return results

    async def enqueue_many_in_transaction(
        self,
        inputs: Sequence[InputBufferEnqueue],
    ) -> list[InputBufferEnqueueResult]:
        """Create pending inputs in one transaction."""
        async with self.session_manager() as session:
            return await self.enqueue_many(session, inputs)

    async def list_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> list[InputBuffer]:
        """Fetch pending input buffers for a session."""
        return await self.input_buffer_repository.list_by_session_id(
            session,
            session_id,
        )

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        buffer_id: str,
    ) -> InputBuffer | None:
        """Fetch a pending InputBuffer by its durable acceptance identity."""
        return await self.input_buffer_repository.get_by_id(session, buffer_id)

    async def delete_by_session_and_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        buffer_id: str,
    ) -> bool:
        """Delete one pending input buffer by session and ID."""
        return await self.input_buffer_repository.delete_by_session_and_id(
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
        return await self.input_buffer_repository.delete_by_session_id(
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
        return await self.input_buffer_repository.move_by_session_id(
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
            pending = await self.input_buffer_repository.list_for_flush(
                session,
                session_id,
                limit=1,
            )
        return PendingInputInferenceProfile(
            input_buffer_id=pending[0].id if pending else None,
            exists=bool(pending),
            requires_inference=(
                _buffer_requires_inference(pending[0]) if pending else False
            ),
            requested_inference_profile=(
                _requested_inference_profile(pending[0]) if pending else None
            ),
        )

    async def has_pending_session_input_buffers(self, session_id: str) -> bool:
        """Check whether session still has unflushed InputBuffer."""
        async with self.session_manager() as session:
            pending = await self.input_buffer_repository.list_for_flush(
                session,
                session_id,
                limit=1,
            )
        return bool(pending)

    async def has_pending_wake_session_input_buffers(self, session_id: str) -> bool:
        """Check whether pending input can start or resume an idle session."""
        async with self.session_manager() as session:
            repository = self.input_buffer_repository
            return await repository.has_by_session_id_and_scheduling_mode(
                session,
                session_id=session_id,
                scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
            )

    async def has_pending_agent_messages(self, session_id: str) -> bool:
        """Check whether the session mailbox has pending agent input."""
        async with self.session_manager() as session:
            return await self.input_buffer_repository.has_by_session_id_and_kind(
                session,
                session_id=session_id,
                kind=InputBufferKind.AGENT_MESSAGE,
            )

    async def flush_session_input_buffers(
        self,
        *,
        session_id: str,
        model: str | None,
        required_inference_profile: RequestedInferenceProfile | None,
        expected_buffer_id: str | None,
        prepared_inference_state: SessionInferenceState | None,
        profile_resolution_failure: str | None,
        active_run_id: str | None,
        limit: int | None = None,
        include_action_messages: bool = True,
    ) -> PromotedInputBuffers:
        """Flush pending buffers of session in claim, append, delete order."""
        del model
        del limit
        prepared_files = await self._prepare_input_buffer_attachments(
            session_id=session_id,
            expected_buffer_id=expected_buffer_id,
            include_action_messages=include_action_messages,
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
            oldest = await self.input_buffer_repository.lock_oldest_by_session_id(
                session,
                session_id,
            )
            actual_buffer_id = oldest.id if oldest is not None else None
            if actual_buffer_id != expected_buffer_id:
                raise InputBufferPreparationStaleError(
                    "Input buffer FIFO head changed during preparation"
                )
            claimed = [oldest] if oldest is not None else []
            if not claimed:
                return PromotedInputBuffers(
                    turn_effect=TurnEffect.NEUTRAL,
                    worktree_action=None,
                    requested_inference_profile=None,
                    user_messages=[],
                    events=[],
                    promoted_event_ids=[],
                    deleted_buffer_ids=[],
                    changed_session_agent_ids=[],
                    claimed_count=0,
                    inserted_count=0,
                    deduped_count=0,
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
            if (
                prepared_inference_state is not None
                and outcome.turn_effect is not TurnEffect.FAILED
                and _buffer_requires_inference(claimed[0])
            ):
                await self.agent_session_repository.set_inference_state(
                    session,
                    session_id=session_id,
                    inference_state=prepared_inference_state,
                )
            worktree_action = outcome.worktree_action
            if worktree_action is not None:
                execution = await self.action_execution_repository.create(
                    session,
                    ActionExecutionCreate(
                        id=None,
                        session_id=session_id,
                        input_buffer_id=worktree_action.buffer.id,
                        sender_user_id=worktree_action.buffer.sender_user_id,
                        action_type=worktree_action.action.type,
                        action=_JSON_OBJECT_ADAPTER.validate_python(
                            worktree_action.action.model_dump(mode="json")
                        ),
                        status=ActionExecutionStatus.PENDING,
                        owner_generation=agent_session.owner_generation,
                    ),
                )
                worktree_action = dataclasses.replace(
                    worktree_action,
                    execution=execution,
                )
            event_inserted = await self._append_input_buffer_events(
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
            if worktree_action is not None:
                buffer_ids.append(worktree_action.buffer.id)
            deleted_count = await self.input_buffer_repository.delete_claimed_by_ids(
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

        return PromotedInputBuffers(
            turn_effect=outcome.turn_effect,
            worktree_action=worktree_action,
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
        )

    async def _acknowledge_promoted_agent_results(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        promoted: list[_PromotedInputBuffer],
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

    async def _prepare_input_buffer_attachments(
        self,
        *,
        session_id: str,
        expected_buffer_id: str | None,
        include_action_messages: bool,
    ) -> PreparedInputBufferFiles:
        """Resolve the FIFO head attachments without holding a database session."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            pending = await self.input_buffer_repository.list_for_flush(
                session,
                session_id,
                limit=1,
            )
        if agent_session is None:
            raise ValueError("AgentSession not found")
        buffer = pending[0] if pending else None
        actual_buffer_id = buffer.id if buffer is not None else None
        if actual_buffer_id != expected_buffer_id:
            raise InputBufferPreparationStaleError(
                "Input buffer FIFO head changed during preparation"
            )
        if buffer is None:
            return PreparedInputBufferFiles(
                attachments=[],
                file_parts=[],
                created_model_file_ids=[],
            )

        file_parts = list(buffer.file_parts)
        if (
            buffer.kind is InputBufferKind.ACTION_MESSAGE
            and not include_action_messages
        ):
            return PreparedInputBufferFiles(
                attachments=[],
                file_parts=file_parts,
                created_model_file_ids=[],
            )
        if file_parts:
            return PreparedInputBufferFiles(
                attachments=[],
                file_parts=file_parts,
                created_model_file_ids=[],
            )
        if not buffer.attachments:
            return PreparedInputBufferFiles(
                attachments=[],
                file_parts=file_parts,
                created_model_file_ids=[],
            )
        materialized = await materialize_admitted_input_exchange_file_attachments(
            buffer.attachments,
            agent_id=agent_session.agent_id,
            session_id=buffer.session_id,
            exchange_file_service=self.exchange_file_service,
            model_file_service=self.model_file_service,
        )
        file_parts.extend(materialized.file_parts)
        return PreparedInputBufferFiles(
            attachments=materialized.attachments,
            file_parts=file_parts,
            created_model_file_ids=[
                part.model_file_id for part in materialized.file_parts
            ],
        )

    @asynccontextmanager
    async def _discard_prepared_model_files_on_failure(
        self,
        prepared_files: PreparedInputBufferFiles,
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
        claimed: list[InputBuffer],
        required_inference_profile: RequestedInferenceProfile | None,
        prepared_inference_state: SessionInferenceState | None,
        prepared_files: PreparedInputBufferFiles,
        profile_resolution_failure: str | None,
        include_action_messages: bool,
        active_run_id: str | None,
    ) -> InputBufferPreparationOutcome:
        """Dispatch exactly one FIFO head to the closed processor registry."""
        if not claimed:
            return InputBufferPreparationOutcome(
                promoted=[],
                turn_effect=TurnEffect.NEUTRAL,
                worktree_action=None,
            )
        buffer = claimed[0]
        if (
            buffer.kind == InputBufferKind.ACTION_MESSAGE
            and not include_action_messages
        ):
            return InputBufferPreparationOutcome(
                promoted=[],
                turn_effect=TurnEffect.NEUTRAL,
                worktree_action=None,
            )
        if (
            _buffer_requires_inference(buffer)
            and profile_resolution_failure is not None
        ):
            return _preparation_outcome(
                [_system_error_promoted_buffer(buffer, profile_resolution_failure)],
                TurnEffect.FAILED,
            )
        context = InputBufferPreparationContext(
            session=session,
            session_id=session_id,
            active_run_id=active_run_id,
            required_inference_profile=required_inference_profile,
            prepared_inference_state=prepared_inference_state,
            prepared_files=prepared_files,
        )
        processor = self._processor_for(buffer)
        return await processor.process(context, buffer)

    def _processor_for(self, buffer: InputBuffer) -> InputBufferProcessor:
        """Resolve one Buffer through the explicit closed processor registry."""
        match buffer.kind:
            case InputBufferKind.USER_MESSAGE:
                return _UserMessageInputBufferProcessor(self)
            case InputBufferKind.GOAL_CONTINUATION:
                return _GoalContinuationInputBufferProcessor(self)
            case InputBufferKind.AGENT_MESSAGE:
                return _AgentMessageInputBufferProcessor(self)
            case InputBufferKind.EXTERNAL_CHANNEL_INVOCATION:
                return ExternalChannelInvocationInputBufferProcessor(self)
            case InputBufferKind.ACTION_MESSAGE:
                if buffer.action is None:
                    raise ValueError(
                        "Action message input buffer requires action payload"
                    )
                action = _CHAT_ACTION_ADAPTER.validate_python(buffer.action)
                match action:
                    case GoalAction():
                        return _GoalActionInputBufferProcessor(self)
                    case SkillAction():
                        return _SkillActionInputBufferProcessor(self, action)
                    case CreateGitWorktreeAction():
                        return _CreateGitWorktreeActionInputBufferProcessor(action)
                    case _:
                        assert_never(action)
            case _:
                assert_never(buffer.kind)

    async def promote_goal_action(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        buffer: InputBuffer,
        prepared_inference_state: SessionInferenceState | None,
        prepared_files: PreparedInputBufferFiles,
    ) -> list[_PromotedInputBuffer]:
        """Apply Goal create side effect for one action_message buffer."""
        objective = buffer.content.strip()
        if not objective:
            return [
                _system_error_promoted_buffer(buffer, "Goal objective is required.")
            ]
        agent_session = await self.agent_session_repository.get_by_id(
            session,
            session_id,
        )
        if agent_session is None:
            return [_system_error_promoted_buffer(buffer, "Session not found.")]
        updated_at = datetime.datetime.now(datetime.UTC).isoformat()
        store = GoalStateStore(session_manager=self.session_manager)

        def mutate(current: GoalState) -> GoalState:
            if current.status in {"active", "paused", "blocked"} and current.objective:
                raise _GoalActionError("An unfinished goal already exists.")
            return GoalState(
                objective=objective,
                status="active",
                created_at=updated_at,
                updated_at=updated_at,
            )

        try:
            updated = await store.update_in_session(
                session,
                agent_session.agent_id,
                session_id,
                mutate,
            )
        except _GoalActionError as exc:
            return [_system_error_promoted_buffer(buffer, exc.message)]
        snapshot = GoalStateSnapshot.from_state(updated)
        user_message = self.buffer_to_user_message(
            buffer,
            external_id=f"{buffer.id}:user_message",
            fallback_profile=_requested_inference_profile(buffer),
            prepared_inference_state=prepared_inference_state,
            prepared_files=prepared_files,
        )
        return [
            _PromotedInputBuffer(
                buffer=buffer,
                user_message=None,
                event_kind=EventKind.GOAL_UPDATED,
                payload=_goal_updated_payload(snapshot, action="create"),
                external_id=f"{buffer.id}:goal_updated",
            ),
            _PromotedInputBuffer(
                buffer=buffer,
                user_message=user_message,
                event_kind=EventKind.USER_MESSAGE,
                payload=_user_message_payload_json(user_message),
                external_id=user_message.external_id,
            ),
        ]

    async def promote_skill_action(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        buffer: InputBuffer,
        action: SkillAction,
        active_run_id: str | None,
        prepared_inference_state: SessionInferenceState | None,
        prepared_files: PreparedInputBufferFiles,
    ) -> list[_PromotedInputBuffer]:
        """Create durable reminder for one Skill action_message buffer."""
        agent_session = await self.agent_session_repository.get_by_id(
            session,
            session_id,
        )
        if agent_session is None:
            return [_system_error_promoted_buffer(buffer, "Session not found.")]
        item: SkillProjectionItem | None
        if action.skill_path.startswith("azents://"):
            item = None
            if active_run_id is not None and self.vfs_projection_service is not None:
                try:
                    resolved = await self.vfs_projection_service.resolve_file(
                        run_id=active_run_id,
                        agent_id=agent_session.agent_id,
                        session_id=session_id,
                        workspace_id=agent_session.workspace_id,
                        uri=action.skill_path,
                    )
                    item = skill_item_from_vfs_entry(resolved.entry)
                except (VfsFileResolutionError, ValueError) as exc:
                    logger.warning(
                        "Managed Skill action resolution failed",
                        extra={
                            "agent_id": agent_session.agent_id,
                            "session_id": session_id,
                            "run_id": active_run_id,
                            "skill_path": action.skill_path,
                            "error_type": type(exc).__name__,
                        },
                    )
        else:
            store = SkillStateStore(session_manager=self.session_manager)
            state = await store.load_in_session(
                session,
                agent_session.agent_id,
                session_id,
            )
            item = resolve_active_skill(state, skill_path=action.skill_path)
        if item is None:
            return [
                _system_error_promoted_buffer(
                    buffer,
                    "Selected Skill is not available in the active projection.",
                )
            ]
        loaded_payload = _skill_loaded_payload(item, user_message=buffer.content)
        promoted = [
            _PromotedInputBuffer(
                buffer=buffer,
                user_message=None,
                event_kind=EventKind.SKILL_LOADED,
                payload=_JSON_OBJECT_ADAPTER.validate_python(
                    loaded_payload.model_dump(mode="json")
                ),
                external_id=f"{buffer.id}:skill_loaded",
            )
        ]
        if buffer.content.strip():
            user_message = self.buffer_to_user_message(
                buffer,
                external_id=f"{buffer.id}:user_message",
                fallback_profile=_requested_inference_profile(buffer),
                prepared_inference_state=prepared_inference_state,
                prepared_files=prepared_files,
            )
            promoted.append(
                _PromotedInputBuffer(
                    buffer=buffer,
                    user_message=user_message,
                    event_kind=EventKind.USER_MESSAGE,
                    payload=_user_message_payload_json(user_message),
                    external_id=user_message.external_id,
                )
            )
        return promoted

    @staticmethod
    def buffer_to_user_message(
        buffer: InputBuffer,
        *,
        external_id: str | None = None,
        fallback_profile: RequestedInferenceProfile | None,
        prepared_inference_state: SessionInferenceState | None,
        prepared_files: PreparedInputBufferFiles,
    ) -> RunUserMessage:
        """Convert a prepared InputBuffer snapshot to a run user message."""
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
            content=buffer.content,
            metadata=buffer.metadata,
            attachments=prepared_files.attachments,
            file_parts=prepared_files.file_parts,
            external_id=external_id or buffer.id,
            attachment_source="input_buffer",
            requested_inference_profile=requested_profile,
        )
        return dataclasses.replace(
            user_message,
            payload=user_message.payload.model_copy(
                update={"applied_inference_profile": applied_profile}
            ),
        )

    async def _append_input_buffer_events(
        self,
        session: AsyncSession,
        session_id: str,
        promoted: list[_PromotedInputBuffer],
    ) -> list[Event]:
        """Append InputBuffer event input to transcript."""
        inserted: list[Event] = []
        for item in promoted:
            existing = await self.event_transcript_repository.get_by_external_id(
                session,
                session_id,
                item.external_id,
            )
            if existing is not None:
                continue
            inserted.append(
                await self.event_transcript_repository.append(
                    session,
                    EventCreate(
                        session_id=session_id,
                        kind=item.event_kind,
                        payload=item.payload,
                        external_id=item.external_id,
                    ),
                )
            )
        return inserted


@dataclasses.dataclass(frozen=True)
class _UserMessageInputBufferProcessor:
    """Prepare a user message as one durable semantic event."""

    service: InputBufferService

    async def process(
        self,
        context: InputBufferPreparationContext,
        buffer: InputBuffer,
    ) -> InputBufferPreparationOutcome:
        user_message = self.service.buffer_to_user_message(
            buffer,
            external_id=f"{buffer.id}:user_message",
            fallback_profile=context.required_inference_profile,
            prepared_inference_state=context.prepared_inference_state,
            prepared_files=context.prepared_files,
        )
        return _preparation_outcome(
            [
                _PromotedInputBuffer(
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
class _GoalContinuationInputBufferProcessor:
    """Prepare a Goal continuation event."""

    service: InputBufferService

    async def process(
        self,
        context: InputBufferPreparationContext,
        buffer: InputBuffer,
    ) -> InputBufferPreparationOutcome:
        user_message = self.service.buffer_to_user_message(
            buffer,
            external_id=f"{buffer.id}:goal_continuation",
            fallback_profile=context.required_inference_profile,
            prepared_inference_state=context.prepared_inference_state,
            prepared_files=context.prepared_files,
        )
        return _preparation_outcome(
            [
                _PromotedInputBuffer(
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
class _AgentMessageInputBufferProcessor:
    """Prepare one inter-agent mailbox message."""

    service: InputBufferService

    async def process(
        self,
        context: InputBufferPreparationContext,
        buffer: InputBuffer,
    ) -> InputBufferPreparationOutcome:
        user_message = self.service.buffer_to_user_message(
            buffer,
            external_id=f"{buffer.id}:agent_message",
            fallback_profile=context.required_inference_profile,
            prepared_inference_state=context.prepared_inference_state,
            prepared_files=context.prepared_files,
        )
        return _preparation_outcome(
            [
                _PromotedInputBuffer(
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
class ExternalChannelInvocationInputBufferProcessor:
    """Prepare one durable external invocation batch as contiguous events."""

    service: InputBufferService

    async def process(
        self,
        context: InputBufferPreparationContext,
        buffer: InputBuffer,
    ) -> InputBufferPreparationOutcome:
        batch_id = buffer.metadata.get(
            EXTERNAL_CHANNEL_INVOCATION_BATCH_ID_METADATA_KEY
        )
        if not batch_id:
            raise ValueError(
                "External invocation InputBuffer requires an invocation batch ID."
            )
        repository = self.service.external_channel_repository
        items = await repository.list_invocation_projection_items(
            context.session,
            batch_id=batch_id,
        )
        if not items:
            raise ValueError("External invocation batch has no projection items.")
        if any(item.batch_id != batch_id for item in items):
            raise ValueError("External invocation batch projection is inconsistent.")
        if [item.sequence for item in items] != list(range(len(items))):
            raise ValueError("External invocation batch sequence is not contiguous.")

        promoted: list[_PromotedInputBuffer] = []
        for item in items:
            provider_tenant_id = item.provider_tenant_id
            if not provider_tenant_id:
                raise ValueError("External invocation is missing provider tenant ID.")
            resource_label = _external_resource_label(item)
            external_id = (
                f"external-channel:{item.binding_id}:"
                f"{item.message_id}:{item.revision_id}"
            )
            payload = ExternalChannelMessagePayload(
                provider=item.provider,
                provider_tenant_id=provider_tenant_id,
                resource_id=item.resource_id,
                resource_label=resource_label,
                resource_type=item.resource_type,
                binding_id=item.binding_id,
                invocation_batch_id=item.batch_id,
                external_message_id=item.message_id,
                revision_id=item.revision_id,
                revision_kind=item.revision_kind,
                projection_root_id=(
                    f"external-channel:{item.binding_id}:{item.message_id}"
                ),
                provider_message_key=item.provider_message_key,
                provider_position=item.provider_position,
                principal_id=item.principal_id,
                provider_user_id=item.provider_user_id,
                sender_display_name=item.sender_display_name,
                author_type=item.author_type,
                authorization=(
                    "authorized_invocation"
                    if item.message_id == item.trigger_message_id
                    else "context_only"
                ),
                lifecycle=_external_message_lifecycle(item.revision_kind),
                body=item.revision_body,
                attachment_metadata=add_external_channel_file_locators(
                    item.attachment_metadata or {},
                    binding_id=item.binding_id,
                ),
                reference_mappings=_external_reference_mappings(
                    item.reference_mappings
                ),
                provider_created_at=item.provider_created_at,
                provider_updated_at=item.provider_updated_at,
                original_url=item.original_url,
                truncated_context_message_count=item.truncation_message_count,
                truncated_context_size=item.truncation_size,
                correction_of_revision_id=item.correction_of_revision_id,
            )
            promoted.append(
                _PromotedInputBuffer(
                    buffer=buffer,
                    user_message=None,
                    event_kind=EventKind.EXTERNAL_CHANNEL_MESSAGE,
                    payload=_JSON_OBJECT_ADAPTER.validate_python(
                        payload.model_dump(mode="json")
                    ),
                    external_id=external_id,
                )
            )
        return _preparation_outcome(promoted, TurnEffect.ELIGIBLE)


@dataclasses.dataclass(frozen=True)
class _GoalActionInputBufferProcessor:
    """Prepare a closed Goal action."""

    service: InputBufferService

    async def process(
        self,
        context: InputBufferPreparationContext,
        buffer: InputBuffer,
    ) -> InputBufferPreparationOutcome:
        promoted = await self.service.promote_goal_action(
            context.session,
            session_id=context.session_id,
            buffer=buffer,
            prepared_inference_state=context.prepared_inference_state,
            prepared_files=context.prepared_files,
        )
        return _preparation_outcome(promoted, _turn_effect_for_promoted(promoted))


@dataclasses.dataclass(frozen=True)
class _SkillActionInputBufferProcessor:
    """Prepare a closed Skill action."""

    service: InputBufferService
    action: SkillAction

    async def process(
        self,
        context: InputBufferPreparationContext,
        buffer: InputBuffer,
    ) -> InputBufferPreparationOutcome:
        promoted = await self.service.promote_skill_action(
            context.session,
            session_id=context.session_id,
            buffer=buffer,
            action=self.action,
            active_run_id=context.active_run_id,
            prepared_inference_state=context.prepared_inference_state,
            prepared_files=context.prepared_files,
        )
        return _preparation_outcome(promoted, _turn_effect_for_promoted(promoted))


@dataclasses.dataclass(frozen=True)
class _CreateGitWorktreeActionInputBufferProcessor:
    """Preserve the worktree action boundary until durable claims replace it."""

    action: CreateGitWorktreeAction

    async def process(
        self,
        context: InputBufferPreparationContext,
        buffer: InputBuffer,
    ) -> InputBufferPreparationOutcome:
        del context
        return InputBufferPreparationOutcome(
            promoted=[],
            turn_effect=TurnEffect.NEUTRAL,
            worktree_action=WorktreeActionInput(
                buffer=buffer,
                action=self.action,
                execution=None,
            ),
        )


def _preparation_outcome(
    promoted: list[_PromotedInputBuffer],
    turn_effect: TurnEffect,
) -> InputBufferPreparationOutcome:
    """Build one immutable processor result."""
    return InputBufferPreparationOutcome(
        promoted=promoted,
        turn_effect=turn_effect,
        worktree_action=None,
    )


class _GoalActionError(Exception):
    """User-visible Goal action failure."""

    def __init__(self, message: str) -> None:
        """Create error."""
        super().__init__(message)
        self.message = message


def _turn_effect_for_promoted(
    promoted: Sequence[_PromotedInputBuffer],
) -> TurnEffect:
    """Derive the fold effect from one processor result."""
    if any(item.event_kind is EventKind.SYSTEM_ERROR for item in promoted):
        return TurnEffect.FAILED
    if promoted:
        return TurnEffect.ELIGIBLE
    return TurnEffect.NEUTRAL


def _external_resource_label(item: ExternalChannelInvocationProjectionItem) -> str:
    """Return the validated provider resource label for one projection item."""
    labels = item.resource_labels
    provider_resource_key = item.provider_resource_key
    if not isinstance(labels, dict) or not labels:
        raise ValueError("External invocation is missing resource labels.")
    channel_id = labels.get("channel_id") or labels.get("channel_name")
    if not isinstance(channel_id, str) or not channel_id:
        raise ValueError("External invocation is missing resource channel label.")
    thread_ts = labels.get("thread_ts")
    if thread_ts is not None and not isinstance(thread_ts, str):
        raise ValueError("External invocation has an invalid thread label.")
    if not isinstance(provider_resource_key, str) or not provider_resource_key:
        raise ValueError("External invocation is missing resource identity.")
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


def _external_message_lifecycle(
    revision_kind: ExternalChannelMessageRevisionKind,
) -> ExternalChannelMessageLifecycle:
    """Return the immutable lifecycle represented by one revision."""
    match revision_kind:
        case ExternalChannelMessageRevisionKind.ORIGINAL:
            return ExternalChannelMessageLifecycle.CURRENT
        case ExternalChannelMessageRevisionKind.EDIT:
            return ExternalChannelMessageLifecycle.EDITED
        case ExternalChannelMessageRevisionKind.DELETE:
            return ExternalChannelMessageLifecycle.DELETED
        case _:
            assert_never(revision_kind)


def _buffer_requires_inference(buffer: InputBuffer) -> bool:
    """Return whether preparing the buffer needs a resolved inference state."""
    match buffer.kind:
        case (
            InputBufferKind.USER_MESSAGE
            | InputBufferKind.GOAL_CONTINUATION
            | InputBufferKind.AGENT_MESSAGE
            | InputBufferKind.EXTERNAL_CHANNEL_INVOCATION
        ):
            return True
        case InputBufferKind.ACTION_MESSAGE:
            if buffer.action is None:
                raise ValueError("Action message input buffer requires action payload")
            action = _CHAT_ACTION_ADAPTER.validate_python(buffer.action)
            return isinstance(action, GoalAction | SkillAction)
        case _:
            assert_never(buffer.kind)


def _requested_inference_profile(
    buffer: InputBuffer,
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


def _agent_message_payload(buffer: InputBuffer) -> AgentMessagePayload:
    """Build agent_message payload from mailbox input buffer metadata."""
    payload: dict[str, object] = {
        "message_kind": buffer.metadata["message_kind"],
        "source_session_agent_id": buffer.metadata["source_session_agent_id"],
        "source_path": buffer.metadata["source_path"],
        "target_session_agent_id": buffer.metadata["target_session_agent_id"],
        "target_path": buffer.metadata["target_path"],
        "content": buffer.content,
    }
    for key in (
        "source_run_id",
        "source_run_index",
        "run_status",
        "source_terminal_result_event_id",
    ):
        value = buffer.metadata.get(key)
        if value is not None:
            payload[key] = value
    return _AGENT_MESSAGE_ADAPTER.validate_python(payload)


def _system_error_promoted_buffer(
    buffer: InputBuffer,
    content: str,
) -> _PromotedInputBuffer:
    """Create a promoted system_error for one handled preparation failure."""
    payload = SystemErrorPayload(
        content=content,
        severity="error",
        recoverable=True,
    )
    return _PromotedInputBuffer(
        buffer=buffer,
        user_message=None,
        event_kind=EventKind.SYSTEM_ERROR,
        payload=_JSON_OBJECT_ADAPTER.validate_python(
            payload.model_dump(mode="json", exclude_none=True)
        ),
        external_id=f"{buffer.id}:failure",
    )


def _skill_loaded_payload(
    item: SkillProjectionItem,
    *,
    user_message: str,
) -> SkillLoadedPayload:
    """Return skill_loaded event payload for a Skill action side effect."""
    return SkillLoadedPayload(
        name=item.name,
        skill_path=item.skill_path,
        body=item.body,
        user_message=user_message,
        content_hash=item.content_hash,
        source_label=item.source_label,
        relative_hint=item.relative_hint,
    )


def _goal_updated_payload(
    snapshot: GoalStateSnapshot,
    *,
    action: str,
) -> dict[str, JSONValue]:
    """Return goal_updated event payload for a Goal side effect."""
    return _JSON_OBJECT_ADAPTER.validate_python(
        {
            "sender_user_id": None,
            "content": "",
            "attachments": [],
            "metadata": {
                "source": "goal",
                "provider_slug": "goal",
                "goal_control_action": action,
                "goal_objective": snapshot.objective or "",
                "goal_status": snapshot.status or "",
                "goal_created_at": snapshot.created_at or "",
                "goal_updated_at": snapshot.updated_at or "",
            },
        }
    )
