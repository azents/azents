"""Message repository based on Event transcript."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import EventKind, MessageRole
from azents.engine.events.action_messages import ActionMessagePayload
from azents.engine.events.output_parts import iter_output_parts
from azents.engine.events.types import (
    AssistantMessagePayload,
    AttachmentOutputPart,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionMarkerPayload,
    CompactionSummaryPayload,
    Event,
    EventPayload,
    GoalBriefingPayload,
    InputTextPart,
    InterruptedPayload,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolResultPayload,
    ReasoningPayload,
    RunMarkerPayload,
    SkillLoadedPayload,
    SubagentEndPayload,
    SubagentStartPayload,
    SystemErrorPayload,
    SystemReminderPayload,
    ToolOutput,
    TurnMarkerPayload,
    UnknownAdapterOutputPayload,
    UserMessagePayload,
)
from azents.engine.events.types import (
    Attachment as EventAttachment,
)
from azents.engine.run.types import FunctionToolCall
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.transport.chat import ChatAttachmentSnapshot, chat_attachment_from_event

from .data import ChatMessage


def _validate_payload(row: RDBEvent) -> EventPayload:
    """Validate Event row payload with model by kind."""
    match row.kind:
        case EventKind.USER_MESSAGE:
            return UserMessagePayload.model_validate(row.payload)
        case EventKind.ASSISTANT_MESSAGE:
            return AssistantMessagePayload.model_validate(row.payload)
        case EventKind.REASONING:
            return ReasoningPayload.model_validate(row.payload)
        case EventKind.CLIENT_TOOL_CALL:
            return ClientToolCallPayload.model_validate(row.payload)
        case EventKind.CLIENT_TOOL_RESULT:
            return ClientToolResultPayload.model_validate(row.payload)
        case EventKind.PROVIDER_TOOL_CALL:
            return ProviderToolCallPayload.model_validate(row.payload)
        case EventKind.PROVIDER_TOOL_RESULT:
            return ProviderToolResultPayload.model_validate(row.payload)
        case EventKind.TURN_MARKER:
            return TurnMarkerPayload.model_validate(row.payload)
        case EventKind.RUN_MARKER:
            return RunMarkerPayload.model_validate(row.payload)
        case EventKind.INTERRUPTED:
            return InterruptedPayload.model_validate(row.payload)
        case EventKind.COMPACTION_MARKER:
            return CompactionMarkerPayload.model_validate(row.payload)
        case EventKind.COMPACTION_SUMMARY:
            return CompactionSummaryPayload.model_validate(row.payload)
        case EventKind.SUBAGENT_START:
            return SubagentStartPayload.model_validate(row.payload)
        case EventKind.SUBAGENT_END:
            return SubagentEndPayload.model_validate(row.payload)
        case EventKind.GOAL_CONTINUATION | EventKind.GOAL_UPDATED:
            return UserMessagePayload.model_validate(row.payload)
        case EventKind.ACTION_MESSAGE:
            return ActionMessagePayload.model_validate(row.payload)
        case EventKind.GOAL_BRIEFING:
            return GoalBriefingPayload.model_validate(row.payload)
        case EventKind.SKILL_LOADED:
            return SkillLoadedPayload.model_validate(row.payload)
        case EventKind.SYSTEM_REMINDER:
            return SystemReminderPayload.model_validate(row.payload)
        case EventKind.SYSTEM_ERROR:
            return SystemErrorPayload.model_validate(row.payload)
        case EventKind.UNKNOWN_ADAPTER_OUTPUT:
            return UnknownAdapterOutputPayload.model_validate(row.payload)
        case _:
            raise ValueError("Unsupported event kind")


def _to_chat_message(row: RDBEvent) -> ChatMessage | None:
    """Convert events row to REST chat message projection."""
    payload = _validate_payload(row)
    match payload:
        case UserMessagePayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.USER,
                content=_input_content_text(payload.content),
                tool_calls=None,
                tool_call_id=None,
                attachments=_attachments(payload.attachments),
                reasoning_summary=None,
                usage=None,
                metadata=payload.metadata or None,
                created_at=row.created_at,
            )
        case ActionMessagePayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.USER,
                content=payload.message,
                tool_calls=None,
                tool_call_id=None,
                attachments=[],
                reasoning_summary=None,
                usage=None,
                metadata={"action": payload.action.model_dump_json()},
                created_at=row.created_at,
            )
        case AssistantMessagePayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.ASSISTANT,
                content=_output_content_text(payload.content),
                tool_calls=None,
                tool_call_id=None,
                attachments=_attachments(payload.attachments),
                reasoning_summary=None,
                usage=None,
                metadata=None,
                created_at=row.created_at,
            )
        case ReasoningPayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.ASSISTANT,
                content=None,
                tool_calls=None,
                tool_call_id=None,
                attachments=[],
                reasoning_summary=payload.summary or payload.text,
                usage=None,
                metadata=None,
                created_at=row.created_at,
            )
        case ClientToolCallPayload() | ProviderToolCallPayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.ASSISTANT,
                content=None,
                tool_calls=[
                    FunctionToolCall(
                        id=payload.call_id,
                        name=payload.name,
                        arguments=payload.arguments or "",
                    )
                ],
                tool_call_id=None,
                attachments=[],
                reasoning_summary=None,
                usage=None,
                metadata=None,
                created_at=row.created_at,
            )
        case ClientToolResultPayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.TOOL,
                content=_tool_output_text(payload.output),
                tool_calls=None,
                tool_call_id=payload.call_id,
                attachments=_attachments(payload.attachments)
                + _output_part_attachments(payload.output),
                reasoning_summary=None,
                usage=None,
                metadata={"status": payload.status},
                created_at=row.created_at,
            )
        case ProviderToolResultPayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.ASSISTANT,
                content=_tool_output_text(payload.output),
                tool_calls=None,
                tool_call_id=payload.call_id,
                attachments=_attachments(payload.attachments)
                + _output_part_attachments(payload.output),
                reasoning_summary=None,
                usage=None,
                metadata={"status": payload.status},
                created_at=row.created_at,
            )
        case TurnMarkerPayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.TURN_COMPLETE,
                content=None,
                tool_calls=None,
                tool_call_id=None,
                attachments=[],
                reasoning_summary=None,
                usage=payload.usage.model_dump(mode="json", exclude_none=True),
                metadata={"run_id": payload.run_id},
                created_at=row.created_at,
            )
        case RunMarkerPayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.RUN_COMPLETE,
                content=payload.error,
                tool_calls=None,
                tool_call_id=None,
                attachments=[],
                reasoning_summary=None,
                usage=None,
                metadata={"run_id": payload.run_id, "status": payload.status},
                created_at=row.created_at,
            )
        case InterruptedPayload():
            return None
        case CompactionMarkerPayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.COMPACTION_STARTED,
                content=payload.reason or payload.error,
                tool_calls=None,
                tool_call_id=None,
                attachments=[],
                reasoning_summary=None,
                usage=None,
                metadata={
                    "compaction_id": payload.compaction_id,
                    "status": payload.status,
                    **({"reason": payload.reason} if payload.reason else {}),
                },
                created_at=row.created_at,
            )
        case CompactionSummaryPayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.COMPACTION,
                content=payload.content,
                tool_calls=None,
                tool_call_id=None,
                attachments=[],
                reasoning_summary=None,
                usage=None,
                metadata={
                    "compaction_id": payload.compaction_id,
                    **({"reason": payload.reason} if payload.reason else {}),
                },
                created_at=row.created_at,
            )
        case SubagentStartPayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.SUBAGENT_START,
                content=None,
                tool_calls=None,
                tool_call_id=None,
                attachments=[],
                reasoning_summary=None,
                usage=None,
                metadata={
                    "subagent_run_id": payload.subagent_run_id,
                    "subagent_id": payload.subagent_id,
                    "subagent_name": payload.subagent_name,
                    "subagent_session_id": payload.subagent_session_id,
                },
                created_at=row.created_at,
            )
        case GoalBriefingPayload() | SkillLoadedPayload():
            return None
        case SubagentEndPayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.SUBAGENT_END,
                content=payload.result or payload.error,
                tool_calls=None,
                tool_call_id=None,
                attachments=[],
                reasoning_summary=None,
                usage=None,
                metadata={
                    "subagent_run_id": payload.subagent_run_id,
                    "subagent_id": payload.subagent_id,
                    "subagent_session_id": payload.subagent_session_id,
                    "status": payload.status,
                },
                created_at=row.created_at,
            )
        case SystemReminderPayload():
            return None
        case SystemErrorPayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.ASSISTANT,
                content=payload.content,
                tool_calls=None,
                tool_call_id=None,
                attachments=[],
                reasoning_summary=None,
                usage=None,
                metadata=_system_error_metadata(payload),
                created_at=row.created_at,
            )
        case UnknownAdapterOutputPayload():
            return None


def event_to_chat_message(row: RDBEvent) -> ChatMessage | None:
    """Convert Event row to REST chat message projection."""
    return _to_chat_message(row)


def _to_event(row: RDBEvent) -> Event:
    """Convert RDB row to event domain model."""
    return Event(
        id=row.id,
        session_id=row.session_id,
        kind=row.kind,
        payload=_validate_payload(row),
        model_order=row.model_order,
        external_id=row.external_id,
        adapter=row.adapter,
        provider=row.provider,
        model=row.model,
        native_format=row.native_format,
        schema_version=row.schema_version,
        created_at=row.created_at,
    )


def _input_content_text(content: object) -> str:
    """Convert Event input content to display text."""
    if isinstance(content, str):
        return content
    lines: list[str] = []
    if isinstance(content, list):
        for part in content:
            if isinstance(part, InputTextPart):
                lines.append(part.text)
    return "\n".join(lines)


def _output_content_text(content: object) -> str:
    """Convert Event output content to display text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _tool_output_text(content) or ""
    return ""


