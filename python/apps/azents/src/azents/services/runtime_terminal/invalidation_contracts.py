"""Runtime lifecycle invalidation contracts shared by ports and adapters."""

from typing import Protocol


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
