"""Helpers for extracting ModelFile references from typed events."""

from collections.abc import Iterable, Sequence

from azents.core.enums import EventKind
from azents.engine.events.output_parts import iter_output_parts
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolResultPayload,
    Event,
    FileOutputPart,
    ProviderToolResultPayload,
    UserMessagePayload,
)


def iter_model_file_ids(events: Sequence[Event]) -> Iterable[str]:
    """Yield ModelFile IDs from typed Event payloads in transcript order."""
    for event in events:
        for part in file_parts(event):
            yield part.model_file_id


def unique_model_file_ids(events: Sequence[Event]) -> list[str]:
    """Return order-preserving unique ModelFile IDs from Events."""
    return list(dict.fromkeys(iter_model_file_ids(events)))


def file_parts(event: Event) -> list[FileOutputPart]:
    """Extract FileOutputPart references from one Event."""
    payload = event.payload
    if event.kind == EventKind.USER_MESSAGE and isinstance(payload, UserMessagePayload):
        if isinstance(payload.content, str):
            return []
        return [part for part in payload.content if isinstance(part, FileOutputPart)]
    if event.kind == EventKind.ASSISTANT_MESSAGE and isinstance(
        payload, AssistantMessagePayload
    ):
        if isinstance(payload.content, str):
            return []
        return [part for part in payload.content if isinstance(part, FileOutputPart)]
    if isinstance(payload, ClientToolResultPayload | ProviderToolResultPayload):
        return [
            part
            for part in iter_output_parts(payload.output)
            if isinstance(part, FileOutputPart)
        ]
    return []
