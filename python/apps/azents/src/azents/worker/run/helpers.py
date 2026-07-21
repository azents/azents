"""Worker run helper functions."""

import asyncio

from azents.core.enums import AgentRunStatus
from azents.engine.events.types import (
    ActiveToolCall,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
)
from azents.engine.run.types import USER_STOP_CANCEL_MESSAGE


def apply_active_tool_call_event(
    active_tool_calls: list[ActiveToolCall],
    event: object,
    *,
    owner_generation: int,
) -> list[ActiveToolCall]:
    """Reflect event in running tool call list."""
    if isinstance(event, Event):
        payload = event.payload
        if isinstance(payload, ClientToolCallPayload):
            return [
                *(
                    tool_call
                    for tool_call in active_tool_calls
                    if tool_call.call_id != payload.call_id
                ),
                ActiveToolCall(
                    call_id=payload.call_id,
                    name=payload.name,
                    arguments=payload.arguments,
                    wire_dialect=payload.wire_dialect,
                    started_at=event.created_at,
                    owner_generation=owner_generation,
                ),
            ]
        if isinstance(payload, ClientToolResultPayload):
            return [
                tool_call
                for tool_call in active_tool_calls
                if tool_call.call_id != payload.call_id
            ]
        return active_tool_calls
    return active_tool_calls


def format_resolve_error(error: object) -> str:
    """Convert ResolveError to user message."""
    return str(error)


def user_stop_cancelled(exc: asyncio.CancelledError) -> bool:
    """Check whether CancelledError is user stop cancellation."""
    return bool(exc.args and exc.args[0] == USER_STOP_CANCEL_MESSAGE)


def observed_terminal_run_event(
    *,
    run_completed: bool,
    terminal_run_status: AgentRunStatus | None,
) -> bool:
    """Check whether Worker emitted terminal run event outward."""
    return run_completed or terminal_run_status == AgentRunStatus.STOPPED
