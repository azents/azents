"""Kimi OAuth session repository data models."""

import dataclasses
import datetime
from typing import Annotated

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from azents.core.kimi_oauth import (
    KimiOAuthConnectionMethod,
    KimiOAuthSessionStatus,
)


class KimiOAuthSession(BaseModel):
    """Kimi OAuth session domain model."""

    id: str = Field(description="Session ID")
    workspace_id: str = Field(description="Workspace ID")
    user_id: str = Field(description="User ID")
    method: KimiOAuthConnectionMethod = Field(description="Connection method")
    user_code: str = Field(description="Device user code")
    verification_uri: str = Field(description="Device verification URI")
    interval_seconds: int = Field(description="Polling interval")
    status: KimiOAuthSessionStatus = Field(description="Session status")
    expires_at: datetime.datetime = Field(description="Session expiration time")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class KimiOAuthSessionWithSecrets(KimiOAuthSession):
    """Kimi OAuth session including decrypted secret values."""

    device_code: str = Field(description="OAuth device code")
    device_id: str = Field(description="Stable device identity")


class KimiOAuthSessionCreate(BaseModel):
    """Kimi OAuth session create schema."""

    workspace_id: str = Field(description="Workspace ID")
    user_id: str = Field(description="User ID")
    method: KimiOAuthConnectionMethod = Field(description="Connection method")
    device_code: str = Field(description="OAuth device code")
    device_id: str = Field(description="Stable device identity")
    user_code: str = Field(description="Device user code")
    verification_uri: str = Field(description="Device verification URI")
    interval_seconds: int = Field(description="Polling interval")
    expires_at: datetime.datetime = Field(description="Session expiration time")


class KimiOAuthSessionUpdate(TypedDict, total=False):
    """Kimi OAuth session update schema."""

    status: Annotated[KimiOAuthSessionStatus, Field(description="Session status")]


@dataclasses.dataclass(frozen=True)
class NotFound:
    """Session not found."""

    session_id: str
