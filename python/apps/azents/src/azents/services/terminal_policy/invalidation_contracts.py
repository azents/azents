"""Terminal policy invalidation contracts shared by ports and adapters."""

import dataclasses
import enum
from typing import Protocol


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
