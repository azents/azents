"""Terminal policy source invalidation boundary."""

import dataclasses
import enum
from typing import Annotated, Protocol

from fastapi import Depends


class TerminalPolicySourceScope(enum.StrEnum):
    """Durable policy source that can revoke active Terminals."""

    INFRASTRUCTURE_PROFILE = "infrastructure_profile"
    WORKSPACE_PROFILE = "workspace_profile"
    AGENT = "agent"


@dataclasses.dataclass(frozen=True)
class TerminalPolicySourceInvalidation:
    """Content-free exact policy source invalidation."""

    scope: TerminalPolicySourceScope
    source_id: str
    source_version: str


class TerminalPolicyInvalidationPublisher(Protocol):
    """Publish committed policy-source changes to volatile coordination."""

    async def publish_terminal_policy_invalidation(
        self,
        invalidation: TerminalPolicySourceInvalidation,
    ) -> None:
        """Publish one committed source version without Terminal content."""
        ...


class NoopTerminalPolicyInvalidationPublisher:
    """Default boundary until Runtime Terminal coordination is activated."""

    async def publish_terminal_policy_invalidation(
        self,
        invalidation: TerminalPolicySourceInvalidation,
    ) -> None:
        """Accept one source invalidation without external side effects."""
        del invalidation


def get_terminal_policy_invalidation_publisher() -> TerminalPolicyInvalidationPublisher:
    """Return the default policy invalidation publisher dependency."""
    return NoopTerminalPolicyInvalidationPublisher()


TerminalPolicyInvalidationPublisherDependency = Annotated[
    TerminalPolicyInvalidationPublisher,
    Depends(get_terminal_policy_invalidation_publisher),
]
