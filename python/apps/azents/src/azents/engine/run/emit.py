"""Emit pattern type definitions and event handling.

Unified event publish instructions yielded by Engine.
- ephemeral: adapter delivery only (ContentDelta, RunStarted, etc.)
- durable: adapter delivery after event transcript append
"""

import dataclasses
from collections.abc import Awaitable, Callable
from typing import Literal, TypeAlias

from azents.engine.events.engine_events import EngineEvent
from azents.engine.events.provider_tool_rendering import render_provider_tool_semantic
from azents.engine.events.types import (
    ArtifactOutputPart,
    AssistantMessagePayload,
    AttachmentOutputPart,
    ClientToolResultPayload,
    Event,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolResultPayload,
    SystemErrorPayload,
)
from azents.engine.events.types import (
    Attachment as EventAttachment,
)
from azents.engine.io.attachments import RuntimeAttachment

PublishedDurableEvent: TypeAlias = Event
PublishedEvent: TypeAlias = EngineEvent | PublishedDurableEvent
EphemeralEvent: TypeAlias = EngineEvent | Event

# ---------------------------------------------------------------------------
# Emit types
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class EphemeralEmit:
    """Ephemeral event publish instruction yielded by Engine.

    Only delivered to adapter and not stored in DB.
    """

    event: EphemeralEvent
    mode: Literal["ephemeral"] = "ephemeral"


@dataclasses.dataclass(frozen=True)
class DurableEmit:
    """Durable event publish instruction yielded by Engine.

    Stored in DB, then delivered to adapter.
    """

    event: PublishedDurableEvent
    mode: Literal["durable"] = "durable"


Emit: TypeAlias = EphemeralEmit | DurableEmit


# ---------------------------------------------------------------------------
# Convenience factory functions
# ---------------------------------------------------------------------------


def ephemeral(event: EphemeralEvent) -> Emit:
    """Adapter delivery only. No DB storage.

    For transient events such as ContentDelta, RunStarted, and stream-only Event.
    """
    return EphemeralEmit(event=event)


def durable(event: PublishedDurableEvent) -> Emit:
    """Deliver to adapter after Event transcript append."""
    return DurableEmit(event=event)


# ---------------------------------------------------------------------------
# Common event handling functions
# ---------------------------------------------------------------------------


async def handle_engine_event(
    item: Emit,
    *,
    publish: Callable[[PublishedEvent], Awaitable[None]],
) -> None:
    """Publish one engine event.

    Durable events are delivered by event runtime after transcript append.
    Workers use this function to apply publish logic.

    :param item: Emit yielded by Engine
    :param publish: Event publish callback
    """
    await publish(item.event)


def collect_event_result(
    ev: object,
    texts: list[str],
    attachments: list[RuntimeAttachment],
) -> None:
    """Collect result text/attachments from event.

    Used to collect assistant output from emitted events.

    :param ev: Event to handle
    :param texts: Accumulated result text list
    :param attachments: Accumulated result attachment list
    """
    if isinstance(ev, Event):
        _collect_event_result(ev, texts, attachments)
        return


def _collect_event_result(
    ev: Event,
    texts: list[str],
    attachments: list[RuntimeAttachment],
) -> None:
    """Collect assistant text result from Event."""
    payload = ev.payload
    if isinstance(payload, AssistantMessagePayload):
        _append_event_text(payload.content, texts)
        attachments.extend(_runtime_attachments_from_event(payload.attachments))
        attachments.extend(_runtime_attachments_from_output(payload.content))
        return
    if isinstance(payload, ClientToolResultPayload):
        _append_event_text(payload.output, texts)
        attachments.extend(_runtime_attachments_from_event(payload.attachments))
        attachments.extend(_runtime_attachments_from_output(payload.output))
        return
    if isinstance(payload, ProviderToolCallPayload | ProviderToolResultPayload):
        texts.append(render_provider_tool_semantic(payload))
        attachments.extend(_runtime_attachments_from_event(payload.attachments))
        attachments.extend(_runtime_attachments_from_output(payload.semantic.output))
        return
    if isinstance(payload, SystemErrorPayload) and payload.content:
        texts.append(payload.content)


def _append_event_text(content: object, texts: list[str]) -> None:
    """Collect only text from Event content/output part."""
    if isinstance(content, str):
        if content:
            texts.append(content)
        return
    if not isinstance(content, list):
        return
    content_texts = [
        part.text for part in content if isinstance(part, OutputTextPart) and part.text
    ]
    if content_texts:
        texts.append("\n".join(content_texts))


def _runtime_attachments_from_event(
    attachments: list[EventAttachment],
) -> list[RuntimeAttachment]:
    """Convert Event attachment snapshot to runtime attachment."""
    converted: list[RuntimeAttachment] = []
    for attachment in attachments:
        converted.append(
            RuntimeAttachment(
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
        )
    return converted


def _runtime_attachments_from_output(content: object) -> list[RuntimeAttachment]:
    """Convert attachment/artifact delivery info from Event output part."""
    if not isinstance(content, list):
        return []
    converted: list[RuntimeAttachment] = []
    for part in content:
        if isinstance(part, AttachmentOutputPart):
            converted.append(
                RuntimeAttachment(
                    attachment_id=part.attachment_id,
                    uri=part.uri,
                    media_type=part.media_type,
                    size=part.size,
                    name=part.name,
                    text_preview=part.preview_summary,
                    preview_thumbnail_uri=part.preview_thumbnail_uri,
                    availability=part.availability,
                    preview_title=part.preview_title,
                    preview_thumbnail_media_type=part.preview_thumbnail_media_type,
                    preview_thumbnail_width=part.preview_thumbnail_width,
                    preview_thumbnail_height=part.preview_thumbnail_height,
                    preview_generated_at=part.preview_generated_at,
                )
            )
        elif isinstance(part, ArtifactOutputPart):
            converted.append(
                RuntimeAttachment(
                    uri=part.uri,
                    media_type=part.media_type,
                    size=part.size,
                    name=part.name,
                    text_preview=None,
                    preview_thumbnail_uri=None,
                )
            )
    return converted
