"""Chat REST/WS transport projection types.

REST history and WebSocket projection belong to same chat transport layer,
so they share types from this module. Durable event transcript types use
`azents.engine.events.types`, and runtime/tool boundary types use
`azents.engine.io.attachments`.
"""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from azents.engine.events.types import Attachment as EventAttachment
from azents.engine.events.types import Event


class ChatAttachmentSnapshot(BaseModel):
    """Attachment snapshot displayed in Chat transport."""

    model_config = ConfigDict(frozen=True)

    attachment_id: str | None = None
    uri: str = Field(description="File-location URI")
    media_type: str = Field(description="MIME type")
    size: int = Field(description="File size (bytes)")
    name: str = Field(description="Display filename")
    text_preview: str | None = Field(default=None, description="Text preview")
    preview_thumbnail_uri: str | None = Field(
        default=None,
        description="Image preview thumbnail URI",
    )
    availability: Literal["available", "expired", "unavailable"] = "available"
    preview_title: str | None = None
    preview_thumbnail_media_type: str | None = None
    preview_thumbnail_width: int | None = None
    preview_thumbnail_height: int | None = None
    preview_generated_at: datetime.datetime | None = None


_ATTACHMENT_KEYS = {
    "attachment_id",
    "uri",
    "media_type",
    "size",
    "name",
    "text_preview",
    "preview_thumbnail_uri",
    "availability",
    "preview_title",
    "preview_thumbnail_media_type",
    "preview_thumbnail_width",
    "preview_thumbnail_height",
    "preview_generated_at",
}


def chat_attachment_from_event(
    attachment: EventAttachment,
) -> ChatAttachmentSnapshot:
    """Convert Event attachment to chat transport snapshot."""
    return ChatAttachmentSnapshot(
        attachment_id=attachment.attachment_id,
        uri=attachment.uri,
        media_type=attachment.media_type,
        size=attachment.size,
        name=attachment.name,
        text_preview=attachment.preview_summary,
        preview_thumbnail_uri=attachment.preview_thumbnail_uri,
        availability=attachment.availability,
        preview_title=attachment.preview_title,
        preview_thumbnail_media_type=attachment.preview_thumbnail_media_type,
        preview_thumbnail_width=attachment.preview_thumbnail_width,
        preview_thumbnail_height=attachment.preview_thumbnail_height,
        preview_generated_at=attachment.preview_generated_at,
    )


def chat_event_transport_dump(event: Event) -> dict[str, object]:
    """Convert Event to chat REST/WS transport wire dict."""
    dumped = event.model_dump(mode="json")
    payload = dumped.get("payload")
    if isinstance(payload, dict):
        _project_payload_attachments(payload)
    return dumped


def chat_history_event_appended_dump(event: Event) -> dict[str, object]:
    """Convert persisted history event append action to chat WS wire dict."""
    return {
        "type": "history_event_appended",
        "session_id": event.session_id,
        "event": chat_event_transport_dump(event),
    }


def chat_live_event_upserted_dump(event: Event) -> dict[str, object]:
    """Convert live event upsert action to chat WS wire dict."""
    return {
        "type": "live_event_upserted",
        "session_id": event.session_id,
        "event": chat_event_transport_dump(event),
    }


def chat_live_event_removed_dump(session_id: str, event_id: str) -> dict[str, object]:
    """Convert live event removal action to chat WS wire dict."""
    return {
        "type": "live_event_removed",
        "session_id": session_id,
        "event_id": event_id,
    }


def chat_input_actions_updated_dump(session_id: str) -> dict[str, object]:
    """Convert composer action list update notification to chat WS wire dict."""
    return {
        "type": "input_actions_updated",
        "session_id": session_id,
    }


def chat_subscription_ack_dump(session_id: str) -> dict[str, object]:
    """Convert Session subscription completion ack to chat WS wire dict."""
    return {
        "type": "subscribed",
        "session_id": session_id,
    }


def chat_subscription_health_check_ack_dump(
    session_id: str,
    request_id: str | None,
) -> dict[str, object]:
    """Convert Session subscription health check ack to chat WS wire dict."""
    payload: dict[str, object] = {
        "type": "subscription_health_check_ack",
        "session_id": session_id,
    }
    if request_id is not None:
        payload["request_id"] = request_id
    return payload


def _project_payload_attachments(payload: dict[str, object]) -> None:
    """Convert attachment list in Event payload to chat transport shape."""
    attachments = payload.get("attachments")
    if isinstance(attachments, list):
        payload["attachments"] = [
            _project_attachment_dict(item) for item in attachments
        ]

    for key in ("content", "output"):
        parts = payload.get(key)
        if isinstance(parts, list):
            payload[key] = [_project_content_part(part) for part in parts]


def _project_content_part(part: object) -> object:
    """Convert Attachment output part to chat transport attachment shape."""
    if not isinstance(part, dict):
        return part
    if part.get("type") != "attachment":
        return part
    projected = _project_attachment_dict(part, text_preview_key="preview_summary")
    if not isinstance(projected, dict):
        return projected
    projected["type"] = "attachment"
    return projected


def _project_attachment_dict(
    item: object,
    *,
    text_preview_key: str = "preview_summary",
) -> object:
    """Convert Event attachment dict to chat attachment dict."""
    if not isinstance(item, dict):
        return item
    text_preview = item.get(text_preview_key)
    projected = {key: value for key, value in item.items() if key in _ATTACHMENT_KEYS}
    if "text_preview" not in projected:
        projected["text_preview"] = text_preview
    return projected
