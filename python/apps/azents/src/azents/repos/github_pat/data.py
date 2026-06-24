"""GitHub PAT repository data models."""

import datetime

from pydantic import BaseModel, Field


class GitHubPAT(BaseModel):
    """Decrypted GitHub PAT domain model."""

    id: str = Field(description="GitHub PAT ID")
    workspace_id: str = Field(description="Workspace ID")
    user_id: str = Field(description="User ID")
    token: str = Field(description="Decrypted PAT")
    github_username: str | None = Field(
        default=None, description="GitHub username for display"
    )
    display_hint: str | None = Field(
        default=None, description="Token identification hint (first 8 chars)"
    )
    expires_at: datetime.datetime | None = Field(
        default=None, description="Fine-grained PAT expiration date"
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class GitHubPATStatus(BaseModel):
    """GitHub PAT status excluding token — for frontend display."""

    registered: bool = Field(description="PAT registration flag")
    github_username: str | None = Field(default=None, description="GitHub username")
    display_hint: str | None = Field(
        default=None, description="Token identification hint"
    )
    expires_at: datetime.datetime | None = Field(
        default=None, description="Fine-grained PAT expiration date"
    )
