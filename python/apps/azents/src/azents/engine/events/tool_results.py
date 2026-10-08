"""Pure terminal Tool-result payloads shared by execution and recovery."""

from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    OutputTextPart,
)


def cancelled_tool_result(call: ClientToolCallPayload) -> ClientToolResultPayload:
    """Build the generic cancelled Tool result without executing the Tool."""
    return ClientToolResultPayload(
        call_id=call.call_id,
        name=call.name,
        wire_dialect=call.wire_dialect,
        status="cancelled",
        output=[
            OutputTextPart(
                text="Tool execution was cancelled before a result was recorded."
            )
        ],
    )
