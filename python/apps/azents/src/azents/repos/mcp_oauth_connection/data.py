"""MCP OAuth connection repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import MCPOAuthConnectionStatus


class MCPOAuthConnection(BaseModel):
    """MCP OAuth connection domain model."""

    id: str = Field(description="MCP OAuth connection ID")
    toolkit_id: str = Field(description="Toolkit ID")
    issuer: str | None = Field(default=None, description="OAuth issuer")
    resource: str | None = Field(default=None, description="OAuth resource")
    server_url: str = Field(description="MCP server URL")
    authorization_endpoint: str = Field(description="OAuth authorization endpoint")
    token_endpoint: str = Field(description="OAuth token endpoint")
    registration_endpoint: str | None = Field(
        default=None, description="OAuth DCR registration endpoint"
    )
    client_id: str = Field(description="Decrypted OAuth client ID")
    client_secret: str | None = Field(
        default=None, description="Decrypted OAuth client secret"
    )
    token_endpoint_auth_method: str = Field(description="Token endpoint auth method")
    scope: str | None = Field(default=None, description="OAuth scope string")
    access_token: str | None = Field(
        default=None, description="Decrypted OAuth access token"
    )
    refresh_token: str | None = Field(
        default=None, description="Decrypted OAuth refresh token"
    )
    expires_at: datetime.datetime | None = Field(
        default=None, description="Access token expiration timestamp"
    )
    status: MCPOAuthConnectionStatus = Field(description="Connection status")
    created_at: datetime.datetime = Field(description="Creation timestamp")
    updated_at: datetime.datetime = Field(description="Update timestamp")


class MCPOAuthConnectionSummary(BaseModel):
    """Public MCP OAuth connection summary."""

    status: MCPOAuthConnectionStatus = Field(description="Connection status")
    issuer: str | None = Field(default=None, description="OAuth issuer")
    resource: str | None = Field(default=None, description="OAuth resource")
    scope: str | None = Field(default=None, description="OAuth scope string")
    expires_at: datetime.datetime | None = Field(
        default=None, description="Access token expiration timestamp"
    )
