"""Agent automatic Project policy service data."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class AgentAutomaticProjectPolicyNotFound:
    """Agent automatic Project policy setting is missing."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class AutomaticSessionProjectsRevisionConflict:
    """Submitted policy revision no longer matches the stored revision."""

    expected_revision: int


@dataclasses.dataclass(frozen=True)
class AutomaticSessionProjectsRuntimeUnavailable:
    """A non-empty policy cannot be validated through the current Runtime."""

    message: str
