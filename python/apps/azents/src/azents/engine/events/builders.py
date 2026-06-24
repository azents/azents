"""Event creation helpers."""

import datetime
from typing import Literal

from azcommon.uuid import uuid7

from azents.core.enums import EventKind
from azents.engine.events.types import (
    Event,
    SubagentEndPayload,
    SubagentStartPayload,
    SystemErrorPayload,
)


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


def make_subagent_start_event(
    *,
    session_id: str,
    subagent_run_id: str,
    subagent_id: str,
    subagent_name: str,
    subagent_session_id: str,
) -> Event:
    """Create Subagent start event."""
    return Event(
        id=uuid7().hex,
        session_id=session_id,
        kind=EventKind.SUBAGENT_START,
        payload=SubagentStartPayload(
            subagent_run_id=subagent_run_id,
            subagent_id=subagent_id,
            subagent_name=subagent_name,
            subagent_session_id=subagent_session_id,
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )


def make_subagent_end_event(
    *,
    session_id: str,
    subagent_run_id: str,
    subagent_id: str,
    subagent_session_id: str,
    status: Literal["completed", "failed", "interrupted"],
    result: str | None = None,
    error: str | None = None,
) -> Event:
    """Create Subagent end event."""
    return Event(
        id=uuid7().hex,
        session_id=session_id,
        kind=EventKind.SUBAGENT_END,
        payload=SubagentEndPayload(
            subagent_run_id=subagent_run_id,
            subagent_id=subagent_id,
            subagent_session_id=subagent_session_id,
            status=status,
            result=result,
            error=error,
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )
