"""Session input buffer service."""

import asyncio
import dataclasses
import datetime
import enum
import logging
from collections.abc import Sequence
from typing import Annotated, Protocol, assert_never

from fastapi import Depends
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ActionExecutionStatus, EventKind, InputBufferKind
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
    FileOutputPart,
    SkillLoadedPayload,
    SystemErrorPayload,
)
from azents.engine.events.user_messages import make_run_user_message
from azents.engine.io.user_input import RunUserMessage
from azents.engine.run.resolve import (
    MaterializedUserInputAttachments,
    materialize_user_input_exchange_file_attachments,
)
from azents.engine.tools.goal import GoalState, GoalStateSnapshot, GoalStateStore
from azents.engine.tools.skill import (
    SkillProjectionItem,
    SkillStateStore,
    resolve_active_skill,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.models.event import JSONValue
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.action_execution.data import ActionExecution, ActionExecutionCreate
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.input_buffer.data import InputBuffer, InputBufferCreate
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.services.session_title import initial_title_from_event

logger = logging.getLogger(__name__)
_JSON_OBJECT_ADAPTER = TypeAdapter[dict[str, JSONValue]](dict[str, JSONValue])
_CHAT_ACTION_ADAPTER = TypeAdapter(ChatAction)
_AGENT_MESSAGE_ADAPTER = TypeAdapter(AgentMessagePayload)


@dataclasses.dataclass(frozen=True)
class InputBufferEnqueue:
    """Input buffer enqueue request."""

    session_id: str
    kind: InputBufferKind
    requested_model_target_label: str | None
    requested_reasoning_effort: ModelReasoningEffort | None
    actor_user_id: str | None
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
class InputBufferPreparationContext:
    """Shared context passed to one closed input-buffer processor."""

    session: AsyncSession
    session_id: str
    required_inference_profile: RequestedInferenceProfile | None
    prepared_inference_state: SessionInferenceState | None
    prepared_attachments: MaterializedUserInputAttachments | None


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
                requested_model_target_label=input.requested_model_target_label,
                requested_reasoning_effort=input.requested_reasoning_effort,
                actor_user_id=input.actor_user_id,
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

    async def prepare_pending_input_attachments(
        self,
        *,
        session_id: str,
        expected_buffer_id: str | None,
    ) -> MaterializedUserInputAttachments | None:
        """Resolve the FIFO head attachments without holding durable row locks."""
        async with self.session_manager() as session:
            pending = await self.input_buffer_repository.list_for_flush(
                session,
                session_id,
                limit=1,
            )
            buffer = pending[0] if pending else None
            actual_buffer_id = buffer.id if buffer is not None else None
            if actual_buffer_id != expected_buffer_id:
                raise InputBufferPreparationStaleError(
                    "Input buffer FIFO head changed during attachment preparation"
                )
            if buffer is None or not buffer.attachments:
                return None
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )

        if agent_session is None:
            raise ValueError("AgentSession not found")
        if buffer.actor_user_id is None:
            raise ValueError("Input buffer attachments require an actor user")
        materialized = await materialize_user_input_exchange_file_attachments(
            buffer.attachments,
            agent_id=agent_session.agent_id,
            session_id=session_id,
            exchange_file_service=self.exchange_file_service,
            model_file_service=(None if buffer.file_parts else self.model_file_service),
            user_id=buffer.actor_user_id,
        )
        if not buffer.file_parts:
            return materialized
        return MaterializedUserInputAttachments(
            attachments=materialized.attachments,
            file_parts=list(buffer.file_parts),
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

    async def flush_session_input_buffers(
        self,
        *,
        session_id: str,
        model: str | None,
        required_inference_profile: RequestedInferenceProfile | None,
        expected_buffer_id: str | None,
        prepared_inference_state: SessionInferenceState | None,
        prepared_attachments: MaterializedUserInputAttachments | None,
        profile_resolution_failure: str | None,
        active_run_id: str | None,
        limit: int | None = None,
        include_action_messages: bool = True,
    ) -> PromotedInputBuffers:
        """Commit one prepared FIFO head in a short durable transaction."""
        started_at = asyncio.get_running_loop().time()
        promoted = await self._flush_session_input_buffers_transaction(
            session_id=session_id,
            model=model,
            required_inference_profile=required_inference_profile,
            expected_buffer_id=expected_buffer_id,
            prepared_inference_state=prepared_inference_state,
            prepared_attachments=prepared_attachments,
            profile_resolution_failure=profile_resolution_failure,
            active_run_id=active_run_id,
            limit=limit,
            include_action_messages=include_action_messages,
        )
        logger.info(
            "Input buffer durable flush transaction committed",
            extra={
                "session_id": session_id,
                "input_buffer_id": expected_buffer_id,
                "duration_seconds": round(
                    asyncio.get_running_loop().time() - started_at,
                    3,
                ),
            },
        )
        return promoted

    async def _flush_session_input_buffers_transaction(
        self,
        *,
        session_id: str,
        model: str | None,
        required_inference_profile: RequestedInferenceProfile | None,
        expected_buffer_id: str | None,
        prepared_inference_state: SessionInferenceState | None,
        prepared_attachments: MaterializedUserInputAttachments | None,
        profile_resolution_failure: str | None,
        active_run_id: str | None,
        limit: int | None,
        include_action_messages: bool,
    ) -> PromotedInputBuffers:
        """Lock, append, and delete one prepared FIFO head atomically."""
        del model
        del limit
        async with self.session_manager() as session:
            lock_started_at = asyncio.get_running_loop().time()
            agent_session = await self.agent_session_repository.lock_by_id(
                session,
                session_id,
            )
            logger.info(
                "Input buffer durable flush acquired AgentSession row lock",
                extra={
                    "session_id": session_id,
                    "input_buffer_id": expected_buffer_id,
                    "wait_seconds": round(
                        asyncio.get_running_loop().time() - lock_started_at,
                        3,
                    ),
                },
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
                prepared_attachments=prepared_attachments,
                profile_resolution_failure=profile_resolution_failure,
                include_action_messages=include_action_messages,
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
            claimed_count=len(buffer_ids),
            inserted_count=len(event_inserted),
            deduped_count=len(deduped),
        )

    async def _promote_claimed_buffers(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        claimed: list[InputBuffer],
        required_inference_profile: RequestedInferenceProfile | None,
        prepared_inference_state: SessionInferenceState | None,
        prepared_attachments: MaterializedUserInputAttachments | None,
        profile_resolution_failure: str | None,
        include_action_messages: bool,
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
            required_inference_profile=required_inference_profile,
            prepared_inference_state=prepared_inference_state,
            prepared_attachments=prepared_attachments,
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
            prepared_attachments=None,
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
        prepared_inference_state: SessionInferenceState | None,
    ) -> list[_PromotedInputBuffer]:
        """Create durable reminder for one Skill action_message buffer."""
        agent_session = await self.agent_session_repository.get_by_id(
            session,
            session_id,
        )
        if agent_session is None:
            return [_system_error_promoted_buffer(buffer, "Session not found.")]
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
                prepared_attachments=None,
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

    def buffer_to_user_message(
        self,
        buffer: InputBuffer,
        *,
        external_id: str | None = None,
        fallback_profile: RequestedInferenceProfile | None,
        prepared_inference_state: SessionInferenceState | None,
        prepared_attachments: MaterializedUserInputAttachments | None,
    ) -> RunUserMessage:
        """Convert a prepared InputBuffer row to an event run user message."""
        if buffer.attachments and prepared_attachments is None:
            raise RuntimeError(
                "Input buffer attachments must be prepared before durable flush"
            )
        attachments = (
            prepared_attachments.attachments if prepared_attachments is not None else []
        )
        file_parts = (
            prepared_attachments.file_parts
            if prepared_attachments is not None
            else list(buffer.file_parts)
        )

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
            content=buffer.content,
            metadata=buffer.metadata,
            attachments=attachments,
            file_parts=file_parts,
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
            prepared_attachments=context.prepared_attachments,
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
            prepared_attachments=context.prepared_attachments,
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
            prepared_attachments=context.prepared_attachments,
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
            prepared_inference_state=context.prepared_inference_state,
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


def _buffer_requires_inference(buffer: InputBuffer) -> bool:
    """Return whether preparing the buffer needs a resolved inference state."""
    match buffer.kind:
        case (
            InputBufferKind.USER_MESSAGE
            | InputBufferKind.GOAL_CONTINUATION
            | InputBufferKind.AGENT_MESSAGE
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
    return _AGENT_MESSAGE_ADAPTER.validate_python(
        {
            "message_kind": buffer.metadata["message_kind"],
            "source_session_agent_id": buffer.metadata["source_session_agent_id"],
            "source_path": buffer.metadata["source_path"],
            "target_session_agent_id": buffer.metadata["target_session_agent_id"],
            "target_path": buffer.metadata["target_path"],
            "content": buffer.content,
        }
    )


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
