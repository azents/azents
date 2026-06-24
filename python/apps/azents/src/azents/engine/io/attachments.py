"""Runtime/tool attachment types.

The types in this module are dedicated to the runtime/tool boundary. Chat REST/WS
transport history projections use the `azents.services.chat.transport` types,
and durable transcripts use the `azents.engine.events.types` types.
"""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class RuntimeAttachment(BaseModel):
    """File reference snapshot for the runtime/tool output boundary."""

    model_config = ConfigDict(frozen=True)

    attachment_id: str | None = None
    uri: str
    media_type: str
    size: int
    name: str
    text_preview: str | None
    preview_thumbnail_uri: str | None = None
    availability: Literal["available", "expired", "unavailable"] = "available"
    preview_title: str | None = None
    preview_thumbnail_media_type: str | None = None
    preview_thumbnail_width: int | None = None
    preview_thumbnail_height: int | None = None
    preview_generated_at: datetime.datetime | None = None
