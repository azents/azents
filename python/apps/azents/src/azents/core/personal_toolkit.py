"""Exact authenticated personal Toolkit management context."""

import dataclasses

from azents.core.toolkit_ownership import PersonalToolkitAccessMode


class PersonalToolkitNotFound(ValueError):
    """The exact owner has no current personal Toolkit target."""


class PersonalToolkitAccessConflict(ValueError):
    """The saved policy mode differs from the editor's prepared assumption."""


class PersonalToolkitAgentIneligible(ValueError):
    """A mutation targets an Agent the owner cannot currently access."""


@dataclasses.dataclass(frozen=True, slots=True)
class PersonalToolkitAccessMutation:
    """Explicit mode intent and membership deltas, never a filtered replacement."""

    toolkit_id: str
    mode: PersonalToolkitAccessMode | None
    allow_agent_ids: frozenset[str]
    restrict_agent_ids: frozenset[str]
    expected_mode: PersonalToolkitAccessMode

    def __post_init__(self) -> None:
        if self.allow_agent_ids & self.restrict_agent_ids:
            raise ValueError("An Agent cannot be both allowed and restricted")
        if self.mode is PersonalToolkitAccessMode.ALL and (
            self.allow_agent_ids or self.restrict_agent_ids
        ):
            raise ValueError("Allow all cannot be combined with membership deltas")


@dataclasses.dataclass(frozen=True, slots=True)
class PersonalToolkitManager:
    """Canonical account and Auth Session, never supplied by a management payload."""

    user_id: str
    session_id: str
    workspace_id: str


class PersonalToolkitAuthorityDenied(ValueError):
    """The exact management User/Auth Session no longer has active authority."""


class PersonalToolkitConfigurationConflict(ValueError):
    """The source changed while configuration was prepared outside the transaction."""


class PersonalToolkitProviderAuthorityDenied(ValueError):
    """Current Provider registration or installation authority rejected persistence."""
