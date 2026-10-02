"""Pure availability projections for durable model-input Event payloads."""

import dataclasses
from collections.abc import Sequence
from typing import Literal

from azents.core.enums import ExchangeFileStatus, ModelFileStatus
from azents.engine.events.file_parts import file_output_part_placeholder_text
from azents.engine.events.output_parts import iter_output_parts
from azents.engine.events.types import (
    AssistantMessagePayload,
    Attachment,
    AttachmentOutputPart,
    ClientToolResultPayload,
    Event,
    EventPayload,
    FileOutputPart,
    InputTextPart,
    OutputContentPart,
    OutputTextPart,
    ProviderToolCallPayload,
    ToolOutputPart,
    UserContentPart,
    UserMessagePayload,
)

_EXCHANGE_URI_PREFIX = "exchange://"
AttachmentAvailability = Literal["available", "expired", "unavailable"]


@dataclasses.dataclass(frozen=True)
class _ChangedValue[T]:
    """Value returned by a transformation together with its change flag."""

    value: T
    changed: bool


def exchange_attachment_object_keys(events: Sequence[Event]) -> list[str]:
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


def refresh_attachment_availability(
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
        attachments = _refresh_attachment_list(payload.attachments, statuses)
        content = _refresh_output_attachment_parts(payload.content, statuses)
        if not attachments.changed and not content.changed:
            return None
        return payload.model_copy(
            update={"attachments": attachments.value, "content": content.value}
        )
    if isinstance(payload, ClientToolResultPayload):
        output = _refresh_tool_output_attachment_parts(payload.output, statuses)
        if not output.changed:
            return None
        return payload.model_copy(update={"output": output.value})
    if isinstance(payload, ProviderToolCallPayload):
        output = _refresh_tool_output_attachment_parts(
            payload.semantic.output, statuses
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


def model_file_ids(events: Sequence[Event]) -> list[str]:
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


def replace_unavailable_file_parts(
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
