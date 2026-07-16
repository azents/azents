"""Broker type definitions."""

import dataclasses
from typing import Literal, Protocol

from azents.core.enums import AgentRunPhase
from azents.engine.run.emit import PublishedEvent


@dataclasses.dataclass(frozen=True)
class SessionActivity:
    """Current execution state of a session."""

    run_id: str
    phase: AgentRunPhase | None = None


@dataclasses.dataclass(frozen=True)
class WebInterfaceContext:
    """Web platform context."""

    type: Literal["web"] = "web"


InterfaceContext = WebInterfaceContext


@dataclasses.dataclass(frozen=True)
class SessionWakeUp:
    """Broker envelope that wakes the session runner."""

    agent_id: str
    session_id: str
    user_id: str | None
    additional_system_prompt: str | None
    interface: InterfaceContext | None
    workspace_id: str | None
    workspace_handle: str | None
    type: Literal["session_wake_up"] = "session_wake_up"


@dataclasses.dataclass(frozen=True)
class SessionStopSignal:
    """Fast-path signal that immediately notifies the session runner to stop."""

    session_id: str
    user_id: str | None = None
    type: Literal["session_stop_signal"] = "session_stop_signal"


BrokerMessage = SessionWakeUp | SessionStopSignal


class SessionBroker(Protocol):
    """Session message broker."""

    # Interface side
    async def send_message(self, message: BrokerMessage) -> None:
        """Send a message to the engine."""
        ...

    # Engine side
    async def receive_messages(self) -> list[BrokerMessage]:
        """Receive messages, blocking.

        After receiving a signal, drain all messages in that session queue and
        return them.
        """
        ...

    async def publish_event(self, session_id: str, event: PublishedEvent) -> None:
        """Publish a session event."""
        ...

    async def renew_session_ttl(self, session_id: str) -> None:
        """Refresh owner lock, owner heartbeat, and activity TTLs."""
        ...

    async def renew_session_owner_heartbeat(self, session_id: str) -> None:
        """Refresh session owner heartbeat TTL."""
        ...

    async def release_session_lock(self, session_id: str) -> None:
        """Release session lock."""
        ...

    # Activity tracking
    async def set_session_activity(
        self,
        session_id: str,
        *,
        run_id: str,
        phase: AgentRunPhase | None = None,
    ) -> None:
        """Record that a session is being processed with automatic TTL refresh."""
        ...

    async def clear_session_activity(self, session_id: str) -> None:
        """Remove activity when session processing completes or errors."""
        ...

    async def get_session_activity(self, session_id: str) -> SessionActivity | None:
        """Get the current execution state of a session."""
        ...
