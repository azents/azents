"""Event runtime filters and append-only compaction."""

import dataclasses
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, NamedTuple, assert_never

from fastapi import Depends

from azents.core.enums import EventKind
from azents.engine.context.compaction import compute_summary_budget
from azents.engine.context.window import compute_auto_compaction_threshold_tokens
from azents.engine.events.external_channel_rendering import (
    external_channel_message_visible_value,
    render_external_channel_message,
)
from azents.engine.events.protocols import (
    ManualCompactor,
    NativeRequestInspection,
    PostLowerFilter,
    SummaryEnricher,
    SummaryGenerator,
)
from azents.engine.events.provider_tool_rendering import render_provider_tool_semantic
from azents.engine.events.system_reminders import (
    format_compaction_summary_reminder,
    format_external_channel_continuation_reminder,
    format_goal_continuation_reminder,
    format_goal_resumed_reminder,
    format_goal_updated_reminder,
    format_interrupted_reminder,
    format_plain_system_reminder,
)
from azents.engine.events.types import (
    ArtifactOutputPart,
    AssistantMessagePayload,
    AttachmentOutputPart,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionSummaryPayload,
    Event,
    ExternalChannelMessagePayload,
    FileOutputPart,
    InputTextPart,
    InterruptedPayload,
    OutputContentPart,
    OutputTextPart,
    ProviderToolCallPayload,
    ScheduledTaskContinuationPayload,
    ScheduledTaskResultPayload,
    ScheduledTaskTriggerPayload,
    SystemReminderPayload,
    ToolOutput,
    ToolOutputPart,
    TurnMarkerPayload,
    UserContentPart,
    UserMessagePayload,
)
from azents.engine.run.errors import (
    CompactionFailedError,
    CompactionPlanStaleError,
    NativeRequestSizeExceededError,
)
from azents.repos.compaction_operation import (
    CompactionCommitContext,
    CompactionOperationRepository,
    get_compaction_operation_repository,
)

logger = logging.getLogger(__name__)

_TOKEN_BYTES = 4
_CONTINUITY_RECENT_TURNS = 5
_CONTINUITY_RECENT_USER_MESSAGES = 5
_CONTINUITY_MAX_EVENT_TOKENS = 2_000
_CONTINUITY_MAX_EVENT_CHARS = _CONTINUITY_MAX_EVENT_TOKENS * _TOKEN_BYTES
_CONTINUITY_TRUNCATION_MARKER = "\n\n[Event truncated by Azents continuity guard.]"
_PLAINTEXT_CUSTOM_INPUT_OMITTED = "[plaintext custom input omitted]"


