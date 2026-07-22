"""Shared model-visible rendering for External Channel messages."""

from collections.abc import Sequence

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
    if payload.attachment_metadata:
        value["attachments"] = payload.attachment_metadata
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
    return "\n".join(lines)


def _body(payload: ExternalChannelMessagePayload) -> str:
    """Return explicit bounded body text for current, edited, or deleted state."""
    if payload.lifecycle.value == "deleted":
        return "[Message deleted by provider.]"
    if payload.body is None or not payload.body.strip():
        return "[Message has no text content.]"
    return payload.body
