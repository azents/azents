"""Event creation helpers."""

import datetime

from azcommon.uuid import uuid7

from azents.core.enums import EventKind
from azents.engine.events.types import Event, SystemErrorPayload


def make_system_error_event(
    *,
    session_id: str,
    content: str,
    recoverable: bool = True,
) -> Event:
    """Create event system_error event to display to the user."""
    return Event(
        id=uuid7().hex,
        session_id=session_id,
        kind=EventKind.SYSTEM_ERROR,
        payload=SystemErrorPayload(
            content=content,
            severity="error",
            recoverable=recoverable,
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )
