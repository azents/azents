"""Detached Agent Toolkit authority and OAuth persistence values."""

import dataclasses
import datetime

from azents.repos.mcp_oauth_connection.data import MCPOAuthConnection
from azents.repos.toolkit.data import AgentToolkit, ToolkitConfig


@dataclasses.dataclass(frozen=True)
class AgentManagementSnapshot:
    """Authorized detached data for the service's management projection."""

    attachments: list[AgentToolkit]
    shared: list[ToolkitConfig]
    owned: list[ToolkitConfig]
    available: list[ToolkitConfig]


@dataclasses.dataclass(frozen=True)
class AgentManagementDenied:
    """Requester lacks current Agent management authority."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class AgentOAuthContext:
    """Authorized Agent-owned Toolkit and its detached OAuth connection."""

    toolkit: ToolkitConfig
    connection: MCPOAuthConnection | None


@dataclasses.dataclass(frozen=True)
class OAuthConnectionWrite:
    """OAuth values ready for encrypted repository persistence."""

    issuer: str | None
    resource: str | None
    server_url: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    client_id: str
    client_secret: str | None
    token_endpoint_auth_method: str
    scope: str | None
    access_token: str | None
    refresh_token: str | None
    expires_at: datetime.datetime | None
