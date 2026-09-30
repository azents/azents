"""Runtime lifecycle invalidation boundary for active Terminals."""

from typing import Annotated

from azcommon import di
from fastapi import Depends

from azents.runtime import deps as runtime_deps
from azents.services.runtime_terminal.invalidation_contracts import (
    RuntimeTerminalInvalidationPublisher,
)


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


async def get_runtime_terminal_invalidation_publisher(
    container: Annotated[di.Container, Depends(di.get_container)],
    publisher: Annotated[
        RuntimeTerminalInvalidationPublisher,
        Depends(runtime_deps.get_runtime_terminal_invalidation_publisher),
    ],
) -> RuntimeTerminalInvalidationPublisher:
    """Return the publisher composed by the request's ordinary dependency graph."""
    binding = container.dependency_overrides.get(
        get_runtime_terminal_invalidation_publisher
    )
    if binding is None or binding is get_runtime_terminal_invalidation_publisher:
        raise RuntimeError("Runtime Terminal invalidation binding is missing.")
    return publisher


RuntimeTerminalInvalidationPublisherDependency = Annotated[
    RuntimeTerminalInvalidationPublisher,
    Depends(get_runtime_terminal_invalidation_publisher),
]