class EventAutoCompactionFilter:
    """Decide compaction from provider usage and following delta estimate."""

    def __init__(
        self,
        *,
        session_id: str,
        compactor: ManualCompactor,
        summarize: SummaryGenerator,
        max_input_tokens: int | Callable[[], int],
        auto_compaction_threshold_tokens: int | None,
        compaction_id_factory: Callable[[], str],
        on_compaction_started: Callable[[], Awaitable[None]] | None = None,
        summary_enricher: SummaryEnricher | None = None,
        commit_context: CompactionCommitContext | None = None,
    ) -> None:
        self._session_id = session_id
        self.compactor = compactor
        self.summarize = summarize
        self._max_input_tokens = max_input_tokens
        initial_max_input_tokens = (
            max_input_tokens
            if isinstance(max_input_tokens, int)
            else max_input_tokens()
        )
        self._threshold_tokens = (
            auto_compaction_threshold_tokens
            if auto_compaction_threshold_tokens is not None
            else compute_auto_compaction_threshold_tokens(initial_max_input_tokens)
        )
        self.compaction_id_factory = compaction_id_factory
        self.on_compaction_started = on_compaction_started
        self.summary_enricher = summary_enricher
        self.commit_context = commit_context
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
        return await self.force_compact(
            events,
            reason="auto_threshold_exceeded",
            on_started=on_started,
        )

    async def force_compact(
        self,
        transcript: Sequence[Event],
        *,
        reason: str,
        on_started: Callable[[], Awaitable[None]] | None,
    ) -> list[Event]:
        """Use the ordinary compactor without the automatic token threshold."""
        self.was_compacted = False
        events = list(transcript)

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
            reason=reason,
            summary_enricher=self.summary_enricher,
            commit_context=self.commit_context,
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
        actual_chars = request.native_request_input_chars()
        if actual_chars > self._max_input_chars:
            raise NativeRequestSizeExceededError(
                actual_chars=actual_chars,
                limit_chars=self._max_input_chars,
            )
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

    operation_repository: Annotated[
        CompactionOperationRepository,
        Depends(get_compaction_operation_repository),
    ]
    summary_context_window_tokens: int | None = None

    def with_operations(
        self, operations: CompactionOperationRepository
    ) -> "EventCompactor":
        """Return an execution-local compactor without changing shared state."""
        return dataclasses.replace(
            self,
            operation_repository=operations,
        )

    async def compact(
        self,
        *,
        session_id: str,
        transcript: Sequence[Event],
        compaction_id: str,
        summarize: SummaryGenerator,
        on_started: Callable[[], Awaitable[None]] | None = None,
        summary_context_window_tokens: int | Callable[[], int] | None = None,
        reason: str | None = None,
        summary_enricher: SummaryEnricher | None = None,
        commit_context: CompactionCommitContext | None = None,
    ) -> Event | None:
        """Append one successful summary and commit related state atomically."""
        old_events = list(transcript)
        if not old_events:
            return None

        plan = await self.operation_repository.prepare(session_id=session_id)
        expected_tail_event_id = old_events[-1].id

        if on_started is not None:
            await on_started()

        if summary_context_window_tokens is None or isinstance(
            summary_context_window_tokens,
            int,
        ):
            resolved_context_window_tokens = summary_context_window_tokens
        else:
            resolved_context_window_tokens = summary_context_window_tokens()
        summary_budget = compute_summary_budget(
            resolved_context_window_tokens or self.summary_context_window_tokens
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
        summary_event = await self.operation_repository.finalize(
            session_id=session_id,
            plan=plan,
            expected_tail_event_id=expected_tail_event_id,
            compaction_id=compaction_id,
            content=summary_with_continuity,
            reason=reason,
            commit_context=commit_context,
        )
        if summary_event is None:
            raise CompactionPlanStaleError(
                "Compaction plan no longer matches the model-input boundaries."
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
    if isinstance(part, ArtifactOutputPart):
        return _format_visible_metadata(
            "Artifact",
            name=part.name,
            media_type=part.media_type,
            status=part.status,
        )
    assert_never(part)


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
    if isinstance(part, ArtifactOutputPart):
        return {
            "type": "artifact",
            "name": part.name,
            "media_type": part.media_type,
            "status": part.status,
        }
    assert_never(part)


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


def _continuity_tool_call_arguments(payload: ClientToolCallPayload) -> str:
    """Return safe arguments for a compaction continuity tool-call excerpt."""
    if payload.wire_dialect == "plaintext_custom":
        return _PLAINTEXT_CUSTOM_INPUT_OMITTED
    return payload.arguments


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
        for event in _select_recent_user_input_events(
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


def _select_recent_user_input_events(
    events: Sequence[Event], max_messages: int
) -> list[Event]:
    """Return the last direct user-input events from the selected transcript."""
    if max_messages <= 0:
        return []
    selected = [
        event
        for event in events
        if (
            event.kind == EventKind.USER_MESSAGE
            and isinstance(event.payload, UserMessagePayload)
        )
        or (
            event.kind == EventKind.EXTERNAL_CHANNEL_MESSAGE
            and isinstance(event.payload, ExternalChannelMessagePayload)
            and event.payload.prompt_role == "invocation"
        )
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
    if isinstance(payload, ExternalChannelMessagePayload):
        return external_channel_message_visible_value(payload)
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
    if event.kind == EventKind.EXTERNAL_CHANNEL_CONTINUATION and isinstance(
        payload,
        UserMessagePayload,
    ):
        return {
            "role": "user",
            "content": format_external_channel_continuation_reminder(payload.metadata),
        }
    if isinstance(
        payload,
        ScheduledTaskTriggerPayload | ScheduledTaskContinuationPayload,
    ):
        return {"role": "user", "content": payload.content}
    if isinstance(payload, ScheduledTaskResultPayload):
        return {
            "role": "assistant",
            "content": (
                f"Scheduled Task: {payload.title}\n"
                f"Status: {payload.status}\n"
                f"Result: {payload.result}"
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
        if payload.wire_dialect == "plaintext_custom":
            return {
                "type": "custom_tool_call",
                "call_id": payload.call_id,
                "name": payload.name,
                "input": _PLAINTEXT_CUSTOM_INPUT_OMITTED,
            }
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
    if isinstance(payload, ExternalChannelMessagePayload):
        return render_external_channel_message(payload, include_label=include_label)
    if event.kind == EventKind.GOAL_CONTINUATION and isinstance(
        payload,
        UserMessagePayload,
    ):
        return _format_continuity_block(
            "User",
            format_goal_continuation_reminder(payload.metadata.get("goal_objective")),
            include_label=include_label,
        )
    if event.kind == EventKind.EXTERNAL_CHANNEL_CONTINUATION and isinstance(
        payload,
        UserMessagePayload,
    ):
        return _format_continuity_block(
            "User",
            format_external_channel_continuation_reminder(payload.metadata),
            include_label=include_label,
        )
    if isinstance(
        payload,
        ScheduledTaskTriggerPayload | ScheduledTaskContinuationPayload,
    ):
        return _format_continuity_block(
            "User",
            payload.content,
            include_label=include_label,
        )
    if isinstance(payload, ScheduledTaskResultPayload):
        return _format_continuity_block(
            "Assistant",
            f"Scheduled Task: {payload.title}\n"
            f"Status: {payload.status}\n"
            f"Result: {payload.result}",
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
                arguments=_continuity_tool_call_arguments(payload),
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
