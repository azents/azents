"""Terminal policy source invalidation boundary."""

from typing import Annotated

from azcommon import di
from fastapi import Depends

from azents.runtime import deps as runtime_deps
from azents.services.terminal_policy.invalidation_contracts import (
    TerminalPolicyInvalidationPublisher,
    TerminalPolicySourceInvalidation,
    TerminalPolicySourceScope,
)

__all__ = [
    "NoopTerminalPolicyInvalidationPublisher",
    "TerminalPolicyInvalidationPublisher",
    "TerminalPolicyInvalidationPublisherDependency",
    "TerminalPolicySourceInvalidation",
    "TerminalPolicySourceScope",
    "get_terminal_policy_invalidation_publisher",
]


class NoopTerminalPolicyInvalidationPublisher:
    """Default boundary until Runtime Terminal coordination is activated."""

    async def publish_terminal_policy_invalidation(
        self,
        invalidation: TerminalPolicySourceInvalidation,
    ) -> None:
        """Accept one source invalidation without external side effects."""
        del invalidation


async def get_terminal_policy_invalidation_publisher(
    container: Annotated[di.Container, Depends(di.get_container)],
    publisher: Annotated[
        TerminalPolicyInvalidationPublisher,
        Depends(runtime_deps.get_runtime_terminal_policy_invalidation_publisher),
    ],
) -> TerminalPolicyInvalidationPublisher:
    """Return the publisher composed by the request's ordinary dependency graph."""
    binding = container.dependency_overrides.get(
        get_terminal_policy_invalidation_publisher
    )
    if binding is None or binding is get_terminal_policy_invalidation_publisher:
        raise RuntimeError("Terminal policy invalidation binding is missing.")
    return publisher


TerminalPolicyInvalidationPublisherDependency = Annotated[
    TerminalPolicyInvalidationPublisher,
    Depends(get_terminal_policy_invalidation_publisher),
]
