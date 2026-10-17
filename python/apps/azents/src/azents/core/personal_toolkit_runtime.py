"""Narrow personal-source authority derived from durable User-root lineage."""

import dataclasses
import enum
from typing import Protocol

from azents.core.session_resource_authority import SessionExecutionOwner


class PersonalToolkitDenialReason(enum.StrEnum):
    """Expected admission failures, distinct from persistence failures."""

    ROOT_UNAVAILABLE = "root_unavailable"
    OWNER_UNAVAILABLE = "owner_unavailable"
    AGENT_ACCESS_DENIED = "agent_access_denied"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_CHANGED = "source_changed"
    PROVIDER_AUTHORIZATION_REQUIRED = "provider_authorization_required"


class PersonalToolkitExecutionDenied(Exception):
    """A source-specific personal effect has no current usable authority."""

    def __init__(self, reason: PersonalToolkitDenialReason) -> None:
        self.reason = reason
        super().__init__("Personal Toolkit authorization is unavailable.")


@dataclasses.dataclass(frozen=True)
class PersonalToolkitExecutionTarget:
    """Exact source capture; created only after canonical Session/owner admission."""

    execution_owner: SessionExecutionOwner
    workspace_id: str
    agent_id: str
    root_session_id: str
    owner_user_id: str
    toolkit_id: str
    source_revision: int


class ToolkitEffectAdmission(Protocol):
    """A source-bound capability, not an ambient execution User or Tool argument."""

    @property
    def target(self) -> PersonalToolkitExecutionTarget:
        """Return the exact target for repository-composed grant finalization."""
        ...

    async def assert_current(self) -> None:
        """Finish current database admission before a new protected external effect."""
        ...
