"""Runtime lifecycle invalidation boundary for active Terminals."""

from typing import Annotated, Protocol

from fastapi import Depends


class RuntimeTerminalInvalidationPublisher(Protocol):
    """Publish committed durable authority invalidations."""

    async def publish_runtime_terminal_invalidation(self, runtime_id: str) -> None:
        """Invalidate active Terminals owned by one Runtime."""
        ...

    async def publish_user_terminal_invalidation(self, user_id: str) -> None:
        """Invalidate active Terminals after one User loses access."""
        ...

    async def publish_authentication_session_terminal_invalidation(
        self,
        authentication_session_id: str,
    ) -> None:
        """Invalidate active Terminals after one authentication Session is revoked."""
        ...

    async def publish_agent_session_terminal_invalidation(
        self,
        agent_session_id: str,
    ) -> None:
        """Invalidate active Terminals after one Agent Session loses access."""
        ...


class NoopRuntimeTerminalInvalidationPublisher:
    """Default boundary until Terminal coordination is activated."""

    async def publish_runtime_terminal_invalidation(self, runtime_id: str) -> None:
        """Accept one Runtime invalidation without external side effects."""
        del runtime_id

    async def publish_user_terminal_invalidation(self, user_id: str) -> None:
        """Accept one User invalidation without external side effects."""
        del user_id

    async def publish_authentication_session_terminal_invalidation(
        self,
        authentication_session_id: str,
    ) -> None:
        """Accept one authentication Session invalidation."""
        del authentication_session_id

    async def publish_agent_session_terminal_invalidation(
        self,
        agent_session_id: str,
    ) -> None:
        """Accept one Agent Session invalidation."""
        del agent_session_id


def get_runtime_terminal_invalidation_publisher() -> (
    RuntimeTerminalInvalidationPublisher
):
    """Return the default Runtime Terminal invalidation publisher."""
    return NoopRuntimeTerminalInvalidationPublisher()


RuntimeTerminalInvalidationPublisherDependency = Annotated[
    RuntimeTerminalInvalidationPublisher,
    Depends(get_runtime_terminal_invalidation_publisher),
]
