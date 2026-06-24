"""Shared live helper types.

`chat.start_session` returns a `Session`, which is then passed to `collect` and
`stream` helpers.
"""

from dataclasses import dataclass

from testenv.seed.types import Agent, User


@dataclass(frozen=True)
class Session:
    """Live chat session value object for server-side state.

    `start_session` performs the WebSocket handshake and init message, then
    returns this session object. The WebSocket itself is not kept open; `collect`
    and `stream` open their own connections for subsequent calls.
    """

    id: str
    user: User
    agent: Agent
    public_url: str
