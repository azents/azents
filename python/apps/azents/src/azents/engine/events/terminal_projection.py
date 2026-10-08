"""Pure terminal assistant-text projection from committed Events."""

from collections.abc import Sequence
from dataclasses import dataclass

from azents.engine.events.types import (
    AssistantMessagePayload,
    Event,
    OutputTextPart,
)


@dataclass(frozen=True)
class TerminalEventResult:
    """User-safe terminal Event identity and assistant text."""

    event_id: str | None
    message: str | None


def terminal_result_from_events(events: Sequence[Event]) -> TerminalEventResult:
    """Project the latest nonblank assistant text from terminal Run Events."""
    for event in reversed(events):
        payload = event.payload
        if isinstance(payload, AssistantMessagePayload):
            text = assistant_content_text(payload.content)
            if text is not None:
                return TerminalEventResult(event_id=event.id, message=text)
    return TerminalEventResult(event_id=None, message=None)


def assistant_content_text(content: object) -> str | None:
    """Extract text from assistant content for terminal result projection."""
    if isinstance(content, str):
        stripped = content.strip()
        return stripped or None
    if isinstance(content, list):
        parts = [
            part.text.strip() for part in content if isinstance(part, OutputTextPart)
        ]
        text = "\n".join(part for part in parts if part)
        return text or None
    return None
