"""ChatGPT OAuth session repository data models."""

import dataclasses
import datetime
from typing import Annotated

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from azents.core.chatgpt_oauth import (
    ChatGPTOAuthConnectionMethod,
    ChatGPTOAuthSessionStatus,
)


class ChatGPTOAuthSession(BaseModel):
    """ChatGPT OAuth session domain model."""

    id: str = Field(description="Session ID")
    workspace_id: str = Field(description="Workspace ID")
    user_id: str = Field(description="User ID")
    method: ChatGPTOAuthConnectionMethod = Field(description="Connection method")
    state: str = Field(description="OAuth state")
    redirect_uri: str = Field(description="Redirect URI")
    user_code: str | None = Field(default=None, description="Device user code")
    verification_uri: str | None = Field(
        default=None, description="Device verification URI"
    )
    interval_seconds: int | None = Field(default=None, description="Polling interval")
    status: ChatGPTOAuthSessionStatus = Field(description="Session status")
    expires_at: datetime.datetime = Field(description="Session expiration time")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class ChatGPTOAuthSessionWithSecrets(ChatGPTOAuthSession):
    """ChatGPT OAuth session including decrypted secret value."""

    code_verifier: str = Field(description="PKCE code verifier")
    device_auth_id: str | None = Field(default=None, description="Device auth ID")


class ChatGPTOAuthSessionCreate(BaseModel):
    """ChatGPT OAuth session create schema."""

    workspace_id: str = Field(description="Workspace ID")
    user_id: str = Field(description="User ID")
    method: ChatGPTOAuthConnectionMethod = Field(description="Connection method")
    state: str = Field(description="OAuth state")
    code_verifier: str = Field(description="PKCE code verifier")
    redirect_uri: str = Field(description="Redirect URI")
    expires_at: datetime.datetime = Field(description="Session expiration time")
    device_auth_id: str | None = Field(default=None, description="Device auth ID")
    user_code: str | None = Field(default=None, description="Device user code")
    verification_uri: str | None = Field(
        default=None, description="Device verification URI"
    )
    interval_seconds: int | None = Field(default=None, description="Polling interval")


class ChatGPTOAuthSessionUpdate(TypedDict, total=False):
    """ChatGPT OAuth session update schema."""

    status: Annotated[ChatGPTOAuthSessionStatus, Field(description="Session status")]


@dataclasses.dataclass(frozen=True)
class NotFound:
    """Session not found."""

    session_id: str
