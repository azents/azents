"""Event runtime filters and append-only compaction."""

import dataclasses
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Literal, NamedTuple, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import EventKind, ExchangeFileStatus, ModelFileStatus
from azents.engine.context.compaction import compute_summary_budget
from azents.engine.context.window import compute_auto_compaction_threshold_tokens
from azents.engine.events.file_parts import file_output_part_placeholder_text
from azents.engine.events.output_parts import iter_output_parts
from azents.engine.events.protocols import (
    EventAppendRepository,
    EventPayloadRepository,
    ManualCompactor,
    NativeRequestInspection,
    PostLowerFilter,
    PreLowerFilter,
    SessionHeadMoveRepository,
    SummaryEnricher,
    SummaryGenerator,
)
from azents.engine.events.provider_tool_rendering import render_provider_tool_semantic
from azents.engine.events.system_reminders import (
    format_compaction_summary_reminder,
    format_goal_continuation_reminder,
    format_goal_resumed_reminder,
    format_goal_updated_reminder,
    format_interrupted_reminder,
    format_plain_system_reminder,
)
from azents.engine.events.types import (
    AssistantMessagePayload,
    Attachment,
    AttachmentOutputPart,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionMarkerPayload,
    CompactionSummaryPayload,
    Event,
    EventPayload,
    FileOutputPart,
    InputTextPart,
    InterruptedPayload,
    OutputContentPart,
    OutputTextPart,
    ProviderToolCallPayload,
    SystemReminderPayload,
    ToolOutput,
    ToolOutputPart,
    TurnMarkerPayload,
    UserContentPart,
    UserMessagePayload,
)
from azents.engine.run.errors import CompactionFailedError, CompactionPlanStaleError
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.model_file import ModelFileRepository

logger = logging.getLogger(__name__)

_TOKEN_BYTES = 4
_CONTINUITY_RECENT_TURNS = 5
_CONTINUITY_RECENT_USER_MESSAGES = 5
_CONTINUITY_MAX_EVENT_TOKENS = 2_000
_CONTINUITY_MAX_EVENT_CHARS = _CONTINUITY_MAX_EVENT_TOKENS * _TOKEN_BYTES
_CONTINUITY_TRUNCATION_MARKER = "\n\n[Event truncated by Azents continuity guard.]"
_EXCHANGE_URI_PREFIX = "exchange://"


AttachmentAvailability = Literal["available", "expired", "unavailable"]


@dataclasses.dataclass(frozen=True)
class _ChangedValue[T]:
    """Value returned by a transformation together with its change flag."""

    value: T
    changed: bool


class ModelFileStatusRepository(Protocol):
    """ModelFile status lookup repository."""

    async def list_statuses_for_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        model_file_ids: Sequence[str],
    ) -> dict[str, ModelFileStatus]:
        """Return status by ModelFile ID belonging to session."""
        ...


class ExchangeFileStatusRepository(Protocol):
    """ExchangeFile status lookup repository."""

    async def list_statuses_by_object_key(
        self,
        session: AsyncSession,
        *,
        object_keys: Sequence[str],
    ) -> dict[str, ExchangeFileStatus]:
        """Return ExchangeFile status by object key."""
        ...


