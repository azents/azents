"""Helpers for constructing event user_message payloads."""

import datetime
from collections.abc import Sequence

from azcommon.uuid import uuid7

from azents.core.inference_profile import RequestedInferenceProfile
from azents.engine.events.types import (
    Attachment as EventAttachment,
)
from azents.engine.events.types import (
    FileOutputPart,
    InputTextPart,
    UserContentPart,
    UserMessagePayload,
)
from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.io.user_input import RunUserMessage


def make_run_user_message(
    *,
    sender_user_id: str | None,
    content: str,
    metadata: dict[str, str],
    attachments: Sequence[RuntimeAttachment],
    file_parts: Sequence[FileOutputPart] = (),
    external_id: str,
    attachment_source: str,
    requested_inference_profile: RequestedInferenceProfile | None,
) -> RunUserMessage:
    """Convert a runtime input snapshot into an event run user message."""
    event_content: str | list[UserContentPart]
    if file_parts:
        event_content = []
        if content:
            event_content.append(InputTextPart(text=content))
        event_content.extend(file_parts)
    else:
        event_content = content
    return RunUserMessage(
        payload=UserMessagePayload(
            sender_user_id=sender_user_id,
            content=event_content,
            attachments=[
                event_attachment_from_runtime_attachment(
                    attachment,
                    source=attachment_source,
                )
                for attachment in attachments
            ],
            metadata=metadata,
            requested_inference_profile=requested_inference_profile,
        ),
        external_id=external_id,
    )


def event_attachment_from_runtime_attachment(
    attachment: RuntimeAttachment,
    *,
    source: str,
) -> EventAttachment:
    """Convert a runtime attachment snapshot into an event Attachment."""
    return EventAttachment(
        attachment_id=attachment.attachment_id or uuid7().hex,
        uri=attachment.uri,
        name=attachment.name,
        media_type=attachment.media_type,
        size=attachment.size,
        created_at=datetime.datetime.now(datetime.UTC),
        source=source,
        availability=attachment.availability,
        preview_title=attachment.preview_title,
        preview_summary=attachment.text_preview,
        preview_thumbnail_uri=attachment.preview_thumbnail_uri,
        preview_thumbnail_media_type=attachment.preview_thumbnail_media_type,
        preview_thumbnail_width=attachment.preview_thumbnail_width,
        preview_thumbnail_height=attachment.preview_thumbnail_height,
        preview_generated_at=attachment.preview_generated_at,
    )
