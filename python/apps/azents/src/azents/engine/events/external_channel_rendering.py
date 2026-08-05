"""Shared model-visible rendering for External Channel messages."""

from collections.abc import Sequence

from azents.core.external_channel_file import (
    MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH,
    MAX_EXTERNAL_CHANNEL_FILES,
    ExternalChannelFileLocator,
    external_channel_file_metadata_items,
)
from azents.core.external_channel_projection import is_external_channel_projection
from azents.core.external_channel_reference import (
    render_provider_reference_mappings,
)
from azents.engine.events.types import ExternalChannelMessagePayload


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
        "projection_root_id": payload.projection_root_id,
        "provider_position": payload.provider_position,
        "sender": {
            "principal_id": payload.principal_id,
            "provider_user_id": payload.provider_user_id,
            "display_name": payload.sender_display_name,
            "author_type": payload.author_type.value,
        },
        "authorization": payload.authorization,
        "timestamp": timestamp.isoformat() if timestamp is not None else None,
        "body": _body(payload),
    }
    visible_attachments = _visible_attachment_metadata(payload.attachment_metadata)
    if visible_attachments:
        value["attachments"] = visible_attachments
    if payload.original_url is not None:
        value["original_url"] = payload.original_url
    if payload.reference_mappings:
        value["reference_mappings"] = payload.reference_mappings
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
    ]
    if timestamp is not None:
        lines.append(f"Timestamp: {timestamp.isoformat()}")
    if payload.truncated_context_message_count or payload.truncated_context_size:
        lines.append(
            "Truncated context: "
            f"{payload.truncated_context_message_count} messages, "
            f"{payload.truncated_context_size} bytes"
        )
    lines.extend(["Body:", _body(payload)])
    lines.extend(_render_file_lines(payload.attachment_metadata))
    lines.extend(_render_embed_lines(payload.attachment_metadata))
    mappings = _identity_mapping_lines((payload,))
    if mappings:
        lines.extend(["", *mappings])
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
            ]
        )
        if timestamp is not None:
            lines.append(f"   Timestamp: {timestamp.isoformat()}")
        lines.append(f"   Body: {_body(payload)}")
        lines.extend(_render_file_lines(payload.attachment_metadata, indent="   "))
        lines.extend(_render_embed_lines(payload.attachment_metadata, indent="   "))
    mappings = _identity_mapping_lines(payloads)
    if mappings:
        lines.extend(["", *mappings])
    return "\n".join(lines)


def _body(payload: ExternalChannelMessagePayload) -> str:
    """Return explicit bounded body text for one accepted history snapshot."""
    if payload.body is None or not payload.body.strip():
        return "[Message has no text content.]"
    return payload.body


def _identity_mapping_lines(
    payloads: Sequence[ExternalChannelMessagePayload],
) -> list[str]:
    """Render bounded provider identities as one concise XML appendix."""
    users: dict[str, str] = {}
    channels: dict[str, str] = {}
    for payload in payloads:
        users.update(payload.reference_mappings.get("users", {}))
        channels.update(payload.reference_mappings.get("channels", {}))
        if (
            payload.provider_user_id is not None
            and payload.sender_display_name is not None
        ):
            users[payload.provider_user_id] = payload.sender_display_name
    if not users and not channels:
        return []
    return list(
        render_provider_reference_mappings(
            users=users,
            channels=channels,
        )
    )


def _visible_attachment_metadata(
    attachment_metadata: dict[str, object],
) -> dict[str, object]:
    """Return only bounded decision-useful attachment fields."""
    visible: dict[str, object] = {}
    blocks = attachment_metadata.get("blocks")
    if is_external_channel_projection(blocks):
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
    embeds = _visible_embed_metadata(attachment_metadata)
    if embeds:
        visible["embeds"] = embeds
        visible["embeds_truncated"] = (
            attachment_metadata.get("embeds_truncated") is True
        )
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


def _visible_embed_metadata(
    attachment_metadata: dict[str, object],
) -> list[dict[str, object]]:
    """Return only safe, bounded text and media-presence embed fields."""
    raw_embeds = attachment_metadata.get("embeds")
    if not isinstance(raw_embeds, list):
        return []
    visible_embeds: list[dict[str, object]] = []
    for raw_embed in raw_embeds[:10]:
        if not is_external_channel_projection(raw_embed):
            continue
        embed: dict[str, object] = {}
        for key in ("type", "title", "description", "author_name", "footer_text"):
            value = _optional_inline_text(raw_embed.get(key))
            if value is not None:
                embed[key] = value
        raw_fields = raw_embed.get("fields")
        if isinstance(raw_fields, list):
            fields: list[dict[str, object]] = []
            for raw_field in raw_fields[:25]:
                if not is_external_channel_projection(raw_field):
                    continue
                field: dict[str, object] = {}
                for key in ("name", "value"):
                    value = _optional_inline_text(raw_field.get(key))
                    if value is not None:
                        field[key] = value
                if raw_field.get("inline") is True:
                    field["inline"] = True
                if field:
                    fields.append(field)
            if fields:
                embed["fields"] = fields
                if raw_embed.get("fields_truncated") is True:
                    embed["fields_truncated"] = True
        for key in ("has_image", "has_thumbnail"):
            if raw_embed.get(key) is True:
                embed[key] = True
        if embed:
            visible_embeds.append(embed)
    return visible_embeds


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
        if not is_external_channel_projection(item):
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


def _render_embed_lines(
    attachment_metadata: dict[str, object],
    *,
    indent: str = "",
) -> list[str]:
    """Render the safe structured embed projection used by model-visible values."""
    visible = _visible_attachment_metadata(attachment_metadata)
    embeds = visible.get("embeds")
    if not isinstance(embeds, list) or not embeds:
        return []
    lines = [f"{indent}Embeds:"]
    for index, raw_embed in enumerate(embeds, start=1):
        if not is_external_channel_projection(raw_embed):
            continue
        lines.append(f"{indent}{index}.")
        for key, label in (
            ("type", "Type"),
            ("title", "Title"),
            ("description", "Description"),
            ("author_name", "Author"),
            ("footer_text", "Footer"),
        ):
            value = raw_embed.get(key)
            if isinstance(value, str):
                lines.append(f"{indent}   {label}: {value}")
        if raw_embed.get("has_image") is True:
            lines.append(f"{indent}   Image: present")
        if raw_embed.get("has_thumbnail") is True:
            lines.append(f"{indent}   Thumbnail: present")
        fields = raw_embed.get("fields")
        if isinstance(fields, list):
            lines.append(f"{indent}   Fields:")
            for field_index, raw_field in enumerate(fields, start=1):
                if not is_external_channel_projection(raw_field):
                    continue
                name = raw_field.get("name") or "[unnamed]"
                value = raw_field.get("value") or "[empty]"
                suffix = " (inline)" if raw_field.get("inline") is True else ""
                lines.append(f"{indent}   {field_index}. {name}: {value}{suffix}")
            if raw_embed.get("fields_truncated") is True:
                lines.append(f"{indent}   [Additional fields omitted.]")
    if visible.get("embeds_truncated") is True:
        lines.append(
            f"{indent}[Additional embeds omitted by the provider metadata limit.]"
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