class EventPreLowerFilterPipeline:
    """Event pre-lower filter pipeline."""

    def __init__(self, filters: Sequence[PreLowerFilter]) -> None:
        self._filters = list(filters)
        self.was_compacted = False

    @property
    def filters(self) -> tuple[PreLowerFilter, ...]:
        """Return configured filter list."""
        return tuple(self._filters)

    async def apply(
        self,
        session: AsyncSession,
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Apply filters in order."""
        self.was_compacted = False
        current = list(transcript)
        for filter_ in self._filters:
            current = await filter_.apply(session, current)
            self.was_compacted = self.was_compacted or filter_.was_compacted
        return current


class NoopPreLowerFilter:
    """Pre-lower filter with no changes."""

    was_compacted = False

    async def apply(
        self,
        session: AsyncSession,
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Return transcript as-is."""
        del session
        return list(transcript)


class EventAttachmentAvailabilityFilter:
    """Reflect Exchange attachment availability in durable event payload."""

    was_compacted = False

    def __init__(
        self,
        *,
        exchange_file_repository: ExchangeFileStatusRepository | None = None,
        transcript_repo: EventPayloadRepository | None = None,
    ) -> None:
        self.exchange_file_repository = (
            exchange_file_repository or ExchangeFileRepository()
        )
        self.transcript_repo = transcript_repo or EventTranscriptRepository()

    async def apply(
        self,
        session: AsyncSession,
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Update attachment availability from Exchange object key status."""
        object_keys = _exchange_attachment_object_keys(transcript)
        if not object_keys:
            return list(transcript)
        statuses = await self.exchange_file_repository.list_statuses_by_object_key(
            session,
            object_keys=object_keys,
        )
        updated: list[Event] = []
        for event in transcript:
            payload = _refresh_attachment_availability(event.payload, statuses)
            if payload is None:
                updated.append(event)
                continue
            updated.append(
                await self.transcript_repo.update_payload(session, event.id, payload)
            )
        return updated


class EventFilePartPlaceholderFilter:
    """Replace unavailable ModelFile FilePart with text in durable payload."""

    was_compacted = False

    def __init__(
        self,
        *,
        session_id: str,
        model_file_repository: ModelFileStatusRepository | None = None,
        transcript_repo: EventPayloadRepository | None = None,
    ) -> None:
        self._session_id = session_id
        self.model_file_repository = model_file_repository or ModelFileRepository()
        self.transcript_repo = transcript_repo or EventTranscriptRepository()

    async def apply(
        self,
        session: AsyncSession,
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Rewrite deleted/missing FilePart as bounded metadata text."""
        model_file_ids = _model_file_ids(transcript)
        if not model_file_ids:
            return list(transcript)
        statuses = await self.model_file_repository.list_statuses_for_session(
            session,
            session_id=self._session_id,
            model_file_ids=model_file_ids,
        )
        updated: list[Event] = []
        for event in transcript:
            payload = _replace_unavailable_file_parts(event.payload, statuses)
            if payload is None:
                updated.append(event)
                continue
            updated.append(
                await self.transcript_repo.update_payload(session, event.id, payload)
            )
        return updated


class EventAutoCompactionFilter:
    """Decide compaction from provider usage and following delta estimate."""

    def __init__(
        self,
        *,
        session_id: str,
        compactor: ManualCompactor,
        summarize: SummaryGenerator,
        max_input_tokens: int,
        auto_compaction_threshold_tokens: int | None,
        compaction_id_factory: Callable[[], str],
        on_compaction_started: Callable[[], Awaitable[None]] | None = None,
        summary_enricher: SummaryEnricher | None = None,
    ) -> None:
        self._session_id = session_id
        self.compactor = compactor
        self.summarize = summarize
        self._max_input_tokens = max_input_tokens
        self._threshold_tokens = (
            auto_compaction_threshold_tokens
            if auto_compaction_threshold_tokens is not None
            else compute_auto_compaction_threshold_tokens(max_input_tokens)
        )
        self.compaction_id_factory = compaction_id_factory
        self.on_compaction_started = on_compaction_started
        self.summary_enricher = summary_enricher
        self.was_compacted = False

    async def compact(
        self,
        transcript: Sequence[Event],
        *,
        on_started: Callable[[], Awaitable[None]] | None = None,
    ) -> list[Event]:
        """Compact model input without keeping a caller-owned DB session open."""
        self.was_compacted = False
        events = list(transcript)
        if _compaction_input_tokens(events) <= self._threshold_tokens:
            return events

        async def notify_started() -> None:
            if on_started is not None:
                await on_started()
            if self.on_compaction_started is not None:
                await self.on_compaction_started()

        summary = await self.compactor.compact(
            session_id=self._session_id,
            transcript=events,
            compaction_id=self.compaction_id_factory(),
            summarize=self.summarize,
            on_started=notify_started,
            summary_context_window_tokens=self._max_input_tokens,
            reason="auto_threshold_exceeded",
            summary_enricher=self.summary_enricher,
        )
        if summary is None:
            return events
        self.was_compacted = True
        return [summary]


class NativeRequestSizeGuard[TNativeRequest: NativeRequestInspection]:
    """Post-lower native request size guard."""

    def __init__(self, *, max_input_chars: int) -> None:
        self._max_input_chars = max_input_chars

    def apply(self, request: TNativeRequest) -> TNativeRequest:
        """Fail when the complete logical request exceeds the character budget."""
        if request.native_request_input_chars() > self._max_input_chars:
            raise ValueError("Native model request input exceeds size guard")
        return request


class PostLowerFilterPipeline[TNativeRequest]:
    """Adapter native post-lower filter pipeline."""

    def __init__(self, filters: Sequence[PostLowerFilter[TNativeRequest]]) -> None:
        self._filters = list(filters)

    @property
    def filters(self) -> tuple[PostLowerFilter[TNativeRequest], ...]:
        """Return configured filter list."""
        return tuple(self._filters)

    def apply(self, request: TNativeRequest) -> TNativeRequest:
        """Apply filters in order."""
        current = request
        for filter_ in self._filters:
            current = filter_.apply(current)
        return current


@dataclasses.dataclass(frozen=True)
class EventCompactor:
    """Append-only event transcript compactor."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    transcript_repo: Annotated[
        EventAppendRepository, Depends(EventTranscriptRepository)
    ]
    session_repo: Annotated[SessionHeadMoveRepository, Depends(AgentSessionRepository)]
    summary_context_window_tokens: int | None = None

    async def compact(
        self,
        *,
        session_id: str,
        transcript: Sequence[Event],
        compaction_id: str,
        summarize: SummaryGenerator,
        on_started: Callable[[], Awaitable[None]] | None = None,
        summary_context_window_tokens: int | None = None,
        reason: str | None = None,
        summary_enricher: SummaryEnricher | None = None,
    ) -> Event | None:
        """Append one successful summary and move the model-input head."""
        old_events = list(transcript)
        if not old_events:
            return None

        async with self.session_manager() as session:
            session_state = await self.session_repo.get_by_id(session, session_id)
        if session_state is None:
            raise ValueError("AgentSession not found")
        expected_head_event_id = session_state.model_input_head_event_id
        marker_order = max(event.model_order for event in old_events) + 1
        summary_order = marker_order + 1

        if on_started is not None:
            await on_started()

        summary_budget = compute_summary_budget(
            summary_context_window_tokens or self.summary_context_window_tokens
        )
        summary = await summarize(old_events, summary_budget)
        if not summary.strip():
            raise CompactionFailedError(
                "Compaction failed: summary model returned no text."
            )

        continuity_history = _render_continuity_history(old_events)
        if summary_enricher is not None:
            summary = await summary_enricher(
                summary=summary,
                continuity_history=continuity_history,
                compaction_id=compaction_id,
                reason=reason,
                covered_until_event_id=old_events[-1].id,
            )
        if not summary.strip():
            raise CompactionFailedError(
                "Compaction failed: summary enrichment returned no text."
            )

        summary_with_continuity = _append_continuity_history(
            summary,
            continuity_history,
        )
        async with self.session_manager() as session:
            current = await self.session_repo.lock_model_input_head_if_current(
                session,
                session_id=session_id,
                expected_event_id=expected_head_event_id,
            )
            if not current:
                raise CompactionPlanStaleError(
                    "Compaction plan no longer matches the model-input head."
                )
            await self.transcript_repo.append(
                session,
                EventCreate(
                    session_id=session_id,
                    kind=EventKind.COMPACTION_MARKER,
                    payload=CompactionMarkerPayload(
                        compaction_id=compaction_id,
                        status="started",
                        reason=reason,
                    ).model_dump(mode="json", exclude_none=True),
                    model_order=marker_order,
                ),
            )
            summary_event = await self.transcript_repo.append(
                session,
                EventCreate(
                    session_id=session_id,
                    kind=EventKind.COMPACTION_SUMMARY,
                    payload=CompactionSummaryPayload(
                        compaction_id=compaction_id,
                        content=summary_with_continuity,
                        covered_until_event_id=old_events[-1].id,
                        reason=reason,
                    ).model_dump(mode="json", exclude_none=True),
                    model_order=summary_order,
                ),
            )
            await self.session_repo.move_model_input_head(
                session,
                session_id,
                summary_event.id,
            )
        return summary_event


def _compaction_input_tokens(events: Sequence[Event]) -> int:
    """Return input token count from provider usage and following delta."""
    latest_marker_index = _latest_turn_marker_index(events)
    if latest_marker_index is None:
        return _estimate_event_tokens(events)
    marker = events[latest_marker_index]
    payload = marker.payload
    if not isinstance(payload, TurnMarkerPayload):
        return _estimate_event_tokens(events)
    return payload.usage.prompt_tokens + _estimate_event_tokens(
        events[latest_marker_index + 1 :]
    )


def _latest_turn_marker_index(events: Sequence[Event]) -> int | None:
    """Return latest turn marker index."""
    for index in range(len(events) - 1, -1, -1):
        if isinstance(events[index].payload, TurnMarkerPayload):
            return index
    return None


def _estimate_single_event_tokens(event: Event) -> int:
    """Return rough token estimate based on model-visible byte cost."""
    return _estimate_bytes_tokens(_estimate_event_visible_bytes(event))


def _format_goal_updated_event_reminder(payload: UserMessagePayload) -> str:
    """Render model-visible reminder for goal_updated event metadata."""
    if payload.metadata.get("goal_control_action") == "resume":
        return format_goal_resumed_reminder(
            goal_objective=payload.metadata.get("goal_objective"),
            previous_goal_status=payload.metadata.get("previous_goal_status"),
            resume_hint=payload.metadata.get("resume_hint"),
        )
    return format_goal_updated_reminder(payload.metadata.get("goal_objective"))


def _estimate_event_tokens(events: Sequence[Event]) -> int:
    """Return model-visible rough token estimate for Event transcript."""
    return sum(_estimate_single_event_tokens(event) for event in events)


def _estimate_event_visible_bytes(event: Event) -> int:
    """Calculate model-visible byte cost for one Event."""
    visible_value = _model_visible_event_value(event)
    if visible_value is None:
        return 0
    return _compact_json_bytes(visible_value)


def _visible_input_content(content: str | Sequence[UserContentPart]) -> str:
    """Return only model-visible text from user content."""
    if isinstance(content, str):
        return content
    return _join_visible_parts(content)


def _visible_output_content(content: str | Sequence[OutputContentPart]) -> str:
    """Return only model-visible text from assistant/output content."""
    if isinstance(content, str):
        return content
    return _join_visible_parts(content)


def _visible_tool_output(output: ToolOutput) -> str:
    """Return only model-visible text from tool output."""
    if isinstance(output, str):
        return output
    return _join_visible_parts(output)


def _join_visible_parts(
    parts: Sequence[UserContentPart | OutputContentPart | ToolOutputPart],
) -> str:
    """Join model-visible text projections of content parts."""
    rendered = [_visible_part(part).strip() for part in parts]
    return "\n".join(part for part in rendered if part)


def _visible_part(part: UserContentPart | OutputContentPart | ToolOutputPart) -> str:
    """Return model-visible text projection of one content part."""
    if isinstance(part, InputTextPart | OutputTextPart):
        return part.text
    if isinstance(part, FileOutputPart):
        return _format_visible_metadata(
            "File",
            name=part.name,
            media_type=part.media_type,
            kind=part.kind,
            detail=part.detail,
            caption=part.caption,
            alt_text=part.alt_text,
        )
    if isinstance(part, AttachmentOutputPart):
        return _format_visible_metadata(
            "Attachment",
            name=part.name,
            media_type=part.media_type,
            availability=part.availability,
        )
    return _format_visible_metadata(
        "Artifact",
        name=getattr(part, "name", None),
        media_type=getattr(part, "media_type", None),
        status=getattr(part, "status", None),
    )


def _format_visible_metadata(label: str, **fields: object) -> str:
    """Render non-empty metadata as compact human-readable text."""
    values = [
        f"{key}={value}"
        for key, value in fields.items()
        if value is not None and value != ""
    ]
    if not values:
        return f"[{label}]"
    return f"[{label}: {'; '.join(values)}]"


def _visible_input_content_value(content: str | Sequence[UserContentPart]) -> object:
    """Return only model-visible structured values from user content."""
    if isinstance(content, str):
        return content
    return [_visible_part_value(part) for part in content]


def _visible_output_content_value(content: str | Sequence[OutputContentPart]) -> object:
    """Return only model-visible structured values from assistant content."""
    if isinstance(content, str):
        return content
    return [_visible_part_value(part) for part in content]


def _visible_tool_output_value(output: ToolOutput) -> object:
    """Return only model-visible structured values from tool output."""
    if isinstance(output, str):
        return output
    return [_visible_part_value(part) for part in output]


def _visible_part_value(
    part: UserContentPart | OutputContentPart | ToolOutputPart,
) -> object:
    """Return model-visible structured projection of one content part."""
    if isinstance(part, InputTextPart | OutputTextPart):
        return {"type": part.type, "text": part.text}
    if isinstance(part, FileOutputPart):
        return _drop_none_values(
            {
                "type": "file",
                "media_type": part.media_type,
                "name": part.name,
                "kind": part.kind,
                "detail": part.detail,
                "caption": part.caption,
                "alt_text": part.alt_text,
            }
        )
    if isinstance(part, AttachmentOutputPart):
        return {
            "type": "attachment",
            "name": part.name,
            "media_type": part.media_type,
            "availability": part.availability,
        }
    return {
        "type": "artifact",
        "name": getattr(part, "name", None),
        "media_type": getattr(part, "media_type", None),
        "status": getattr(part, "status", None),
    }


def _drop_none_values(value: dict[str, object | None]) -> dict[str, object]:
    """Return dict excluding None values."""
    return {key: item for key, item in value.items() if item is not None}


def _format_tool_call_text(
    *,
    title: str,
    call_id: str | None,
    arguments: str | None,
) -> str:
    """Render a tool call as readable transcript text."""
    lines = [title]
    if call_id:
        lines.append(f"call_id: {call_id}")
    if arguments:
        lines.append("arguments:")
        lines.append(arguments)
    return "\n".join(lines)


def _compact_json_bytes(value: object) -> int:
    """Return compact JSON serialization byte count."""
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _estimate_bytes_tokens(byte_count: int) -> int:
    """Return rough token estimate from byte count."""
    if byte_count <= 0:
        return 0
    return (byte_count + _TOKEN_BYTES - 1) // _TOKEN_BYTES


class _ContinuityEventRender(NamedTuple):
    """Rendered recent event excerpt for compaction continuity."""

    text: str
    truncated: bool
    original_chars: int


def _render_continuity_history(events: Sequence[Event]) -> str:
    """Render bounded recent event excerpts for compaction continuity."""
    rendered_user_messages = [
        rendered
        for event in _select_recent_user_message_events(
            events,
            _CONTINUITY_RECENT_USER_MESSAGES,
        )
        if (
            rendered := _render_continuity_event(
                event,
                include_label=False,
            )
        )
        is not None
    ]
    rendered_events = [
        rendered
        for event in _select_recent_turn_events(events, _CONTINUITY_RECENT_TURNS)
        if (rendered := _render_continuity_event(event)) is not None
    ]
    if not rendered_user_messages and not rendered_events:
        return ""

    lines: list[str] = []
    if rendered_user_messages:
        lines.extend(
            [
                "## Recent User Messages",
                (
                    "Last "
                    f"{_CONTINUITY_RECENT_USER_MESSAGES} user messages from the "
                    "compacted transcript, kept independent of the recent "
                    "transcript window."
                ),
                f"Per-message cap: {_CONTINUITY_MAX_EVENT_TOKENS} estimated tokens.",
                "",
            ]
        )
        for index, rendered in enumerate(rendered_user_messages, start=1):
            if rendered.truncated:
                lines.append(f"{index}.")
                lines.append(f"Truncated from {rendered.original_chars} characters.")
                lines.append(rendered.text)
            elif "\n" in rendered.text:
                lines.append(f"{index}.")
                lines.append(rendered.text)
            else:
                lines.append(f"{index}. {rendered.text}")
            lines.append("")

    if rendered_events:
        lines.extend(
            [
                "## Recent Transcript",
                (
                    "Recent model-visible excerpts from the compacted transcript. "
                    "Each excerpt is bounded and may be truncated."
                ),
                (
                    "Recent turn window: last "
                    f"{_CONTINUITY_RECENT_TURNS} completed model turns."
                ),
                f"Per-event cap: {_CONTINUITY_MAX_EVENT_TOKENS} estimated tokens.",
                "",
            ]
        )
        for index, rendered in enumerate(rendered_events, start=1):
            lines.append(f"### {index}")
            if rendered.truncated:
                lines.append(f"Truncated from {rendered.original_chars} characters.")
            lines.append(rendered.text)
            lines.append("")
    return "\n".join(lines).strip()


def _append_continuity_history(summary: str, continuity_history: str) -> str:
    """Append already-rendered continuity history after summary."""
    summary = summary.rstrip()
    continuity_history = continuity_history.strip()
    if not continuity_history:
        return summary
    return f"{summary}\n\n{continuity_history}"


def _select_recent_user_message_events(
    events: Sequence[Event], max_messages: int
) -> list[Event]:
    """Return the last user-message events from the selected transcript."""
    if max_messages <= 0:
        return []
    selected = [
        event
        for event in events
        if event.kind == EventKind.USER_MESSAGE
        and isinstance(event.payload, UserMessagePayload)
    ]
    return selected[-max_messages:]


def _select_recent_turn_events(events: Sequence[Event], max_turns: int) -> list[Event]:
    """Return events belonging to the last completed model turns."""
    if max_turns <= 0:
        return []
    turn_marker_indexes = [
        index
        for index, event in enumerate(events)
        if isinstance(event.payload, TurnMarkerPayload)
    ]
    if not turn_marker_indexes:
        return list(events)
    if len(turn_marker_indexes) <= max_turns:
        return list(events)
    start_index = turn_marker_indexes[-max_turns - 1] + 1
    return list(events[start_index:])


def _render_continuity_event(
    event: Event,
    *,
    include_label: bool = True,
) -> _ContinuityEventRender | None:
    """Render one event as a bounded model-visible continuity excerpt."""
    event_text = _model_visible_event_text(event, include_label=include_label)
    if event_text is None:
        return None
    original_chars = len(event_text)
    if original_chars <= _CONTINUITY_MAX_EVENT_CHARS:
        return _ContinuityEventRender(
            text=event_text,
            truncated=False,
            original_chars=original_chars,
        )
    keep_chars = max(
        _CONTINUITY_MAX_EVENT_CHARS - len(_CONTINUITY_TRUNCATION_MARKER),
        0,
    )
    return _ContinuityEventRender(
        text=event_text[:keep_chars].rstrip() + _CONTINUITY_TRUNCATION_MARKER,
        truncated=True,
        original_chars=original_chars,
    )


def _model_visible_event_value(event: Event) -> object | None:
    """Return model-visible structured content for token estimation."""
    payload = event.payload
    if event.kind == EventKind.GOAL_CONTINUATION and isinstance(
        payload,
        UserMessagePayload,
    ):
        return {
            "role": "user",
            "content": format_goal_continuation_reminder(
                payload.metadata.get("goal_objective")
            ),
        }
    if event.kind == EventKind.GOAL_UPDATED and isinstance(payload, UserMessagePayload):
        return {"role": "user", "content": _format_goal_updated_event_reminder(payload)}
    if isinstance(payload, UserMessagePayload):
        return {
            "role": "user",
            "content": _visible_input_content_value(payload.content),
        }
    if isinstance(payload, AssistantMessagePayload):
        return {
            "role": "assistant",
            "content": _visible_output_content_value(payload.content),
        }
    if isinstance(payload, ClientToolCallPayload):
        return {
            "type": "function_call",
            "call_id": payload.call_id,
            "name": payload.name,
            "arguments": payload.arguments,
        }
    if isinstance(payload, ClientToolResultPayload):
        return {
            "type": "function_call_output",
            "call_id": payload.call_id,
            "output": _visible_tool_output_value(payload.output),
        }
    if isinstance(payload, ProviderToolCallPayload):
        return {
            "role": "assistant",
            "content": render_provider_tool_semantic(payload),
        }
    if isinstance(payload, CompactionSummaryPayload):
        return {
            "role": "user",
            "content": format_compaction_summary_reminder(payload.content),
        }
    if isinstance(payload, InterruptedPayload):
        return {"role": "user", "content": format_interrupted_reminder()}
    if isinstance(payload, SystemReminderPayload):
        return {
            "role": "user",
            "content": format_plain_system_reminder(payload.text),
        }
    return None


def _model_visible_event_text(
    event: Event,
    *,
    include_label: bool = True,
) -> str | None:
    """Return readable model-visible content for continuity rendering."""
    payload = event.payload
    if event.kind == EventKind.GOAL_CONTINUATION and isinstance(
        payload,
        UserMessagePayload,
    ):
        return _format_continuity_block(
            "User",
            format_goal_continuation_reminder(payload.metadata.get("goal_objective")),
            include_label=include_label,
        )
    if event.kind == EventKind.GOAL_UPDATED and isinstance(payload, UserMessagePayload):
        return _format_continuity_block(
            "User",
            _format_goal_updated_event_reminder(payload),
            include_label=include_label,
        )
    if isinstance(payload, UserMessagePayload):
        return _format_continuity_block(
            "User",
            _visible_input_content(payload.content),
            include_label=include_label,
        )
    if isinstance(payload, AssistantMessagePayload):
        return _format_continuity_block(
            "Assistant",
            _visible_output_content(payload.content),
            include_label=include_label,
        )
    if isinstance(payload, ClientToolCallPayload):
        return _format_continuity_block(
            "Tool call",
            _format_tool_call_text(
                title=payload.name,
                call_id=None,
                arguments=payload.arguments,
            ),
            include_label=include_label,
        )
    if isinstance(payload, ClientToolResultPayload):
        return _format_continuity_block(
            "Tool result",
            _visible_tool_output(payload.output),
            include_label=include_label,
        )
    if isinstance(payload, ProviderToolCallPayload):
        return _format_continuity_block(
            "Assistant",
            render_provider_tool_semantic(payload),
            include_label=include_label,
        )
    if isinstance(payload, CompactionSummaryPayload):
        return _format_continuity_block(
            "User",
            format_compaction_summary_reminder(payload.content),
            include_label=include_label,
        )
    if isinstance(payload, InterruptedPayload):
        return _format_continuity_block(
            "User",
            format_interrupted_reminder(),
            include_label=include_label,
        )
    if isinstance(payload, SystemReminderPayload):
        return _format_continuity_block(
            "User",
            format_plain_system_reminder(payload.text),
            include_label=include_label,
        )
    return None


def _format_continuity_block(
    label: str,
    body: str,
    *,
    include_label: bool = True,
) -> str:
    """Render one continuity item without exposing event storage JSON."""
    body = body.strip()
    if not body:
        body = "(no model-visible content)"
    if not include_label:
        return body
    return f"{label}:\n{body}"


def _exchange_attachment_object_keys(
    events: Sequence[Event],
) -> list[str]:
    """Deduplicate exchange attachment object keys preserving order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for event in events:
        for uri in _payload_attachment_uris(event.payload):
            object_key = _exchange_object_key(uri)
            if object_key is None or object_key in seen:
                continue
            seen.add(object_key)
            ordered.append(object_key)
    return ordered


def _payload_attachment_uris(payload: EventPayload) -> list[str]:
    """Return attachment URI list in payload."""
    uris = [attachment.uri for attachment in _payload_attachments(payload)]
    if isinstance(payload, AssistantMessagePayload):
        if isinstance(payload.content, str):
            return uris
        uris.extend(
            part.uri
            for part in payload.content
            if isinstance(part, AttachmentOutputPart)
        )
        return uris
    if isinstance(payload, ClientToolResultPayload):
        for part in iter_output_parts(payload.output):
            if isinstance(part, AttachmentOutputPart):
                uris.append(part.uri)
    if isinstance(payload, ProviderToolCallPayload):
        for part in iter_output_parts(payload.semantic.output):
            if isinstance(part, AttachmentOutputPart):
                uris.append(part.uri)
    return uris


def _payload_attachments(payload: EventPayload) -> list[Attachment]:
    """Return payload attachment list."""
    if isinstance(payload, UserMessagePayload | AssistantMessagePayload):
        return payload.attachments
    return []


def _exchange_object_key(uri: str) -> str | None:
    """Get object storage key from exchange:// URI."""
    if not uri.startswith(_EXCHANGE_URI_PREFIX):
        return None
    object_key = uri.removeprefix(_EXCHANGE_URI_PREFIX)
    if not object_key:
        return None
    return object_key


def _availability_for_uri(
    uri: str,
    statuses: dict[str, ExchangeFileStatus],
) -> AttachmentAvailability | None:
    """Return current availability of Exchange URI."""
    object_key = _exchange_object_key(uri)
    if object_key is None:
        return None
    status = statuses.get(object_key)
    if status is None:
        return "unavailable"
    if status is ExchangeFileStatus.EXPIRED:
        return "expired"
    return "available"


def _refresh_attachment_availability(
    payload: EventPayload,
    statuses: dict[str, ExchangeFileStatus],
) -> EventPayload | None:
    """Update exchange attachment availability in payload."""
    if isinstance(payload, UserMessagePayload):
        refreshed = _refresh_attachment_list(payload.attachments, statuses)
        if not refreshed.changed:
            return None
        return payload.model_copy(update={"attachments": refreshed.value})
    if isinstance(payload, AssistantMessagePayload):
        attachments = _refresh_attachment_list(
            payload.attachments,
            statuses,
        )
        content = _refresh_output_attachment_parts(
            payload.content,
            statuses,
        )
        if not attachments.changed and not content.changed:
            return None
        return payload.model_copy(
            update={"attachments": attachments.value, "content": content.value}
        )
    if isinstance(payload, ClientToolResultPayload):
        output = _refresh_tool_output_attachment_parts(
            payload.output,
            statuses,
        )
        if not output.changed:
            return None
        return payload.model_copy(update={"output": output.value})
    if isinstance(payload, ProviderToolCallPayload):
        output = _refresh_tool_output_attachment_parts(
            payload.semantic.output,
            statuses,
        )
        if not output.changed:
            return None
        return payload.model_copy(
            update={
                "semantic": payload.semantic.model_copy(
                    update={"output": output.value}
                ),
            }
        )
    return None


def _refresh_attachment_list(
    attachments: Sequence[Attachment],
    statuses: dict[str, ExchangeFileStatus],
) -> _ChangedValue[list[Attachment]]:
    """Update availability of attachment list."""
    changed = False
    refreshed: list[Attachment] = []
    for attachment in attachments:
        availability = _availability_for_uri(attachment.uri, statuses)
        if availability is None or attachment.availability == availability:
            refreshed.append(attachment)
            continue
        refreshed.append(attachment.model_copy(update={"availability": availability}))
        changed = True
    return _ChangedValue(value=refreshed, changed=changed)


def _refresh_output_attachment_parts(
    content: str | Sequence[OutputContentPart],
    statuses: dict[str, ExchangeFileStatus],
) -> _ChangedValue[str | list[OutputContentPart]]:
    """Update assistant output attachment part availability."""
    if isinstance(content, str):
        return _ChangedValue(value=content, changed=False)
    changed = False
    refreshed: list[OutputContentPart] = []
    for part in content:
        refreshed_part = _refresh_attachment_output_part(part, statuses)
        if refreshed_part != part:
            changed = True
        refreshed.append(refreshed_part)
    return _ChangedValue(value=refreshed, changed=changed)


def _refresh_tool_output_attachment_parts(
    output: str | Sequence[ToolOutputPart],
    statuses: dict[str, ExchangeFileStatus],
) -> _ChangedValue[str | list[ToolOutputPart]]:
    """Update tool output attachment part availability."""
    if isinstance(output, str):
        return _ChangedValue(value=output, changed=False)
    changed = False
    refreshed: list[ToolOutputPart] = []
    for part in output:
        refreshed_part = _refresh_attachment_output_part(part, statuses)
        if refreshed_part != part:
            changed = True
        refreshed.append(refreshed_part)
    return _ChangedValue(value=refreshed, changed=changed)


def _refresh_attachment_output_part(
    part: OutputContentPart,
    statuses: dict[str, ExchangeFileStatus],
) -> OutputContentPart:
    """Update AttachmentOutputPart availability."""
    if not isinstance(part, AttachmentOutputPart):
        return part
    availability = _availability_for_uri(part.uri, statuses)
    if availability is None or part.availability == availability:
        return part
    return part.model_copy(update={"availability": availability})


def _model_file_ids(events: Sequence[Event]) -> list[str]:
    """Deduplicate FilePart model_file_id values preserving order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for event in events:
        for part in _payload_file_parts(event.payload):
            if part.model_file_id in seen:
                continue
            seen.add(part.model_file_id)
            ordered.append(part.model_file_id)
    return ordered


def _payload_file_parts(payload: EventPayload) -> list[FileOutputPart]:
    """Return FilePart list in payload."""
    if isinstance(payload, UserMessagePayload):
        if isinstance(payload.content, str):
            return []
        return [part for part in payload.content if isinstance(part, FileOutputPart)]
    if isinstance(payload, AssistantMessagePayload):
        if isinstance(payload.content, str):
            return []
        return [part for part in payload.content if isinstance(part, FileOutputPart)]
    if isinstance(payload, ClientToolResultPayload):
        return [
            part
            for part in iter_output_parts(payload.output)
            if isinstance(part, FileOutputPart)
        ]
    if isinstance(payload, ProviderToolCallPayload):
        return [
            part
            for part in iter_output_parts(payload.semantic.output)
            if isinstance(part, FileOutputPart)
        ]
    return []


def _replace_unavailable_file_parts(
    payload: EventPayload,
    statuses: dict[str, ModelFileStatus],
) -> EventPayload | None:
    """Replace unavailable FilePart with text placeholder in payload."""
    if isinstance(payload, UserMessagePayload):
        if isinstance(payload.content, str):
            return None
        content = _replace_user_file_parts(payload.content, statuses)
        if not content.changed:
            return None
        return payload.model_copy(update={"content": content.value})
    if isinstance(payload, AssistantMessagePayload):
        if isinstance(payload.content, str):
            return None
        content = _replace_output_file_parts(payload.content, statuses)
        if not content.changed:
            return None
        return payload.model_copy(update={"content": content.value})
    if isinstance(payload, ClientToolResultPayload):
        output = _replace_tool_output_file_parts(payload.output, statuses)
        if not output.changed:
            return None
        return payload.model_copy(update={"output": output.value})
    if isinstance(payload, ProviderToolCallPayload):
        output = _replace_tool_output_file_parts(payload.semantic.output, statuses)
        if not output.changed:
            return None
        return payload.model_copy(
            update={
                "semantic": payload.semantic.model_copy(update={"output": output.value})
            }
        )
    return None


def _replace_user_file_parts(
    content: Sequence[UserContentPart],
    statuses: dict[str, ModelFileStatus],
) -> _ChangedValue[list[UserContentPart]]:
    """Replace user content FilePart with InputTextPart placeholder."""
    changed = False
    output: list[UserContentPart] = []
    for part in content:
        if isinstance(part, FileOutputPart):
            reason = _unavailable_file_reason(part, statuses)
            if reason is not None:
                output.append(
                    InputTextPart(
                        text=file_output_part_placeholder_text(part, reason=reason)
                    )
                )
                changed = True
                continue
        output.append(part)
    return _ChangedValue(value=output, changed=changed)


def _replace_output_file_parts(
    content: Sequence[OutputContentPart],
    statuses: dict[str, ModelFileStatus],
) -> _ChangedValue[list[OutputContentPart]]:
    """Replace assistant output FilePart with OutputTextPart placeholder."""
    changed = False
    output: list[OutputContentPart] = []
    for part in content:
        if isinstance(part, FileOutputPart):
            reason = _unavailable_file_reason(part, statuses)
            if reason is not None:
                output.append(
                    OutputTextPart(
                        text=file_output_part_placeholder_text(part, reason=reason)
                    )
                )
                changed = True
                continue
        output.append(part)
    return _ChangedValue(value=output, changed=changed)


def _replace_tool_output_file_parts(
    output: str | list[ToolOutputPart],
    statuses: dict[str, ModelFileStatus],
) -> _ChangedValue[str | list[ToolOutputPart]]:
    """Replace tool output FilePart with OutputTextPart placeholder."""
    if isinstance(output, str):
        return _ChangedValue(value=output, changed=False)
    changed = False
    replaced: list[ToolOutputPart] = []
    for part in output:
        if isinstance(part, FileOutputPart):
            reason = _unavailable_file_reason(part, statuses)
            if reason is not None:
                replaced.append(
                    OutputTextPart(
                        text=file_output_part_placeholder_text(part, reason=reason)
                    )
                )
                changed = True
                continue
        replaced.append(part)
    return _ChangedValue(value=replaced, changed=changed)


def _unavailable_file_reason(
    part: FileOutputPart,
    statuses: dict[str, ModelFileStatus],
) -> str | None:
    """Return placeholder reason based on FilePart status."""
    status = statuses.get(part.model_file_id)
    if status is None:
        return "model file metadata is unavailable"
    if status == ModelFileStatus.AVAILABLE:
        return None
    return f"model file status is {status.value}"
