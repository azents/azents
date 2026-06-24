"""Credential type definitions by MCP server.

Secrets are stored encrypted at Toolkit level in the encrypted_credentials column.
"""

import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Secrets, encrypted storage at Toolkit level
# ---------------------------------------------------------------------------


class McpSecretsNone(BaseModel):
    """No authentication required."""

    type: Literal["none"] = "none"


class McpSecretsHeader(BaseModel):
    """Header-based authentication."""

    type: Literal["header"] = "header"
    value: str = Field(description="Header value")


class McpSecretsBearer(BaseModel):
    """Bearer token authentication."""

    type: Literal["bearer"] = "bearer"
    token: str = Field(description="Bearer token")


class McpSecretsOAuth2(BaseModel):
    """OAuth2 client credentials before token issuance."""

    type: Literal["oauth2"] = "oauth2"
    client_id: str = Field(description="OAuth2 Client ID")
    client_secret: str = Field(description="OAuth2 Client Secret")


class McpSecretsOAuth2Token(BaseModel):
    """OAuth2 client credentials plus issued token."""

    type: Literal["oauth2_token"] = "oauth2_token"
    client_id: str = Field(description="OAuth2 Client ID")
    client_secret: str = Field(description="OAuth2 Client Secret")
    access_token: str = Field(description="Access Token")
    refresh_token: str | None = Field(default=None, description="Refresh Token")
    expires_at: datetime.datetime | None = Field(
        default=None, description="Token expiration time"
    )


class McpSecretsOAuth2Dcr(BaseModel):
    """OAuth2 client info auto-registered with DCR (Dynamic Client Registration)."""

    type: Literal["oauth2_dcr"] = "oauth2_dcr"
    client_id: str = Field(description="Client ID issued by DCR")
    client_secret: str = Field(description="Client Secret issued by DCR")
    registration_endpoint: str = Field(
        description="Endpoint where the client was registered"
    )


McpSecrets = Annotated[
    McpSecretsNone
    | McpSecretsHeader
    | McpSecretsBearer
    | McpSecretsOAuth2
    | McpSecretsOAuth2Token
    | McpSecretsOAuth2Dcr,
    Field(discriminator="type"),
]
