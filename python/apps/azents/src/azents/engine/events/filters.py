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
    NativeModelRequest,
    PostLowerFilter,
    PreLowerFilter,
    SessionHeadMoveRepository,
    SummaryGenerator,
)
from azents.engine.events.system_reminders import (
    format_compaction_summary_reminder,
    format_goal_continuation_reminder,
    format_goal_resumed_reminder,
    format_goal_updated_reminder,
    format_interrupted_reminder,
    format_system_reminder,
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
    ProviderToolResultPayload,
    SystemReminderPayload,
    ToolOutput,
    ToolOutputPart,
    TurnMarkerPayload,
    UserContentPart,
    UserMessagePayload,
)
from azents.engine.run.errors import CompactionFailedError
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.model_file import ModelFileRepository

logger = logging.getLogger(__name__)

_TOKEN_BYTES = 4
_CONTINUITY_RECENT_TURNS = 5
_CONTINUITY_MAX_EVENT_TOKENS = 2_000
_CONTINUITY_MAX_EVENT_CHARS = _CONTINUITY_MAX_EVENT_TOKENS * _TOKEN_BYTES
_CONTINUITY_TRUNCATION_MARKER = "\n\n[Event truncated by Azents continuity guard.]"
_EXCHANGE_URI_PREFIX = "exchange://"


