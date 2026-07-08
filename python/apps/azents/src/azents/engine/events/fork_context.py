"""Utilities for preparing forked model-visible context."""

import dataclasses
import re
from collections.abc import Sequence
from typing import Literal, assert_never

from azents.core.enums import EventKind
from azents.engine.events.output_parts import iter_output_parts
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolResultPayload,
    Event,
    FileOutputPart,
    InputTextPart,
    OutputTextPart,
    ProviderToolResultPayload,
    ToolOutput,
    ToolOutputPart,
    UserContentPart,
    UserMessagePayload,
)

_FORK_TURNS_PATTERN = re.compile(r"^[1-9][0-9]*$")


class InvalidForkTurns(ValueError):
    """Raised when a fork_turns value is not valid."""


@dataclasses.dataclass(frozen=True)
class ForkTurnsSelection:
    """Parsed fork_turns selection."""

    mode: Literal["none", "all", "latest"]
    count: int | None


def parse_fork_turns(value: str) -> ForkTurnsSelection:
    """Parse spawn_agent fork_turns syntax.

    :param value: Raw fork_turns value. Accepted values are ``none``, ``all``,
        or a positive integer string.
    :return: Parsed selection
    :raises InvalidForkTurns: if value is malformed
    """
    normalized = value
    if normalized == "none":
        return ForkTurnsSelection(mode="none", count=None)
    if normalized == "all":
        return ForkTurnsSelection(mode="all", count=None)
    if _FORK_TURNS_PATTERN.fullmatch(normalized):
        return ForkTurnsSelection(mode="latest", count=int(normalized))
    raise InvalidForkTurns(
        "fork_turns must be 'none', 'all', or a positive integer string"
    )


def select_fork_events(
    events: Sequence[Event],
    selection: ForkTurnsSelection,
    *,
    head_event_id: str | None,
) -> list[Event]:
    """Select forked transcript context from the current model-input range.

    The returned events never include durable history before ``head_event_id``.
    Positive integer selections choose the latest N turns within that bounded
    range, using ``turn_marker`` events as completed-turn boundaries.
    """
    visible_events = _events_from_head(events, head_event_id=head_event_id)
    match selection.mode:
        case "none":
            return []
        case "all":
            return list(visible_events)
        case "latest":
            if selection.count is None:
                raise InvalidForkTurns("latest fork_turns count is missing")
            return _select_recent_turn_events(visible_events, selection.count)
        case _:
            assert_never(selection.mode)


def degrade_file_parts_for_fork(events: Sequence[Event]) -> list[Event]:
    """Replace FileParts with text placeholders for forked context.

    The fork helper intentionally does not copy object-storage blobs, does not
    create child ModelFiles, and does not share ModelFile rows. FilePart metadata
    is rendered as bounded text so the child can ask for an explicit handoff when
    it needs file bytes.
    """
    return [_degrade_event_file_parts(event) for event in events]


def _events_from_head(
    events: Sequence[Event], *, head_event_id: str | None
) -> list[Event]:
    ordered = sorted(events, key=lambda event: (event.model_order, event.id))
    if head_event_id is None:
        return ordered
    head_event = next((event for event in ordered if event.id == head_event_id), None)
    if head_event is None:
        raise ValueError("head_event_id is not present in transcript")
    return [event for event in ordered if event.model_order >= head_event.model_order]


def _select_recent_turn_events(events: Sequence[Event], max_turns: int) -> list[Event]:
    if max_turns <= 0:
        return []
    turn_marker_indexes = [
        index
        for index, event in enumerate(events)
        if event.kind == EventKind.TURN_MARKER
    ]
    if not turn_marker_indexes:
        return list(events)
    if len(turn_marker_indexes) <= max_turns:
        return list(events)
    start_index = turn_marker_indexes[-max_turns - 1] + 1
    return list(events[start_index:])


def _degrade_event_file_parts(event: Event) -> Event:
    payload = event.payload
    if isinstance(payload, UserMessagePayload):
        content = _degrade_user_content(event, payload.content)
        if content is payload.content:
            return event
        return event.model_copy(
            update={"payload": payload.model_copy(update={"content": content})}
        )
    if isinstance(payload, AssistantMessagePayload):
        content = _degrade_output_content(event, payload.content)
        if content is payload.content:
            return event
        return event.model_copy(
            update={"payload": payload.model_copy(update={"content": content})}
        )
    if isinstance(payload, ClientToolResultPayload | ProviderToolResultPayload):
        output = _degrade_tool_output(event, payload.output)
        if output is payload.output:
            return event
        return event.model_copy(
            update={"payload": payload.model_copy(update={"output": output})}
        )
    return event


def _degrade_user_content(
    event: Event,
    content: str | Sequence[UserContentPart],
) -> str | Sequence[UserContentPart]:
    if isinstance(content, str):
        return content
    changed = False
    degraded: list[UserContentPart] = []
    for part in content:
        if isinstance(part, FileOutputPart):
            degraded.append(InputTextPart(text=_fork_file_placeholder(event, part)))
            changed = True
        else:
            degraded.append(part)
    if not changed:
        return content
    return degraded


def _degrade_output_content(
    event: Event,
    content: str | Sequence[ToolOutputPart],
) -> str | Sequence[ToolOutputPart]:
    if isinstance(content, str):
        return content
    changed = False
    degraded: list[ToolOutputPart] = []
    for part in content:
        if isinstance(part, FileOutputPart):
            degraded.append(OutputTextPart(text=_fork_file_placeholder(event, part)))
            changed = True
        else:
            degraded.append(part)
    if not changed:
        return content
    return degraded


def _degrade_tool_output(event: Event, output: ToolOutput) -> ToolOutput:
    if isinstance(output, str):
        return output
    changed = False
    degraded: list[ToolOutputPart] = []
    for part in iter_output_parts(output):
        if isinstance(part, FileOutputPart):
            degraded.append(OutputTextPart(text=_fork_file_placeholder(event, part)))
            changed = True
        else:
            degraded.append(part)
    if not changed:
        return output
    return degraded


def _fork_file_placeholder(event: Event, part: FileOutputPart) -> str:
    lines = [
        "Forked file placeholder: file bytes were not copied into this child context.",
        f"Name: {part.name or part.model_file_id}",
        f"Media type: {part.media_type}",
        f"Model file ID: {part.model_file_id}",
        f"Source event: {event.kind.value} {event.id}",
    ]
    if part.size is not None:
        lines.insert(3, f"Size: {part.size} bytes")
    if part.kind:
        lines.append(f"Kind: {part.kind}")
    if part.caption:
        lines.append(f"Caption: {part.caption}")
    if part.alt_text:
        lines.append(f"Alt text: {part.alt_text}")
    lines.append(
        "Provide a runtime path or explicit file handoff if the child needs bytes."
    )
    return "\n".join(lines)
