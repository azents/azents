"""GitHub PAT v1 Public API data models."""

import datetime

from pydantic import BaseModel, Field


class RegisterPATRequest(BaseModel):
    """PAT registration request."""

    token: str = Field(description="GitHub Personal Access Token")


class RegisterPATResponse(BaseModel):
    """PAT registration success response."""

    github_username: str = Field(description="GitHub username")
    expires_at: datetime.datetime | None = Field(
        default=None, description="Fine-grained PAT expiration date"
    )


class PATStatusResponse(BaseModel):
    """PAT status response."""

    registered: bool = Field(description="Whether PAT is registered")
    github_username: str | None = Field(default=None, description="GitHub username")
    display_hint: str | None = Field(
        default=None, description="Token identification hint"
    )
    expires_at: datetime.datetime | None = Field(
        default=None, description="Fine-grained PAT expiration date"
    )


class SetupStatusResponse(BaseModel):
    """Settings status response for the settings page."""

    platform_linked: bool = Field(description="Whether platform account is linked")
    pat_registered: bool = Field(description="Whether PAT is registered")
    github_username: str | None = Field(default=None, description="GitHub username")
