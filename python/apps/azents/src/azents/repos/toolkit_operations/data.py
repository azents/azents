"""Toolkit operation repository data."""

import dataclasses

from azents.core.system_setting import SystemSettingFieldSource
from azents.repos.mcp_oauth_connection.data import MCPOAuthConnectionSummary
from azents.repos.toolkit.data import ToolkitConfig


@dataclasses.dataclass(frozen=True)
class ToolkitWithOAuth:
    """Detached Toolkit and its current public MCP OAuth summary."""

    toolkit: ToolkitConfig
    oauth_connection: MCPOAuthConnectionSummary | None


@dataclasses.dataclass(frozen=True)
class PlatformToolkitAuthority:
    """Exact Platform GitHub authority prepared outside a DB transaction."""

    app_id: str
    app_id_source: SystemSettingFieldSource
    user_id: str
    installation_ids: frozenset[int]


@dataclasses.dataclass(frozen=True)
class ToolkitWorkspaceMismatch:
    """Toolkit does not belong to the requested Workspace."""

    toolkit_id: str


@dataclasses.dataclass(frozen=True)
class ScopeToolkitMismatch:
    """Scope does not belong to the requested Toolkit."""

    scope_id: str


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceMismatch:
    """Agent does not belong to the requested Workspace."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class AgentToolkitMismatch:
    """Agent Toolkit does not belong to the requested Agent."""

    agent_toolkit_id: str


@dataclasses.dataclass(frozen=True)
class ToolkitUnavailable:
    """Toolkit is not currently available to the requesting Workspace user."""

    toolkit_id: str


@dataclasses.dataclass(frozen=True)
class PlatformAuthorityRejected:
    """Prepared Platform GitHub authority is no longer current."""

    detail: str
