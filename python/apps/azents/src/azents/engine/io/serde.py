"""Attachment/FunctionToolCall/Usage serialization utilities.

Provides serialization/deserialization functions shared by multiple paths such as
DB JSONB storage, WS/Redis message delivery, and REST API conversion.
"""

import datetime
import json
import logging
from typing import Any

from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.run.types import FunctionToolCall, TokenUsage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Attachment
# ---------------------------------------------------------------------------


def serialize_attachment(a: RuntimeAttachment) -> dict[str, Any]:
    """Serialize RuntimeAttachment to dict."""
    d: dict[str, Any] = {
        "uri": a.uri,
        "media_type": a.media_type,
        "size": a.size,
    }
    if a.attachment_id is not None:
        d["attachment_id"] = a.attachment_id
    if a.name:
        d["name"] = a.name
    if a.text_preview is not None:
        d["text_preview"] = a.text_preview
    if a.preview_thumbnail_uri is not None:
        d["preview_thumbnail_uri"] = a.preview_thumbnail_uri
    if a.availability != "available":
        d["availability"] = a.availability
    if a.preview_title is not None:
        d["preview_title"] = a.preview_title
    if a.preview_thumbnail_media_type is not None:
        d["preview_thumbnail_media_type"] = a.preview_thumbnail_media_type
    if a.preview_thumbnail_width is not None:
        d["preview_thumbnail_width"] = a.preview_thumbnail_width
    if a.preview_thumbnail_height is not None:
        d["preview_thumbnail_height"] = a.preview_thumbnail_height
    if a.preview_generated_at is not None:
        d["preview_generated_at"] = a.preview_generated_at.isoformat()
    return d


def deserialize_attachment(d: dict[str, Any]) -> RuntimeAttachment:
    """Restore RuntimeAttachment from dict."""
    return RuntimeAttachment(
        attachment_id=d.get("attachment_id"),
        uri=d["uri"],
        media_type=d["media_type"],
        size=d["size"],
        name=d.get("name", ""),
        text_preview=d.get("text_preview"),
        preview_thumbnail_uri=d.get("preview_thumbnail_uri"),
        availability=d.get("availability", "available"),
        preview_title=d.get("preview_title"),
        preview_thumbnail_media_type=d.get("preview_thumbnail_media_type"),
        preview_thumbnail_width=d.get("preview_thumbnail_width"),
        preview_thumbnail_height=d.get("preview_thumbnail_height"),
        preview_generated_at=_datetime_from_iso(d.get("preview_generated_at")),
    )


def _datetime_from_iso(value: object) -> datetime.datetime | None:
    """Restore ISO datetime string to datetime."""
    if not isinstance(value, str):
        return None
    return datetime.datetime.fromisoformat(value)


def serialize_attachments(
    attachments: list[RuntimeAttachment],
) -> list[dict[str, Any]] | None:
    """Convert Attachment list to dict list for JSONB storage.

    Return None for empty list.
    """
    if not attachments:
        return None
    return [serialize_attachment(a) for a in attachments]


def deserialize_attachments(
    raw: list[dict[str, Any]] | None,
) -> list[RuntimeAttachment]:
    """Restore Attachment list from JSONB dict list.

    Return empty list when None.
    """
    if not raw:
        return []
    return [deserialize_attachment(a) for a in raw]


# ---------------------------------------------------------------------------
# FunctionToolCall
# ---------------------------------------------------------------------------


def serialize_tool_calls(
    tool_calls: list[FunctionToolCall],
) -> list[dict[str, str]] | None:
    """Convert FunctionToolCall list to dict list for JSONB storage.

    Return None for empty list.
    """
    if not tool_calls:
        return None
    return [
        {
            "id": tc.id,
            "name": tc.name,
            "arguments": tc.arguments,
            "wire_dialect": tc.wire_dialect,
        }
        for tc in tool_calls
    ]


def _sanitize_tool_call_arguments(arguments: str, *, tc_id: str) -> str:
    """Validate tool call arguments JSON and replace malformed value.

    A model can cut JSON in the middle when exceeding max output tokens.
    If such truncated JSON remains in conversation history, LiteLLM Bedrock
    conversion can raise ``JSONDecodeError`` and permanently stick the session.

    :param arguments: Tool call arguments JSON string
    :param tc_id: Tool call ID for logging
    :return: Valid JSON string, or ``"{}"`` when malformed
    """
    try:
        json.loads(arguments)
    except json.JSONDecodeError, ValueError:
        logger.warning(
            "Malformed tool call arguments sanitized",
            extra={"tool_call_id": tc_id, "raw_arguments": arguments[:200]},
        )
        return "{}"
    return arguments


def deserialize_tool_calls(
    raw: list[dict[str, Any]] | None,
) -> list[FunctionToolCall] | None:
    """Restore FunctionToolCall list from JSONB dict list.

    Return None when None.
    Malformed JSON arguments are replaced with empty object.
    """
    if raw is None:
        return None
    return [
        FunctionToolCall(
            id=tc["id"],
            name=tc["name"],
            arguments=_sanitize_tool_call_arguments(tc["arguments"], tc_id=tc["id"]),
            wire_dialect=tc.get("wire_dialect", "json_function"),
        )
        for tc in raw
    ]


# ---------------------------------------------------------------------------
# TokenUsage
# ---------------------------------------------------------------------------


def serialize_usage(usage: TokenUsage | None) -> dict[str, Any] | None:
    """Convert TokenUsage to dict for JSONB storage."""
    if usage is None:
        return None
    d: dict[str, Any] = {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }
    if usage.cached_tokens is not None:
        d["cached_tokens"] = usage.cached_tokens
    if usage.cache_creation_tokens is not None:
        d["cache_creation_tokens"] = usage.cache_creation_tokens
    if usage.reasoning_tokens is not None:
        d["reasoning_tokens"] = usage.reasoning_tokens
    if usage.cost_usd is not None:
        d["cost_usd"] = usage.cost_usd
    if usage.raw is not None:
        d["raw"] = usage.raw
    if usage.raw_hidden_params is not None:
        d["raw_hidden_params"] = usage.raw_hidden_params
    return d


def deserialize_usage(data: dict[str, Any] | None) -> TokenUsage | None:
    """Restore TokenUsage from JSONB dict."""
    if data is None:
        return None
    return TokenUsage(
        prompt_tokens=data["prompt_tokens"],
        completion_tokens=data["completion_tokens"],
        total_tokens=data["total_tokens"],
        cached_tokens=data.get("cached_tokens"),
        cache_creation_tokens=data.get("cache_creation_tokens"),
        reasoning_tokens=data.get("reasoning_tokens"),
        cost_usd=data.get("cost_usd"),
        raw=data.get("raw"),
        raw_hidden_params=data.get("raw_hidden_params"),
    )