def _tool_output_text(output: ToolOutput) -> str | None:
    """Merge text parts of Tool output."""
    lines: list[str] = []
    for part in iter_output_parts(output):
        if isinstance(part, OutputTextPart):
            lines.append(part.text)
    if lines:
        return "\n".join(lines)
    return None


def _attachments(items: list[EventAttachment]) -> list[ChatAttachmentSnapshot]:
    """Convert Event attachment to REST attachment snapshot."""
    return [_attachment(item) for item in items]


def _attachment(item: EventAttachment) -> ChatAttachmentSnapshot:
    """Convert single Event attachment to REST attachment."""
    return chat_attachment_from_event(item)


def _output_part_attachments(output: ToolOutput) -> list[ChatAttachmentSnapshot]:
    """Convert output attachment part to REST attachment projection."""
    attachments: list[ChatAttachmentSnapshot] = []
    for part in iter_output_parts(output):
        match part:
            case AttachmentOutputPart() as attachment_part:
                attachments.append(
                    ChatAttachmentSnapshot(
                        attachment_id=attachment_part.attachment_id,
                        uri=attachment_part.uri,
                        media_type=attachment_part.media_type,
                        size=attachment_part.size,
                        name=attachment_part.name,
                        text_preview=attachment_part.preview_summary,
                        preview_thumbnail_uri=attachment_part.preview_thumbnail_uri,
                        availability=attachment_part.availability,
                        preview_title=attachment_part.preview_title,
                        preview_thumbnail_media_type=(
                            attachment_part.preview_thumbnail_media_type
                        ),
                        preview_thumbnail_width=attachment_part.preview_thumbnail_width,
                        preview_thumbnail_height=(
                            attachment_part.preview_thumbnail_height
                        ),
                        preview_generated_at=attachment_part.preview_generated_at,
                    )
                )
            case OutputTextPart():
                pass
            case _:
                pass
    return attachments


