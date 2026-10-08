"""Expected Toolkit domain failures shared by persistence and product contracts."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class NotFound:
    """Toolkit not found."""

    toolkit_id: str


@dataclasses.dataclass(frozen=True)
class AgentToolkitNotFound:
    """Agent Toolkit attachment not found."""

    agent_toolkit_id: str


@dataclasses.dataclass(frozen=True)
class DuplicateAgentToolkit:
    """Same Toolkit is already mounted on agent."""

    agent_id: str
    toolkit_id: str
