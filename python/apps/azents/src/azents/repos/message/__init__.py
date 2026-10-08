"""Message repository based on Event transcript."""

import dataclasses
import json
import time
from typing import NamedTuple

import sqlalchemy as sa

from azents.core.enums import EventKind, MessageRole
from azents.core.type_guards import is_object_list
from azents.engine.events.action_messages import ActionMessagePayload
from azents.engine.events.conversational_tool_projection import (
    CONVERSATIONAL_TOOL_PROJECTIONS,
)
from azents.engine.events.historical_memory_projection import (
    HistoricalMemoryEvidenceTier,
    project_historical_memory_event,
)
from azents.engine.events.output_parts import iter_output_parts
from azents.engine.events.provider_tool_rendering import render_provider_tool_semantic
from azents.engine.events.types import (
    ActionExecutionResultPayload,
    AgentMessagePayload,
    AssistantMessagePayload,
    AttachmentOutputPart,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionMarkerPayload,
    CompactionSummaryPayload,
    Event,
    EventPayload,
    ExternalChannelMessagePayload,
    GoalBriefingPayload,
    InputTextPart,
    InterruptedPayload,
    OutputTextPart,
    ProviderToolCallPayload,
    ReasoningPayload,
    RunMarkerPayload,
    ScheduledTaskContinuationPayload,
    ScheduledTaskResultPayload,
    ScheduledTaskTriggerPayload,
    SkillLoadedPayload,
    SystemErrorPayload,
    SystemReminderPayload,
    ToolOutput,
    TurnMarkerPayload,
    UnknownAdapterOutputPayload,
    UserMessagePayload,
    upgrade_persisted_client_tool_payload,
)
from azents.engine.events.types import (
    Attachment as EventAttachment,
)
from azents.engine.run.types import FunctionToolCall
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.event import RDBEvent
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.transport.chat import ChatAttachmentSnapshot, chat_attachment_from_event

from .data import ChatMessage

_INVISIBLE_RETRY_ELIGIBILITY_ROLES = {
    MessageRole.TURN_COMPLETE,
    MessageRole.RUN_COMPLETE,
    MessageRole.COMPACTION_STARTED,
    MessageRole.COMPACTION,
}
_HISTORICAL_MEMORY_SCAN_PAGE_SIZE = 50
_HISTORICAL_MEMORY_SCAN_ROW_MULTIPLIER = 8
_HISTORICAL_MEMORY_SCAN_MAX_ROWS = 1_600
_HISTORICAL_MEMORY_SCAN_MAX_PAGES = 32
_HISTORICAL_MEMORY_SCAN_MAX_BYTES = 8 * 1024 * 1024
_HISTORICAL_MEMORY_SCAN_MAX_SECONDS = 2.0


