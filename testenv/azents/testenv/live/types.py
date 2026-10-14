"""Shared live helper types.

`chat.start_session` returns a `Session`, which is then passed to `collect` and
`stream` helpers.
"""

from dataclasses import dataclass

from testenv.seed.types import Agent, User


@dataclass(frozen=True)
class Session:
    """Live chat session value object for server-side state.

    `start_session` resolves the team primary session through REST. `collect`
    and `stream` open a confirmed WebSocket subscription before committing input.
    """

    id: str
    user: User
    agent: Agent
    public_url: str