AttachmentAvailability = Literal["available", "expired", "unavailable"]


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
        self._exchange_file_repository = (
            exchange_file_repository or ExchangeFileRepository()
        )
        self._transcript_repo = transcript_repo or EventTranscriptRepository()

    async def apply(
        self,
        session: AsyncSession,
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Update attachment availability from Exchange object key status."""
        object_keys = _exchange_attachment_object_keys(transcript)
        if not object_keys:
            return list(transcript)
        statuses = await self._exchange_file_repository.list_statuses_by_object_key(
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
                await self._transcript_repo.update_payload(session, event.id, payload)
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
        self._model_file_repository = model_file_repository or ModelFileRepository()
        self._transcript_repo = transcript_repo or EventTranscriptRepository()

    async def apply(
        self,
        session: AsyncSession,
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Rewrite deleted/missing FilePart as bounded metadata text."""
        model_file_ids = _model_file_ids(transcript)
        if not model_file_ids:
            return list(transcript)
        statuses = await self._model_file_repository.list_statuses_for_session(
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
                await self._transcript_repo.update_payload(session, event.id, payload)
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
        compaction_id_factory: Callable[[], str],
        on_compaction_started: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._session_id = session_id
        self._compactor = compactor
        self._summarize = summarize
        self._max_input_tokens = max_input_tokens
        self._threshold_tokens = compute_auto_compaction_threshold_tokens(
            max_input_tokens
        )
        self._compaction_id_factory = compaction_id_factory
        self._on_compaction_started = on_compaction_started
        self.was_compacted = False

    async def apply(
        self,
        session: AsyncSession,
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Replace old input with append-only summary when threshold is exceeded."""
        self.was_compacted = False
        events = list(transcript)
        if _compaction_input_tokens(events) <= self._threshold_tokens:
            return events

        if self._on_compaction_started is not None:
            await self._on_compaction_started()

        summary = await self._compactor.compact(
            session,
            session_id=self._session_id,
            transcript=events,
            compaction_id=self._compaction_id_factory(),
            summarize=self._summarize,
            summary_context_window_tokens=self._max_input_tokens,
            reason="auto_threshold_exceeded",
        )
        if summary is None:
            return events
        self.was_compacted = True
        return [summary]


class NativeRequestSizeGuard:
    """Post-lower native request size guard."""

    def __init__(self, *, max_input_chars: int) -> None:
        self._max_input_chars = max_input_chars

    def apply(self, request: NativeModelRequest) -> NativeModelRequest:
        """Fail when native request exceeds the specified character budget."""
        input_chars = _native_request_input_chars(request)
        if input_chars > self._max_input_chars:
            raise ValueError("Native model request input exceeds size guard")
        return request


class PostLowerFilterPipeline:
    """Adapter native post-lower filter pipeline."""

    def __init__(self, filters: Sequence[PostLowerFilter]) -> None:
        self._filters = list(filters)

    @property
    def filters(self) -> tuple[PostLowerFilter, ...]:
        """Return configured filter list."""
        return tuple(self._filters)

    def apply(self, request: NativeModelRequest) -> NativeModelRequest:
        """Apply filters in order."""
        current = request
        for filter_ in self._filters:
            current = filter_.apply(current)
        return current


def _native_request_input_chars(request: NativeModelRequest) -> int:
    """Estimate character count of native input payload sent to provider."""
    return len(str(request.input)) + len(str(request.tools)) + len(str(request.kwargs))


@dataclasses.dataclass(frozen=True)
class EventCompactor:
    """Append-only event transcript compactor."""

    transcript_repo: Annotated[
        EventAppendRepository, Depends(EventTranscriptRepository)
    ]
    session_repo: Annotated[SessionHeadMoveRepository, Depends(AgentSessionRepository)]
    summary_context_window_tokens: int | None = None

    async def compact(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        transcript: Sequence[Event],
        compaction_id: str,
        summarize: SummaryGenerator,
        summary_context_window_tokens: int | None = None,
        reason: str | None = None,
    ) -> Event | None:
        """Append summary event and move session model input head to summary."""
        old_events = list(transcript)
        if not old_events:
            return None

        marker_event = await self.transcript_repo.append(
            session,
            EventCreate(
                session_id=session_id,
                kind=EventKind.COMPACTION_MARKER,
                payload=CompactionMarkerPayload(
                    compaction_id=compaction_id,
                    status="started",
                    reason=reason,
                ).model_dump(mode="json", exclude_none=True),
            ),
        )
        summary_budget = compute_summary_budget(
            summary_context_window_tokens or self.summary_context_window_tokens
        )
        try:
            summary = await summarize(old_events, summary_budget)
        except Exception as exc:
            await self.transcript_repo.append(
                session,
                EventCreate(
                    session_id=session_id,
                    kind=EventKind.COMPACTION_MARKER,
                    payload=CompactionMarkerPayload(
                        compaction_id=compaction_id,
                        status="failed",
                        reason="summary_failed",
                        error=str(exc),
                    ).model_dump(mode="json", exclude_none=True),
                ),
            )
            raise

        if not summary.strip():
            await self.transcript_repo.append(
                session,
                EventCreate(
                    session_id=session_id,
                    kind=EventKind.COMPACTION_MARKER,
                    payload=CompactionMarkerPayload(
                        compaction_id=compaction_id,
                        status="failed",
                        reason="empty_summary",
                    ).model_dump(mode="json", exclude_none=True),
                ),
            )
            raise CompactionFailedError(
                "Compaction failed: summary model returned no text."
            )

        summary_with_continuity = _append_continuity_events(summary, old_events)
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
            ),
        )
        marker_order = old_events[-1].model_order + 1
        summary_order = marker_order + 1
        order_updates = {
            marker_event.id: marker_order,
            summary_event.id: summary_order,
        }
        await self.transcript_repo.update_model_orders(
            session,
            session_id,
            order_updates,
        )
        await self.session_repo.move_model_input_head(
            session,
            session_id,
            summary_event.id,
        )
        return summary_event.model_copy(update={"model_order": summary_order})


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


def _visible_input_content(content: str | list[UserContentPart]) -> object:
    """Return only model-visible values from user content."""
    if isinstance(content, str):
        return content
    return [_visible_part(part) for part in content]


def _visible_output_content(content: str | list[OutputContentPart]) -> object:
    """Return only model-visible values from assistant/output content."""
    if isinstance(content, str):
        return content
    return [_visible_part(part) for part in content]


def _visible_tool_output(output: ToolOutput) -> object:
    """Return only model-visible values from tool output."""
    if isinstance(output, str):
        return output
    return [_visible_part(part) for part in output]


def _visible_part(part: UserContentPart | OutputContentPart) -> object:
    """Return model-visible projection of content part."""
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
        "name": part.name,
        "media_type": part.media_type,
        "status": part.status,
    }


def _provider_tool_call_text(payload: ProviderToolCallPayload) -> str:
    """Return model-visible text of provider tool call."""
    return f"[Provider tool call: {payload.name}({payload.arguments or ''})]"


def _provider_tool_result_text(payload: ProviderToolResultPayload) -> str:
    """Return model-visible text of provider tool result."""
    return (
        f"[Provider tool result: {payload.name or 'unknown'} {payload.status}] "
        f"{_tool_output_text(payload.output)}"
    )


def _tool_output_text(output: ToolOutput) -> str:
    """Join text bodies of tool output."""
    if isinstance(output, str):
        return output
    texts: list[str] = []
    for part in iter_output_parts(output):
        if isinstance(part, OutputTextPart):
            texts.append(part.text)
    return "\n".join(texts)


def _drop_none_values(value: dict[str, object | None]) -> dict[str, object]:
    """Return dict excluding None values."""
    return {key: item for key, item in value.items() if item is not None}


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


def _append_continuity_events(summary: str, events: Sequence[Event]) -> str:
    """Append bounded recent event excerpts to the compaction summary."""
    rendered_events = [
        rendered
        for event in _select_recent_turn_events(events, _CONTINUITY_RECENT_TURNS)
        if (rendered := _render_continuity_event(event)) is not None
    ]
    if not rendered_events:
        return summary

    lines = [
        summary.rstrip(),
        "",
        "## Recent Events for Continuity",
        (
            "The following are raw excerpts from the most recent compacted events "
            "so the next agent can continue from the immediate context. The full "
            "compacted transcript was already included in the summary above. Each "
            "event excerpt is independently bounded and may be truncated."
        ),
        f"Recent turn window: last {_CONTINUITY_RECENT_TURNS} user turns.",
        f"Per-event excerpt cap: {_CONTINUITY_MAX_EVENT_TOKENS} estimated tokens.",
        "",
    ]
    for index, rendered in enumerate(rendered_events, start=1):
        lines.append(f"### Recent Event {index}")
        if rendered.truncated:
            lines.append(
                "This event excerpt was truncated "
                f"from {rendered.original_chars} characters."
            )
        lines.append(rendered.text)
        lines.append("")
    return "\n".join(lines).strip()


def _select_recent_turn_events(events: Sequence[Event], max_turns: int) -> list[Event]:
    """Return events belonging to the last user turns."""
    if max_turns <= 0:
        return []
    user_turn_indexes = [
        index
        for index, event in enumerate(events)
        if event.kind == EventKind.USER_MESSAGE
        and isinstance(event.payload, UserMessagePayload)
    ]
    if not user_turn_indexes:
        return list(events)
    if len(user_turn_indexes) <= max_turns:
        return list(events[user_turn_indexes[0] :])
    return list(events[user_turn_indexes[-max_turns] :])


def _render_continuity_event(event: Event) -> _ContinuityEventRender | None:
    """Render one event as a bounded model-visible continuity excerpt."""
    visible_value = _model_visible_event_value(event)
    if visible_value is None:
        return None
    event_text = json.dumps(
        {
            "kind": event.kind.value,
            "model_order": event.model_order,
            "content": visible_value,
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
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
    """Return model-visible content for continuity rendering."""
    payload = event.payload
    if event.kind == EventKind.GOAL_CONTINUATION and isinstance(
        payload, UserMessagePayload
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
        return {"role": "user", "content": _visible_input_content(payload.content)}
    if isinstance(payload, AssistantMessagePayload):
        return {
            "role": "assistant",
            "content": _visible_output_content(payload.content),
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
            "output": _visible_tool_output(payload.output),
        }
    if isinstance(payload, ProviderToolCallPayload):
        return {"role": "assistant", "content": _provider_tool_call_text(payload)}
    if isinstance(payload, ProviderToolResultPayload):
        return {"role": "assistant", "content": _provider_tool_result_text(payload)}
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
            "content": format_system_reminder(
                reminder_type="system_reminder",
                instruction=payload.text,
                data=(),
            ),
        }
    return None


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
    if isinstance(payload, ClientToolResultPayload | ProviderToolResultPayload):
        for part in iter_output_parts(payload.output):
            if isinstance(part, AttachmentOutputPart):
                uris.append(part.uri)
    return uris


def _payload_attachments(payload: EventPayload) -> list[Attachment]:
    """Return payload attachment list."""
    if isinstance(
        payload,
        UserMessagePayload
        | AssistantMessagePayload
        | ClientToolResultPayload
        | ProviderToolResultPayload,
    ):
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
        attachments, changed = _refresh_attachment_list(payload.attachments, statuses)
        if not changed:
            return None
        return payload.model_copy(update={"attachments": attachments})
    if isinstance(payload, AssistantMessagePayload):
        attachments, attachments_changed = _refresh_attachment_list(
            payload.attachments,
            statuses,
        )
        content, content_changed = _refresh_output_attachment_parts(
            payload.content,
            statuses,
        )
        if not attachments_changed and not content_changed:
            return None
        return payload.model_copy(
            update={"attachments": attachments, "content": content}
        )
    if isinstance(payload, ClientToolResultPayload):
        attachments, attachments_changed = _refresh_attachment_list(
            payload.attachments,
            statuses,
        )
        output, output_changed = _refresh_tool_output_attachment_parts(
            payload.output,
            statuses,
        )
        if not attachments_changed and not output_changed:
            return None
        return payload.model_copy(update={"attachments": attachments, "output": output})
    if isinstance(payload, ProviderToolResultPayload):
        attachments, attachments_changed = _refresh_attachment_list(
            payload.attachments,
            statuses,
        )
        output, output_changed = _refresh_tool_output_attachment_parts(
            payload.output,
            statuses,
        )
        if not attachments_changed and not output_changed:
            return None
        return payload.model_copy(update={"attachments": attachments, "output": output})
    return None


def _refresh_attachment_list(
    attachments: Sequence[Attachment],
    statuses: dict[str, ExchangeFileStatus],
) -> tuple[list[Attachment], bool]:
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
    return refreshed, changed


def _refresh_output_attachment_parts(
    content: str | Sequence[OutputContentPart],
    statuses: dict[str, ExchangeFileStatus],
) -> tuple[str | list[OutputContentPart], bool]:
    """Update assistant output attachment part availability."""
    if isinstance(content, str):
        return content, False
    changed = False
    refreshed: list[OutputContentPart] = []
    for part in content:
        refreshed_part = _refresh_attachment_output_part(part, statuses)
        if refreshed_part != part:
            changed = True
        refreshed.append(refreshed_part)
    return refreshed, changed


def _refresh_tool_output_attachment_parts(
    output: str | Sequence[ToolOutputPart],
    statuses: dict[str, ExchangeFileStatus],
) -> tuple[str | list[ToolOutputPart], bool]:
    """Update tool output attachment part availability."""
    if isinstance(output, str):
        return output, False
    changed = False
    refreshed: list[ToolOutputPart] = []
    for part in output:
        refreshed_part = _refresh_attachment_output_part(part, statuses)
        if refreshed_part != part:
            changed = True
        refreshed.append(refreshed_part)
    return refreshed, changed


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
    if isinstance(payload, ClientToolResultPayload | ProviderToolResultPayload):
        return [
            part
            for part in iter_output_parts(payload.output)
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
        content, changed = _replace_user_file_parts(payload.content, statuses)
        if not changed:
            return None
        return payload.model_copy(update={"content": content})
    if isinstance(payload, AssistantMessagePayload):
        if isinstance(payload.content, str):
            return None
        content, changed = _replace_output_file_parts(payload.content, statuses)
        if not changed:
            return None
        return payload.model_copy(update={"content": content})
    if isinstance(payload, ClientToolResultPayload):
        output, changed = _replace_tool_output_file_parts(payload.output, statuses)
        if not changed:
            return None
        return payload.model_copy(update={"output": output})
    if isinstance(payload, ProviderToolResultPayload):
        output, changed = _replace_tool_output_file_parts(payload.output, statuses)
        if not changed:
            return None
        return payload.model_copy(update={"output": output})
    return None


def _replace_user_file_parts(
    content: Sequence[UserContentPart],
    statuses: dict[str, ModelFileStatus],
) -> tuple[list[UserContentPart], bool]:
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
    return output, changed


def _replace_output_file_parts(
    content: Sequence[OutputContentPart],
    statuses: dict[str, ModelFileStatus],
) -> tuple[list[OutputContentPart], bool]:
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
    return output, changed


def _replace_tool_output_file_parts(
    output: str | list[ToolOutputPart],
    statuses: dict[str, ModelFileStatus],
) -> tuple[str | list[ToolOutputPart], bool]:
    """Replace tool output FilePart with OutputTextPart placeholder."""
    if isinstance(output, str):
        return output, False
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
    return replaced, changed


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
