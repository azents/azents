"""Expected Toolkit domain failures shared by persistence and product contracts."""

import dataclasses

from azents.core.enums import ToolkitScopeType


@dataclasses.dataclass(frozen=True)
class NotFound:
    """Toolkit not found."""

    toolkit_id: str


@dataclasses.dataclass(frozen=True)
class ScopeNotFound:
    """ToolkitScope not found."""

    scope_id: str


@dataclasses.dataclass(frozen=True)
class DuplicateScope:
    """Same scope already exists."""

    toolkit_id: str
    scope_type: ToolkitScopeType
    scope_id: str


@dataclasses.dataclass(frozen=True)
class DuplicateAgentToolkit:
    """Same Toolkit is already mounted on agent."""

    agent_id: str
    toolkit_id: str
