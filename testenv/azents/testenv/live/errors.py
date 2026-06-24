"""Live helper exceptions.

Callers can import specific exceptions with
`from testenv.live.errors import ChatTimeout, ChatConnectionError`.
"""


class ChatError(Exception):
    """Base exception for live.chat helpers."""


class ChatConnectionError(ChatError):
    """WebSocket connection/handshake failure.

    Raised when the devserver is not reachable or the handshake fails. The message
    should usually point users to `uv run devserver.py status`.
    """


class ChatTimeout(ChatError):
    """Raised when the requested `until` event does not arrive before timeout.

    `collected_events` keeps the events seen so far so callers can inspect what
    happened before the timeout.
    """

    def __init__(self, message: str, *, collected_events: list[dict[str, object]]) -> None:
        super().__init__(message)
        self.collected_events = collected_events
