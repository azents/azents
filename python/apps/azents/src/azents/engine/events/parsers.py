"""Parser by SDK origin type: raw OAI dict to structured events.item dict.

Snapshot at write-time: convert once at emit time and persist in ``data`` column.
Call sites (UI / adapter) use normalized fields directly and do not re-parse raw.

Each parser is dispatched exactly once per type and is a pure function.
Normalized field names map 1:1 to Pydantic Item field names.
"""

from collections.abc import Callable
from typing import Any, TypedDict

from azents.core.enums import EventType


class AttachmentDict(TypedDict):
    """Attachment item stored in ``data`` column."""

    type: str
    url: str


class TextItemData(TypedDict):
    """``parse_text_item`` result data."""

    content: str
    attachments: list[AttachmentDict]


class ReasoningItemData(TypedDict):
    """``parse_reasoning_item`` result data."""

    reasoning: dict[str, Any]
    reasoning_text: str


class ToolCallItemData(TypedDict):
    """``parse_tool_call_item`` result data."""

    id: str | None
    call_id: str
    name: str
    arguments: str


class ToolCallOutputItemData(TypedDict):
    """``parse_tool_call_output_item`` result."""

    call_id: str
    output: dict[str, Any]


class ImageGenerationItemData(TypedDict):
    """``parse_image_generation_item`` result."""

    attachments: list[AttachmentDict]


class UnknownItemData(TypedDict):
    """``parse_unknown_item`` result: no additional Pydantic fields."""


ParsedData = (
    TextItemData
    | ReasoningItemData
    | ToolCallItemData
    | ToolCallOutputItemData
    | ImageGenerationItemData
    | UnknownItemData
)


def parse_text_item(raw: dict[str, Any]) -> TextItemData:
    """assistant message dict → :class:`TextItemData`.

    Combine ``output_text`` / ``text`` parts in ``content`` list into ``content``
    and convert ``image_url`` of ``input_image`` parts into attachments.
    """
    raw_content = raw.get("content", [])
    text_parts: list[str] = []
    attachments: list[AttachmentDict] = []
    if isinstance(raw_content, list):
        for part in raw_content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype in ("output_text", "text"):
                text = part.get("text", "")
                if isinstance(text, str):
                    text_parts.append(text)
            elif ptype == "input_image":
                url = part.get("image_url")
                if isinstance(url, str):
                    attachments.append(AttachmentDict(type="image", url=url))
    elif isinstance(raw_content, str):
        text_parts.append(raw_content)
    return TextItemData(
        content="\n".join(text_parts),
        attachments=attachments,
    )


def parse_reasoning_item(raw: dict[str, Any]) -> ReasoningItemData:
    """reasoning dict → :class:`ReasoningItemData`.

    Each ``summary`` item has ``{type, text}`` shape; combine only text into one
    string and preserve raw itself in ``reasoning``.
    """
    summary = raw.get("summary", [])
    text_parts: list[str] = []
    if isinstance(summary, list):
        for entry in summary:
            if isinstance(entry, dict):
                text = entry.get("text", "")
                if isinstance(text, str):
                    text_parts.append(text)
    return ReasoningItemData(
        reasoning=dict(raw),
        reasoning_text="\n".join(text_parts),
    )


def parse_tool_call_item(raw: dict[str, Any]) -> ToolCallItemData:
    """tool call dict → :class:`ToolCallItemData` (function / web_search / etc).

    Preserve raw ``id`` as ID for streaming partial merge, and preserve ``call_id``
    as ID for output pairing. Hosted tools without ``call_id`` use ``id`` as
    fallback.
    """
    call_id = raw.get("call_id") or raw.get("id") or ""
    item_id = raw.get("id") or call_id or ""
    name = raw.get("name") or raw.get("type") or ""
    arguments = raw.get("arguments") or ""
    return ToolCallItemData(
        id=item_id if isinstance(item_id, str) else None,
        call_id=call_id if isinstance(call_id, str) else "",
        name=name if isinstance(name, str) else "",
        arguments=arguments if isinstance(arguments, str) else "",
    )


def parse_tool_call_output_item(raw: dict[str, Any]) -> ToolCallOutputItemData:
    """tool call output dict → :class:`ToolCallOutputItemData`.

    When output is multipart list including images, separate text and attachments.
    Preserve plain string as-is.
    """
    output = raw.get("output", "")
    text_parts: list[str] = []
    attachments: list[AttachmentDict] = []
    if isinstance(output, list):
        for part in output:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype in ("output_text", "text"):
                text = part.get("text", "")
                if isinstance(text, str):
                    text_parts.append(text)
            elif ptype == "input_image":
                url = part.get("image_url")
                if isinstance(url, str):
                    attachments.append(AttachmentDict(type="image", url=url))
    elif isinstance(output, str):
        text_parts.append(output)
    call_id = raw.get("call_id", "")
    return ToolCallOutputItemData(
        call_id=call_id if isinstance(call_id, str) else "",
        output={
            "content": "\n".join(text_parts),
            "attachments": attachments,
            "images": [],
        },
    )


def parse_image_generation_item(raw: dict[str, Any]) -> ImageGenerationItemData:
    """image_generation_call dict → :class:`ImageGenerationItemData`.

    ``result`` field is large base64; emit pipeline (Phase 4+) owns file_storage
    upload and URI replacement. This parser assumes raw was already processed into
    _attachments key and only extracts that. Empty list when unprocessed.
    """
    raw_attachments = raw.get("_attachments", [])
    attachments: list[AttachmentDict] = []
    if isinstance(raw_attachments, list):
        for entry in raw_attachments:
            if not isinstance(entry, dict):
                continue
            atype = entry.get("type")
            url = entry.get("url")
            if isinstance(atype, str) and isinstance(url, str):
                attachments.append(AttachmentDict(type=atype, url=url))
    return ImageGenerationItemData(attachments=attachments)


def parse_unknown_item(raw: dict[str, Any]) -> UnknownItemData:
    """Unknown SDK sub-type: raw alone can round-trip. No additional data fields."""
    return UnknownItemData()


PARSERS: dict[EventType, Callable[[dict[str, Any]], ParsedData]] = {
    EventType.TEXT_ITEM: parse_text_item,
    EventType.REASONING_ITEM: parse_reasoning_item,
    EventType.TOOL_CALL_ITEM: parse_tool_call_item,
    EventType.TOOL_CALL_OUTPUT_ITEM: parse_tool_call_output_item,
    EventType.IMAGE_GENERATION_ITEM: parse_image_generation_item,
    EventType.UNKNOWN_ITEM: parse_unknown_item,
}
