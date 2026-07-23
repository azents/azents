"""Shared model-visible rendering for External Channel messages."""

import re
from collections.abc import Sequence

from azents.core.external_channel_file import (
    MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH,
    MAX_EXTERNAL_CHANNEL_FILES,
    ExternalChannelFileLocator,
    external_channel_file_metadata_items,
)
from azents.engine.events.types import ExternalChannelMessagePayload

_SLACK_VISIBLE_REFERENCE = re.compile(
    r"<@(?P<user_angle>[A-Z0-9]+)(?:\|[^>]+)?>"
    r"|(?<![A-Za-z0-9])@(?P<user_raw>[UW][A-Z0-9]+)\b"
    r"|<#(?P<channel_angle>[A-Z0-9]+)(?:\|[^>]+)?>"
    r"|(?<![A-Za-z0-9])#(?P<channel_raw>[CG][A-Z0-9]+)\b"
)


def external_channel_message_visible_value(
    payload: ExternalChannelMessagePayload,
) -> dict[str, object]:
    """Return a deterministic structured model-visible message value."""
    timestamp = payload.provider_updated_at or payload.provider_created_at
    value: dict[str, object] = {
        "message_type": "external_channel_message",
        "provider": payload.provider.value,
        "provider_tenant_id": payload.provider_tenant_id,
        "resource": {
            "id": payload.resource_id,
            "label": payload.resource_label,
            "type": payload.resource_type.value,
        },
        "binding_id": payload.binding_id,
        "invocation_batch_id": payload.invocation_batch_id,
        "external_message_id": payload.external_message_id,
        "revision_id": payload.revision_id,
        "revision_kind": payload.revision_kind.value,
        "projection_root_id": payload.projection_root_id,
        "provider_position": payload.provider_position,
        "sender": {
            "principal_id": payload.principal_id,
            "provider_user_id": payload.provider_user_id,
            "display_name": payload.sender_display_name,
            "author_type": payload.author_type.value,
        },
        "authorization": payload.authorization,
        "lifecycle": payload.lifecycle.value,
        "timestamp": timestamp.isoformat() if timestamp is not None else None,
        "body": _body(payload),
    }
    visible_attachments = _visible_attachment_metadata(payload.attachment_metadata)
    if visible_attachments:
        value["attachments"] = visible_attachments
    if payload.original_url is not None:
        value["original_url"] = payload.original_url
    if payload.correction_of_revision_id is not None:
        value["correction_of_revision_id"] = payload.correction_of_revision_id
    if payload.truncated_context_message_count or payload.truncated_context_size:
        value["truncated_context"] = {
            "message_count": payload.truncated_context_message_count,
            "size": payload.truncated_context_size,
        }
    return value


def render_external_channel_message(
    payload: ExternalChannelMessagePayload,
    *,
    include_label: bool = True,
) -> str:
    """Render one bounded source-labeled external message for model input."""
    sender = payload.sender_display_name or payload.provider_user_id or "unknown"
    timestamp = payload.provider_updated_at or payload.provider_created_at
    lines = [
        f"Provider: {payload.provider.value}",
        f"Resource: {payload.resource_label}",
        f"Sender: {sender} ({payload.author_type.value})",
        f"Authorization: {payload.authorization}",
        f"Lifecycle: {payload.lifecycle.value}",
    ]
    if timestamp is not None:
        lines.append(f"Timestamp: {timestamp.isoformat()}")
    if payload.revision_kind.value != "original":
        lines.append(f"Revision: {payload.revision_kind.value}")
    if payload.correction_of_revision_id is not None:
        lines.append(f"Correction of revision: {payload.correction_of_revision_id}")
    if payload.truncated_context_message_count or payload.truncated_context_size:
        lines.append(
            "Truncated context: "
            f"{payload.truncated_context_message_count} messages, "
            f"{payload.truncated_context_size} bytes"
        )
    lines.extend(["Body:", _body(payload)])
    lines.extend(_render_file_lines(payload.attachment_metadata))
    body = "\n".join(lines)
    return f"External Channel Message:\n{body}" if include_label else body


def render_external_channel_turn(
    payloads: Sequence[ExternalChannelMessagePayload],
) -> str:
    """Render one contiguous invocation batch as an explicit external turn."""
    if not payloads:
        return ""
    first = payloads[0]
    lines = [
        "Message Type: EXTERNAL_CHANNEL_TURN",
        f"Provider: {first.provider.value}",
        f"Resource: {first.resource_label}",
        f"Binding: {first.binding_id}",
    ]
    if first.truncated_context_message_count or first.truncated_context_size:
        lines.append(
            "Truncated Context: "
            f"{first.truncated_context_message_count} messages, "
            f"{first.truncated_context_size} bytes"
        )
    lines.append("")
    for index, payload in enumerate(payloads, start=1):
        sender = payload.sender_display_name or payload.provider_user_id or "unknown"
        timestamp = payload.provider_updated_at or payload.provider_created_at
        lines.extend(
            [
                f"{index}. Sender: {sender}",
                f"   Author Type: {payload.author_type.value}",
                f"   Authorization: {payload.authorization}",
                f"   Lifecycle: {payload.lifecycle.value}",
            ]
        )
        if timestamp is not None:
            lines.append(f"   Timestamp: {timestamp.isoformat()}")
        if payload.revision_kind.value != "original":
            lines.append(f"   Revision: {payload.revision_kind.value}")
        if payload.correction_of_revision_id is not None:
            lines.append(
                f"   Correction of revision: {payload.correction_of_revision_id}"
            )
        lines.append(f"   Body: {_body(payload)}")
        lines.extend(_render_file_lines(payload.attachment_metadata, indent="   "))
    return "\n".join(lines)


