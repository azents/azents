"""Session input buffer service."""

import dataclasses
import logging
from collections.abc import Sequence
from typing import Annotated, assert_never

from fastapi import Depends
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import EventKind, InputBufferKind
from azents.engine.events.types import Event, FileOutputPart
from azents.engine.events.user_messages import make_run_user_message
from azents.engine.io.user_input import RunUserMessage
from azents.engine.run.resolve import materialize_user_input_exchange_file_attachments
from azents.rdb.deps import get_session_manager
from azents.rdb.models.event import JSONValue
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.input_buffer.data import InputBuffer, InputBufferCreate
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.services.session_title import initial_title_from_event

logger = logging.getLogger(__name__)
_JSON_OBJECT_ADAPTER = TypeAdapter[dict[str, JSONValue]](dict[str, JSONValue])


@dataclasses.dataclass(frozen=True)
class InputBufferEnqueue:
    """Input buffer enqueue request."""

    session_id: str
    kind: InputBufferKind
    actor_user_id: str | None
    content: str
    idempotency_key: str | None
    metadata: dict[str, str]
    attachments: list[str]
    file_parts: list[FileOutputPart]


@dataclasses.dataclass(frozen=True)
class InputBufferEnqueueResult:
    """Input buffer enqueue result."""

    input_buffer: InputBuffer
    created: bool


@dataclasses.dataclass(frozen=True)
class PromotedInputBuffers:
    """InputBuffer flush result."""

    user_messages: list[RunUserMessage]
    events: list[Event]
    deleted_buffer_ids: list[str]
    claimed_count: int
    inserted_count: int
    deduped_count: int


@dataclasses.dataclass(frozen=True)
class _PromotedInputBuffer:
    """Result of converting InputBuffer to model input and durable event kind."""

    buffer: InputBuffer
    user_message: RunUserMessage
    event_kind: EventKind


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

    async def enqueue(
        self,
        session: AsyncSession,
        input: InputBufferEnqueue,
    ) -> InputBufferEnqueueResult:
        """Create one pending input buffer and mark the session running."""
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
                actor_user_id=input.actor_user_id,
                content=input.content,
                idempotency_key=input.idempotency_key,
                metadata=input.metadata,
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
        await self.agent_session_repository.mark_running_for_input_wakeup(
            session,
            input.session_id,
        )
        return InputBufferEnqueueResult(input_buffer=input_buffer, created=created)

    async def enqueue_many(
        self,
        session: AsyncSession,
        inputs: Sequence[InputBufferEnqueue],
    ) -> list[InputBufferEnqueueResult]:
        """Create pending input buffers and mark each affected session running."""
        results = [await self.enqueue(session, input) for input in inputs]
        return results

    async def enqueue_many_in_transaction(
        self,
        inputs: Sequence[InputBufferEnqueue],
    ) -> list[InputBufferEnqueueResult]:
        """Create pending inputs and running transitions in one transaction."""
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
        moved = await self.input_buffer_repository.move_by_session_id(
            session,
            from_session_id=from_session_id,
            to_session_id=to_session_id,
        )
        if moved:
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                to_session_id,
            )
        return moved

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
        limit: int | None = None,
    ) -> PromotedInputBuffers:
        """Flush pending buffers of session in claim, append, delete order."""
        del model
        async with self.session_manager() as session:
            claimed = await self.input_buffer_repository.claim_for_flush(
                session,
                session_id,
                limit=limit,
            )
            if not claimed:
                return PromotedInputBuffers(
                    user_messages=[],
                    events=[],
                    deleted_buffer_ids=[],
                    claimed_count=0,
                    inserted_count=0,
                    deduped_count=0,
                )

            promoted = [
                _PromotedInputBuffer(
                    buffer=buffer,
                    user_message=await self._buffer_to_user_message(buffer),
                    event_kind=_event_kind_for_input_buffer(buffer.kind),
                )
                for buffer in claimed
            ]
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
            inserted_external_ids = {
                event.external_id
                for event in event_inserted
                if event.external_id is not None
            }
            deduped = [
                item
                for item in promoted
                if item.user_message.external_id not in inserted_external_ids
            ]
            if deduped:
                missing: list[str] = []
                for item in deduped:
                    existing = (
                        await self.event_transcript_repository.get_by_external_id(
                            session,
                            session_id,
                            item.user_message.external_id,
                        )
                    )
                    if existing is None:
                        missing.append(item.user_message.external_id)
                if missing:
                    raise RuntimeError("Conflicted input buffer event was not found")

            buffer_ids = [buffer.id for buffer in claimed]
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
            user_messages=[item.user_message for item in promoted],
            events=event_inserted,
            deleted_buffer_ids=buffer_ids,
            claimed_count=len(claimed),
            inserted_count=len(event_inserted),
            deduped_count=len(deduped),
        )

    async def _buffer_to_user_message(self, buffer: InputBuffer) -> RunUserMessage:
        """Convert InputBuffer domain row to event run user message."""
        attachments = []
        file_parts = list(buffer.file_parts)
        if buffer.attachments:
            if buffer.actor_user_id is None:
                raise ValueError("Input buffer attachments require an actor user")
            async with self.session_manager() as session:
                agent_session = await self.agent_session_repository.get_by_id(
                    session,
                    buffer.session_id,
                )
            if agent_session is None:
                logger.warning(
                    "Input buffer session disappeared before attachment "
                    "materialization",
                    extra={"session_id": buffer.session_id, "buffer_id": buffer.id},
                )
            else:
                materialized = await materialize_user_input_exchange_file_attachments(
                    buffer.attachments,
                    agent_id=agent_session.agent_id,
                    session_id=buffer.session_id,
                    exchange_file_service=self.exchange_file_service,
                    model_file_service=(
                        None if file_parts else self.model_file_service
                    ),
                    user_id=buffer.actor_user_id,
                )
                attachments = materialized.attachments
                if not file_parts:
                    file_parts = materialized.file_parts

        return make_run_user_message(
            content=buffer.content,
            metadata=buffer.metadata,
            attachments=attachments,
            file_parts=file_parts,
            external_id=buffer.id,
            attachment_source="input_buffer",
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
                item.user_message.external_id,
            )
            if existing is not None:
                continue
            inserted.append(
                await self.event_transcript_repository.append(
                    session,
                    EventCreate(
                        session_id=session_id,
                        kind=item.event_kind,
                        payload=_JSON_OBJECT_ADAPTER.validate_python(
                            item.user_message.payload.model_dump(
                                mode="json",
                                exclude_none=True,
                            )
                        ),
                        external_id=item.user_message.external_id,
                    ),
                )
            )
        return inserted


def _event_kind_for_input_buffer(kind: InputBufferKind) -> EventKind:
    """Return durable event kind corresponding to InputBuffer kind."""
    match kind:
        case InputBufferKind.USER_MESSAGE | InputBufferKind.EDITED_USER_MESSAGE:
            return EventKind.USER_MESSAGE
        case InputBufferKind.BACKGROUND_COMPLETION:
            return EventKind.BACKGROUND_COMPLETION
        case InputBufferKind.GOAL_CONTINUATION:
            return EventKind.GOAL_CONTINUATION
        case _:
            assert_never(kind)