@dataclasses.dataclass
class _HistoricalMemoryScanBudget:
    """Hard per-lane database scan bounds before semantic projection."""

    max_rows: int
    deadline: float
    visited_rows: int = 0
    visited_pages: int = 0
    visited_bytes: int = 0

    @classmethod
    def for_limit(cls, limit: int) -> "_HistoricalMemoryScanBudget":
        return cls(
            max_rows=min(
                max(
                    _HISTORICAL_MEMORY_SCAN_PAGE_SIZE,
                    limit * _HISTORICAL_MEMORY_SCAN_ROW_MULTIPLIER,
                ),
                _HISTORICAL_MEMORY_SCAN_MAX_ROWS,
            ),
            deadline=time.monotonic() + _HISTORICAL_MEMORY_SCAN_MAX_SECONDS,
        )

    @property
    def exhausted(self) -> bool:
        return (
            self.visited_rows >= self.max_rows
            or self.visited_pages >= _HISTORICAL_MEMORY_SCAN_MAX_PAGES
            or self.visited_bytes >= _HISTORICAL_MEMORY_SCAN_MAX_BYTES
            or time.monotonic() >= self.deadline
        )

    @property
    def next_page_limit(self) -> int:
        return min(
            _HISTORICAL_MEMORY_SCAN_PAGE_SIZE,
            self.max_rows - self.visited_rows,
        )

    def admit_page(self, rows: list[RDBEvent]) -> list[RDBEvent]:
        """Count one query page and retain rows inside row/byte/time bounds."""
        self.visited_pages += 1
        admitted: list[RDBEvent] = []
        for row in rows:
            if (
                self.visited_rows >= self.max_rows
                or self.visited_bytes >= _HISTORICAL_MEMORY_SCAN_MAX_BYTES
                or time.monotonic() >= self.deadline
            ):
                break
            payload_bytes = len(
                json.dumps(
                    row.payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            )
            if self.visited_bytes + payload_bytes > _HISTORICAL_MEMORY_SCAN_MAX_BYTES:
                self.visited_bytes = _HISTORICAL_MEMORY_SCAN_MAX_BYTES
                break
            self.visited_rows += 1
            self.visited_bytes += payload_bytes
            admitted.append(row)
        return admitted


class ChatMessagePage(NamedTuple):
    """Paginated ChatMessage projection."""

    items: list[ChatMessage]
    has_more: bool


class EventPage(NamedTuple):
    """Bidirectional paginated Event projection."""

    items: list[Event]
    has_more: bool
    has_newer: bool


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
            return ClientToolCallPayload.model_validate(
                upgrade_persisted_client_tool_payload(row.kind, row.payload)
            )
        case EventKind.CLIENT_TOOL_RESULT:
            return ClientToolResultPayload.model_validate(
                upgrade_persisted_client_tool_payload(row.kind, row.payload)
            )
        case EventKind.PROVIDER_TOOL_CALL:
            return ProviderToolCallPayload.model_validate(row.payload)
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
        case (
            EventKind.GOAL_CONTINUATION
            | EventKind.EXTERNAL_CHANNEL_CONTINUATION
            | EventKind.GOAL_UPDATED
        ):
            return UserMessagePayload.model_validate(row.payload)
        case EventKind.ACTION_MESSAGE:
            return ActionMessagePayload.model_validate(row.payload)
        case EventKind.AGENT_MESSAGE:
            return AgentMessagePayload.model_validate(row.payload)
        case EventKind.EXTERNAL_CHANNEL_MESSAGE:
            return ExternalChannelMessagePayload.model_validate(row.payload)
        case EventKind.ACTION_EXECUTION_RESULT:
            return ActionExecutionResultPayload.model_validate(row.payload)
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
        case EventKind.SCHEDULED_TASK_TRIGGER:
            return ScheduledTaskTriggerPayload.model_validate(row.payload)
        case EventKind.SCHEDULED_TASK_CONTINUATION:
            return ScheduledTaskContinuationPayload.model_validate(row.payload)
        case EventKind.SCHEDULED_TASK_RESULT:
            return ScheduledTaskResultPayload.model_validate(row.payload)
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
        case AgentMessagePayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.USER,
                content=payload.content,
                tool_calls=None,
                tool_call_id=None,
                attachments=[],
                reasoning_summary=None,
                usage=None,
                metadata={
                    "source": "agent_mailbox",
                    "message_kind": payload.message_kind,
                    "source_path": payload.source_path,
                    "target_path": payload.target_path,
                },
                created_at=row.created_at,
            )
        case ExternalChannelMessagePayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.USER,
                content=payload.body,
                tool_calls=None,
                tool_call_id=None,
                attachments=[],
                reasoning_summary=None,
                usage=None,
                metadata={
                    "source": "external_channel",
                    "provider": payload.provider.value,
                    "provider_tenant_id": payload.provider_tenant_id,
                    "resource_id": payload.resource_id,
                    "resource_label": payload.resource_label,
                    "resource_type": payload.resource_type.value,
                    "binding_id": payload.binding_id,
                    "invocation_batch_id": payload.invocation_batch_id,
                    "external_message_id": payload.external_message_id,
                    "projection_root_id": payload.projection_root_id,
                    "provider_message_key": payload.provider_message_key,
                    "provider_position": payload.provider_position,
                    "author_type": payload.author_type.value,
                    "prompt_role": payload.prompt_role,
                    "event_render_key": f"event:{row.external_id or row.id}",
                    **(
                        {"principal_id": payload.principal_id}
                        if payload.principal_id is not None
                        else {}
                    ),
                    **(
                        {"provider_user_id": payload.provider_user_id}
                        if payload.provider_user_id is not None
                        else {}
                    ),
                    **(
                        {
                            "provider_created_at": (
                                payload.provider_created_at.isoformat()
                            )
                        }
                        if payload.provider_created_at is not None
                        else {}
                    ),
                    **(
                        {
                            "provider_updated_at": (
                                payload.provider_updated_at.isoformat()
                            )
                        }
                        if payload.provider_updated_at is not None
                        else {}
                    ),
                    **(
                        {"sender_display_name": payload.sender_display_name}
                        if payload.sender_display_name is not None
                        else {}
                    ),
                    **(
                        {
                            "reference_mappings": json.dumps(
                                payload.reference_mappings,
                                ensure_ascii=False,
                                sort_keys=True,
                            )
                        }
                        if payload.reference_mappings
                        else {}
                    ),
                    **(
                        {"original_url": payload.original_url}
                        if payload.original_url is not None
                        else {}
                    ),
                },
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
        case ClientToolCallPayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.ASSISTANT,
                content=None,
                tool_calls=[
                    FunctionToolCall(
                        id=payload.call_id,
                        name=payload.name,
                        arguments=payload.arguments,
                        wire_dialect=payload.wire_dialect,
                    )
                ],
                tool_call_id=None,
                attachments=[],
                reasoning_summary=None,
                usage=None,
                metadata=None,
                created_at=row.created_at,
            )
        case ProviderToolCallPayload():
            return ChatMessage(
                id=row.id,
                session_id=row.session_id,
                role=MessageRole.ASSISTANT,
                content=render_provider_tool_semantic(payload),
                tool_calls=[
                    FunctionToolCall(
                        id=payload.call_id,
                        name=payload.name,
                        arguments=payload.semantic.input or "",
                        wire_dialect="json_function",
                    )
                ],
                tool_call_id=None,
                attachments=_output_part_attachments(payload.semantic.output),
                reasoning_summary=None,
                usage=None,
                metadata={"status": payload.status or "unknown"},
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
                attachments=_output_part_attachments(payload.output),
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
        case (
            ActionExecutionResultPayload()
            | GoalBriefingPayload()
            | SkillLoadedPayload()
        ):
            return None

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
    if is_object_list(content):
        return _tool_output_text(content) or ""
    return ""


def _tool_output_text(output: ToolOutput | list[object]) -> str | None:
    """Merge text parts of Tool output."""
    if isinstance(output, str):
        return output
    lines: list[str] = []
    for part in output:
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

    async def get_by_id(self, session: ReadSession, message_id: str) -> RDBEvent | None:
        """Fetch message by ID."""
        return await session.read_session.get(RDBEvent, message_id)

    async def get_event_by_id(
        self,
        session: ReadSession,
        event_id: str,
    ) -> Event | None:
        """Fetch and decode one transcript Event by ID."""
        row = await session.read_session.get(RDBEvent, event_id)
        return None if row is None else _to_event(row)

    async def has_non_reverted_kind(
        self,
        session: ReadSession,
        *,
        session_id: str,
        kind: EventKind,
    ) -> bool:
        """Return whether one Session contains a non-reverted event kind."""
        return bool(
            await session.read_session.scalar(
                sa.select(
                    sa.exists().where(
                        RDBEvent.session_id == session_id,
                        RDBEvent.kind == kind,
                        RDBEvent.reverted.is_(False),
                    )
                )
            )
        )

    async def list_historical_memory_events_by_tier(
        self,
        session: WriteSession,
        *,
        session_id: str,
        tail_event_id: str,
        per_tier_limit: int,
    ) -> list[Event]:
        """Load newest projector-eligible source evidence per semantic lane."""
        if per_tier_limit < 1:
            raise ValueError("Historical Memory tier limit must be positive.")
        human_clause = sa.or_(
            RDBEvent.kind.in_(
                (
                    EventKind.USER_MESSAGE,
                    EventKind.ACTION_MESSAGE,
                )
            ),
            sa.and_(
                RDBEvent.kind == EventKind.EXTERNAL_CHANNEL_MESSAGE,
                RDBEvent.payload["prompt_role"].astext == "invocation",
            ),
        )
        semantic_lanes = (
            (
                human_clause,
                HistoricalMemoryEvidenceTier.HUMAN,
            ),
            (
                RDBEvent.kind == EventKind.ASSISTANT_MESSAGE,
                HistoricalMemoryEvidenceTier.ASSISTANT,
            ),
            (
                RDBEvent.kind == EventKind.AGENT_MESSAGE,
                HistoricalMemoryEvidenceTier.OTHER_AGENT,
            ),
            (
                RDBEvent.kind == EventKind.SYSTEM_ERROR,
                HistoricalMemoryEvidenceTier.CONTEXT,
            ),
        )
        rows_by_id: dict[str, RDBEvent] = {}
        for clause, expected_tier in semantic_lanes:
            rows = await self._list_historical_memory_eligible_lane(
                session,
                session_id=session_id,
                tail_event_id=tail_event_id,
                clause=clause,
                expected_tier=expected_tier,
                limit=per_tier_limit,
            )
            for row in rows:
                rows_by_id[row.id] = row
        conversational_tool_names = tuple(CONVERSATIONAL_TOOL_PROJECTIONS)
        if conversational_tool_names:
            registered_rows = await self._list_historical_memory_registered_tools(
                session,
                session_id=session_id,
                tail_event_id=tail_event_id,
                tool_names=conversational_tool_names,
                limit=per_tier_limit,
            )
            for row in registered_rows:
                rows_by_id[row.id] = row
        generic_tool_clause = self._historical_memory_generic_tool_clause(
            conversational_tool_names
        )
        generic_tool_rows = await self._list_historical_memory_eligible_lane(
            session,
            session_id=session_id,
            tail_event_id=tail_event_id,
            clause=generic_tool_clause,
            expected_tier=HistoricalMemoryEvidenceTier.TOOL,
            limit=per_tier_limit,
        )
        for row in generic_tool_rows:
            rows_by_id[row.id] = row
        return [_to_event(rows_by_id[event_id]) for event_id in sorted(rows_by_id)]

    async def _list_historical_memory_eligible_lane(
        self,
        session: ReadSession,
        *,
        session_id: str,
        tail_event_id: str,
        clause: sa.ColumnElement[bool],
        expected_tier: HistoricalMemoryEvidenceTier,
        limit: int,
    ) -> list[RDBEvent]:
        """Page one lane until its projector-eligible bound is filled."""
        selected: list[RDBEvent] = []
        before_id: str | None = None
        budget = _HistoricalMemoryScanBudget.for_limit(limit)
        while len(selected) < limit and not budget.exhausted:
            statement = sa.select(RDBEvent).where(
                RDBEvent.session_id == session_id,
                RDBEvent.id <= tail_event_id,
                RDBEvent.reverted.is_(False),
                clause,
            )
            if before_id is not None:
                statement = statement.where(RDBEvent.id < before_id)
            page_limit = budget.next_page_limit
            rows = list(
                (
                    await session.read_session.execute(
                        statement.order_by(RDBEvent.id.desc()).limit(page_limit)
                    )
                ).scalars()
            )
            if not rows:
                break
            before_id = rows[-1].id
            admitted_rows = budget.admit_page(rows)
            for row in admitted_rows:
                evidence = project_historical_memory_event(_to_event(row))
                if evidence is None or evidence.tier is not expected_tier:
                    continue
                selected.append(row)
                if len(selected) == limit:
                    break
            if len(rows) < page_limit or not admitted_rows:
                break
        return selected

    async def _list_historical_memory_registered_tools(
        self,
        session: WriteSession,
        *,
        session_id: str,
        tail_event_id: str,
        tool_names: tuple[str, ...],
        limit: int,
    ) -> list[RDBEvent]:
        """Collect valid conversation calls and malformed-call Tool fallback."""
        valid_rows: list[RDBEvent] = []
        fallback_rows: list[RDBEvent] = []
        linked_results: dict[str, RDBEvent] = {}
        result_payloads: dict[str, ClientToolResultPayload] = {}
        valid_call_ids: set[str] = set()
        before_id: str | None = None
        budget = _HistoricalMemoryScanBudget.for_limit(limit)
        result_budget = _HistoricalMemoryScanBudget.for_limit(limit)
        result_budget.deadline = budget.deadline
        while (
            len(valid_rows) < limit or len(fallback_rows) < limit
        ) and not budget.exhausted:
            statement = sa.select(RDBEvent).where(
                RDBEvent.session_id == session_id,
                RDBEvent.id <= tail_event_id,
                RDBEvent.reverted.is_(False),
                RDBEvent.kind == EventKind.CLIENT_TOOL_CALL,
                RDBEvent.payload["name"].astext.in_(tool_names),
            )
            if before_id is not None:
                statement = statement.where(RDBEvent.id < before_id)
            page_limit = budget.next_page_limit
            call_rows = list(
                (
                    await session.write_session.execute(
                        statement.order_by(RDBEvent.id.desc()).limit(page_limit)
                    )
                ).scalars()
            )
            if not call_rows:
                break
            before_id = call_rows[-1].id
            admitted_calls = budget.admit_page(call_rows)
            if not admitted_calls:
                break
            call_events = {row.id: _to_event(row) for row in admitted_calls}
            call_ids = tuple(
                event.payload.call_id
                for event in call_events.values()
                if isinstance(event.payload, ClientToolCallPayload)
            )
            result_rows = await self._historical_memory_tool_results(
                session,
                session_id=session_id,
                tail_event_id=tail_event_id,
                call_ids=call_ids,
                budget=result_budget,
            )
            for row in result_rows:
                payload = _to_event(row).payload
                if isinstance(payload, ClientToolResultPayload):
                    linked_results[payload.call_id] = row
                    result_payloads[payload.call_id] = payload
            for row in admitted_calls:
                event = call_events[row.id]
                evidence = project_historical_memory_event(
                    event,
                    client_results=result_payloads,
                )
                if evidence is None:
                    continue
                target = (
                    valid_rows
                    if evidence.tier is HistoricalMemoryEvidenceTier.ASSISTANT
                    else fallback_rows
                )
                if len(target) < limit:
                    target.append(row)
                    if target is valid_rows and isinstance(
                        event.payload, ClientToolCallPayload
                    ):
                        valid_call_ids.add(event.payload.call_id)
            if len(call_rows) < page_limit:
                break
        return [
            *valid_rows,
            *fallback_rows,
            *(
                row
                for call_id, row in linked_results.items()
                if call_id in valid_call_ids
            ),
        ]

    async def _historical_memory_tool_results(
        self,
        session: ReadSession,
        *,
        session_id: str,
        tail_event_id: str,
        call_ids: tuple[str, ...],
        budget: _HistoricalMemoryScanBudget,
    ) -> list[RDBEvent]:
        """Load correlated registered-tool results for one call page."""
        if not call_ids or budget.exhausted:
            return []
        result = await session.read_session.execute(
            sa.select(RDBEvent)
            .where(
                RDBEvent.session_id == session_id,
                RDBEvent.id <= tail_event_id,
                RDBEvent.reverted.is_(False),
                RDBEvent.kind == EventKind.CLIENT_TOOL_RESULT,
                RDBEvent.payload["call_id"].astext.in_(call_ids),
            )
            .order_by(RDBEvent.id.desc())
            .limit(budget.next_page_limit)
        )
        return budget.admit_page(list(result.scalars()))

    @staticmethod
    def _historical_memory_generic_tool_clause(
        registered_tool_names: tuple[str, ...],
    ) -> sa.ColumnElement[bool]:
        """Exclude registered tool rows owned by the dedicated semantic lanes."""
        if not registered_tool_names:
            return RDBEvent.kind.in_(
                (
                    EventKind.CLIENT_TOOL_CALL,
                    EventKind.CLIENT_TOOL_RESULT,
                    EventKind.PROVIDER_TOOL_CALL,
                )
            )
        unregistered_name = sa.or_(
            RDBEvent.payload["name"].astext.is_(None),
            RDBEvent.payload["name"].astext.not_in(registered_tool_names),
        )
        return sa.or_(
            RDBEvent.kind == EventKind.PROVIDER_TOOL_CALL,
            sa.and_(
                RDBEvent.kind.in_(
                    (
                        EventKind.CLIENT_TOOL_CALL,
                        EventKind.CLIENT_TOOL_RESULT,
                    )
                ),
                unregistered_name,
            ),
        )

    async def list_by_session_id_paginated(
        self,
        session: ReadSession,
        session_id: str,
        limit: int = 50,
        before: str | None = None,
    ) -> ChatMessagePage:
        """Fetch session messages paginated in reverse order."""
        query = sa.select(RDBEvent).where(
            RDBEvent.session_id == session_id,
            RDBEvent.reverted.is_(False),
        )

        if before is not None:
            query = query.where(RDBEvent.id < before)

        query = query.order_by(RDBEvent.id.desc()).limit(limit + 1)

        result = await session.read_session.execute(query)
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
        return ChatMessagePage(items=messages, has_more=has_more)

    async def list_events_by_session_id_paginated(
        self,
        session: ReadSession,
        session_id: str,
        limit: int = 50,
        before: str | None = None,
        after: str | None = None,
        visible_kinds: frozenset[EventKind] | None = None,
        around: str | None = None,
    ) -> EventPage:
        """Fetch session events with bidirectional cursor."""
        query = sa.select(RDBEvent).where(
            RDBEvent.session_id == session_id,
            RDBEvent.reverted.is_(False),
        )
        visibility_clause = (
            RDBEvent.kind.in_(visible_kinds) if visible_kinds is not None else sa.true()
        )
        query = query.where(visibility_clause)

        if before is not None:
            query = query.where(RDBEvent.id < before)
            query = query.order_by(RDBEvent.id.desc()).limit(limit + 1)
        elif after is not None:
            query = query.where(RDBEvent.id > after)
            query = query.order_by(RDBEvent.id.asc()).limit(limit + 1)
        else:
            if around is not None:
                query = query.where(RDBEvent.id <= around)
            query = query.order_by(RDBEvent.id.desc()).limit(limit + 1)

        result = await session.read_session.execute(query)
        rows = list(result.scalars())

        if len(rows) > limit:
            rows = rows[:limit]

        if after is None:
            rows.reverse()

        oldest_boundary = rows[0].id if rows else before or after or around
        newest_boundary = rows[-1].id if rows else after or before or around
        has_more = False
        if oldest_boundary is not None:
            has_more = bool(
                await session.read_session.scalar(
                    sa.select(
                        sa.exists().where(
                            RDBEvent.session_id == session_id,
                            RDBEvent.reverted.is_(False),
                            visibility_clause,
                            RDBEvent.id < oldest_boundary,
                        )
                    )
                )
            )
        has_newer = False
        if newest_boundary is not None:
            has_newer = bool(
                await session.read_session.scalar(
                    sa.select(
                        sa.exists().where(
                            RDBEvent.session_id == session_id,
                            RDBEvent.reverted.is_(False),
                            visibility_clause,
                            RDBEvent.id > newest_boundary,
                        )
                    )
                )
            )
        return EventPage(
            items=[_to_event(row) for row in rows],
            has_more=has_more,
            has_newer=has_newer,
        )

    async def get_latest_retry_visible_event(
        self,
        session: ReadSession,
        session_id: str,
    ) -> RDBEvent | None:
        """Fetch the newest durable event that is visible in retry eligibility."""
        result = await session.read_session.execute(
            sa.select(RDBEvent)
            .where(
                RDBEvent.session_id == session_id,
                RDBEvent.reverted.is_(False),
            )
            .order_by(RDBEvent.id.desc())
        )
        for row in result.scalars():
            message = event_to_chat_message(row)
            if message is None or self._is_empty(message):
                continue
            if message.role in _INVISIBLE_RETRY_ELIGIBILITY_ROLES:
                continue
            return row
        return None

    async def mark_reverted_from_event_id(
        self,
        session: WriteSession,
        session_id: str,
        event_id: str,
    ) -> int:
        """Hide the selected event and later events from UI and model input."""
        count_result = await session.write_session.execute(
            sa.select(sa.func.count())
            .select_from(RDBEvent)
            .where(
                RDBEvent.session_id == session_id,
                RDBEvent.id >= event_id,
                RDBEvent.reverted.is_(False),
            )
        )
        delete_count = count_result.scalar_one()
        result = await session.write_session.execute(
            sa.update(RDBEvent)
            .where(
                RDBEvent.session_id == session_id,
                RDBEvent.id >= event_id,
                RDBEvent.reverted.is_(False),
            )
            .values(reverted=True)
        )
        del result
        await self._refresh_session_last_user_input_at(session, session_id)
        return delete_count

    async def _refresh_session_last_user_input_at(
        self,
        session: WriteSession,
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
        await session.write_session.execute(
            sa.update(RDBConversation)
            .where(
                RDBConversation.session_id == session_id,
                RDBAgentSession.id == RDBConversation.session_id,
            )
            .values(
                last_user_input_at=sa.func.coalesce(
                    latest_user_input_at,
                    RDBAgentSession.created_at,
                )
            )
        )
        await session.write_session.flush()

    async def is_at_or_before_model_input_head(
        self,
        session: ReadSession,
        session_id: str,
        event_id: str,
    ) -> bool:
        """Check whether the target event is at or before the model-input head."""
        head_event_id = await session.read_session.scalar(
            sa.select(RDBAgentSession.model_input_head_event_id).where(
                RDBAgentSession.id == session_id
            )
        )
        if head_event_id is None:
            return False
        return event_id <= head_event_id

    def _is_empty(self, msg: ChatMessage) -> bool:
        """Return whether message is empty with no displayable content."""
        if msg.role in (
            MessageRole.TURN_COMPLETE,
            MessageRole.RUN_COMPLETE,
        ):
            return False
        return (
            msg.role == MessageRole.ASSISTANT
            and not msg.content
            and msg.tool_calls is None
            and msg.reasoning_summary is None
            and len(msg.attachments) == 0
        )
