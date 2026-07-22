"""Per-call execution identity available to durable client tool handlers."""

import contextlib
import contextvars
import dataclasses
from collections.abc import Iterator


@dataclasses.dataclass(frozen=True)
class ClientToolExecutionContext:
    """Identity of the client tool call currently executing."""

    call_id: str
    name: str


_CURRENT_CLIENT_TOOL_CALL: contextvars.ContextVar[ClientToolExecutionContext | None] = (
    contextvars.ContextVar("current_client_tool_call", default=None)
)


@contextlib.contextmanager
def client_tool_execution_context(
    *,
    call_id: str,
    name: str,
) -> Iterator[None]:
    """Bind one client tool call identity for the duration of its handler."""
    token = _CURRENT_CLIENT_TOOL_CALL.set(
        ClientToolExecutionContext(call_id=call_id, name=name)
    )
    try:
        yield
    finally:
        _CURRENT_CLIENT_TOOL_CALL.reset(token)


def get_client_tool_execution_context() -> ClientToolExecutionContext:
    """Return the active client tool call identity."""
    context = _CURRENT_CLIENT_TOOL_CALL.get()
    if context is None:
        raise RuntimeError("Client tool execution context is unavailable.")
    return context