def _system_error_metadata(payload: SystemErrorPayload) -> dict[str, str] | None:
    """Build System error payload metadata."""
    metadata: dict[str, str] = {}
    if payload.severity is not None:
        metadata["severity"] = payload.severity
    if payload.recoverable is not None:
        metadata["recoverable"] = str(payload.recoverable)
    if payload.reset_suggested is not None:
        metadata["reset_suggested"] = str(payload.reset_suggested)
    if metadata:
        return metadata
    return None


class MessageRepository:
    """Message fetch repository. Operates on events."""

    async def get_by_id(
        self, session: AsyncSession, message_id: str
    ) -> RDBEvent | None:
        """Fetch message by ID."""
        return await session.get(RDBEvent, message_id)

    async def list_by_session_id_paginated(
        self,
        session: AsyncSession,
        session_id: str,
        limit: int = 50,
        before: str | None = None,
    ) -> tuple[list[ChatMessage], bool]:
        """Fetch session messages paginated in reverse order."""
        query = sa.select(RDBEvent).where(
            RDBEvent.session_id == session_id,
            RDBEvent.reverted.is_(False),
        )

        if before is not None:
            query = query.where(RDBEvent.id < before)

        query = query.order_by(RDBEvent.id.desc()).limit(limit + 1)

        result = await session.execute(query)
        rows = list(result.scalars())

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        rows.reverse()
        messages: list[ChatMessage] = []
        for row in rows:
            message = event_to_chat_message(row)
            if message is not None and not self._is_empty(message):
                messages.append(message)
        return messages, has_more

    async def list_events_by_session_id_paginated(
        self,
        session: AsyncSession,
        session_id: str,
        limit: int = 50,
        before: str | None = None,
        after: str | None = None,
    ) -> tuple[list[Event], bool, bool]:
        """Fetch session events with bidirectional cursor."""
        query = sa.select(RDBEvent).where(
            RDBEvent.session_id == session_id,
            RDBEvent.reverted.is_(False),
        )

        if before is not None:
            query = query.where(RDBEvent.id < before)
            query = query.order_by(RDBEvent.id.desc()).limit(limit + 1)
        elif after is not None:
            query = query.where(RDBEvent.id > after)
            query = query.order_by(RDBEvent.id.asc()).limit(limit + 1)
        else:
            query = query.order_by(RDBEvent.id.desc()).limit(limit + 1)

        result = await session.execute(query)
        rows = list(result.scalars())

        has_extra = len(rows) > limit
        if has_extra:
            rows = rows[:limit]

        if after is None:
            rows.reverse()

        has_more = has_extra if after is None else False
        has_newer = has_extra if after is not None else False
        return [_to_event(row) for row in rows], has_more, has_newer

    async def mark_reverted_from_model_order(
        self,
        session: AsyncSession,
        session_id: str,
        model_order: int,
    ) -> int:
        """Hide events at or above specific model_order from UI/model input."""
        count_result = await session.execute(
            sa.select(sa.func.count())
            .select_from(RDBEvent)
            .where(
                RDBEvent.session_id == session_id,
                RDBEvent.model_order >= model_order,
                RDBEvent.reverted.is_(False),
            )
        )
        delete_count = count_result.scalar_one()
        result = await session.execute(
            sa.update(RDBEvent)
            .where(
                RDBEvent.session_id == session_id,
                RDBEvent.model_order >= model_order,
                RDBEvent.reverted.is_(False),
            )
            .values(reverted=True)
        )
        del result
        await self._refresh_session_last_user_input_at(session, session_id)
        return delete_count

    async def _refresh_session_last_user_input_at(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> None:
        """Refresh AgentSession latest user input timestamp after event revert."""
        latest_user_input_at = (
            sa.select(sa.func.max(RDBEvent.created_at))
            .where(
                RDBEvent.session_id == session_id,
                RDBEvent.kind == EventKind.USER_MESSAGE,
                RDBEvent.reverted.is_(False),
            )
            .scalar_subquery()
        )
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(
                last_user_input_at=sa.func.coalesce(
                    latest_user_input_at,
                    RDBAgentSession.created_at,
                )
            )
        )
        await session.flush()

    async def is_at_or_before_model_input_head(
        self,
        session: AsyncSession,
        session_id: str,
        model_order: int,
    ) -> bool:
        """Check whether target model_order is at or below current model input head."""
        result = await session.execute(
            sa.select(
                RDBAgentSession.model_input_head_event_id,
                RDBEvent.model_order,
            )
            .select_from(RDBAgentSession)
            .outerjoin(
                RDBEvent, RDBEvent.id == RDBAgentSession.model_input_head_event_id
            )
            .where(RDBAgentSession.id == session_id)
        )
        row = result.one_or_none()
        if row is None:
            return False
        head_event_id, head_model_order = row
        if head_event_id is None:
            return False
        if head_model_order is None:
            return True
        return model_order <= head_model_order

    def _is_empty(self, msg: ChatMessage) -> bool:
        """Return whether message is empty with no displayable content."""
        if msg.role in (
            MessageRole.TURN_COMPLETE,
            MessageRole.RUN_COMPLETE,
            MessageRole.SUBAGENT_START,
            MessageRole.SUBAGENT_END,
        ):
            return False
        return (
            msg.role == MessageRole.ASSISTANT
            and not msg.content
            and msg.tool_calls is None
            and msg.reasoning_summary is None
            and len(msg.attachments) == 0
        )