def _body(payload: ExternalChannelMessagePayload) -> str:
    """Return explicit bounded body text for current, edited, or deleted state."""
    if payload.lifecycle.value == "deleted":
        return "[Message deleted by provider.]"
    if payload.body is None or not payload.body.strip():
        return "[Message has no text content.]"
    return _display_body(payload.body, payload.reference_mappings)


def _display_body(
    body: str,
    mappings: dict[str, dict[str, str]],
) -> str:
    """Resolve provider references only in the visible body projection."""
    user_mappings = mappings.get("users", {})
    channel_mappings = mappings.get("channels", {})

    def replace(match: re.Match[str]) -> str:
        user_id = match.group("user_angle") or match.group("user_raw")
        if user_id is not None:
            display_name = user_mappings.get(user_id)
            if display_name is None:
                return match.group(0)
            return display_name if display_name.startswith("@") else f"@{display_name}"
        channel_id = match.group("channel_angle") or match.group("channel_raw")
        if channel_id is None:
            return match.group(0)
        display_name = channel_mappings.get(channel_id)
        if display_name is None:
            return match.group(0)
        return display_name if display_name.startswith("#") else f"#{display_name}"

    return _SLACK_VISIBLE_REFERENCE.sub(replace, body)


def _visible_attachment_metadata(
    attachment_metadata: dict[str, object],
) -> dict[str, object]:
    """Return only bounded decision-useful attachment fields."""
    visible: dict[str, object] = {}
    blocks = attachment_metadata.get("blocks")
    if isinstance(blocks, dict):
        visible_blocks = _visible_block_metadata(blocks)
        if visible_blocks:
            visible["blocks"] = visible_blocks
    else:
        visible_blocks = _visible_block_metadata(attachment_metadata)
        if visible_blocks:
            visible.update(visible_blocks)

    files = [
        _visible_file_metadata(item)
        for item in external_channel_file_metadata_items(attachment_metadata)[
            :MAX_EXTERNAL_CHANNEL_FILES
        ]
    ]
    if files:
        visible["files"] = files
        visible["files_truncated"] = attachment_metadata.get("files_truncated") is True
    return visible


def _visible_block_metadata(metadata: dict[str, object]) -> dict[str, object]:
    """Return the existing bounded Block Kit summary fields."""
    visible: dict[str, object] = {}
    block_count = metadata.get("block_count")
    if isinstance(block_count, int) and not isinstance(block_count, bool):
        visible["block_count"] = max(block_count, 0)
    block_types = metadata.get("block_types")
    if isinstance(block_types, list):
        visible["block_types"] = [
            _inline_text(value)
            for value in block_types
            if isinstance(value, str) and value
        ][:32]
    if isinstance(metadata.get("truncated"), bool):
        visible["truncated"] = metadata["truncated"]
    return visible


def _visible_file_metadata(metadata: dict[str, object]) -> dict[str, object]:
    """Return one provider-neutral file entry without provider-private fields."""
    declared_size = metadata.get("declared_size")
    supported = metadata.get("supported") is True
    visible: dict[str, object] = {
        "name": _optional_inline_text(metadata.get("name")),
        "title": _optional_inline_text(metadata.get("title")),
        "media_type": _optional_inline_text(metadata.get("media_type")),
        "declared_size": (
            declared_size
            if isinstance(declared_size, int)
            and not isinstance(declared_size, bool)
            and declared_size >= 0
            else None
        ),
        "supported": supported,
        "unsupported_reason": (
            None
            if supported
            else _optional_inline_text(metadata.get("unsupported_reason"))
        ),
    }
    locator = metadata.get("file")
    if isinstance(locator, str):
        try:
            parsed_locator = ExternalChannelFileLocator.parse(locator)
        except ValueError:
            pass
        else:
            if parsed_locator.encode() == locator:
                visible["file"] = locator
    return visible


def _render_file_lines(
    attachment_metadata: dict[str, object],
    *,
    indent: str = "",
) -> list[str]:
    """Render the same safe file semantics used by structured visibility."""
    visible = _visible_attachment_metadata(attachment_metadata)
    files = visible.get("files")
    if not isinstance(files, list) or not files:
        return []
    lines = [f"{indent}Files:"]
    for index, item in enumerate(files, start=1):
        if not isinstance(item, dict):
            continue
        name = item.get("name") or "[unnamed]"
        title = item.get("title") or "[untitled]"
        media_type = item.get("media_type") or "unknown"
        declared_size = item.get("declared_size")
        size = f"{declared_size} bytes" if isinstance(declared_size, int) else "unknown"
        status = (
            "supported"
            if item.get("supported") is True
            else f"unsupported ({item.get('unsupported_reason') or 'unknown_reason'})"
        )
        lines.extend(
            [
                f"{indent}{index}. Name: {name}",
                f"{indent}   Title: {title}",
                f"{indent}   Media type: {media_type}",
                f"{indent}   Declared size: {size}",
                f"{indent}   Status: {status}",
            ]
        )
        locator = item.get("file")
        if isinstance(locator, str):
            lines.append(f"{indent}   File: {locator}")
    if visible.get("files_truncated") is True:
        lines.append(
            f"{indent}[Additional files omitted by the provider metadata limit.]"
        )
    return lines


def _optional_inline_text(value: object) -> str | None:
    """Return one bounded single-line metadata value."""
    if not isinstance(value, str) or not value:
        return None
    return _inline_text(value)


def _inline_text(value: str) -> str:
    """Normalize provider metadata for deterministic single-line rendering."""
    normalized = " ".join(value.split())
    return normalized[:MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH]
