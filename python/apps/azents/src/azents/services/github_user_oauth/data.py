"""Allowlisted GitHub user-account management projections."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from azents.core.github_user_oauth import GitHubUserConnectionSummary


class GitHubUserConnectOutput(BaseModel):
    """One setup URL and its local attempt identifier."""

    model_config = ConfigDict(extra="forbid")
    attempt_id: str
    authorization_url: str = Field(repr=False)
    install_url: str


class GitHubUserCandidateSummary(BaseModel):
    """Verified account awaiting the manager's explicit confirmation."""

    model_config = ConfigDict(extra="forbid")
    attempt_id: str
    account_id: int
    account_login: str
    account_avatar_url: str | None
    app_id: str
    source: Literal["platform_user", "byoa_user"]
    sharing_scope: Literal["workspace_shared", "agent_only"]


class GitHubUserStatusOutput(BaseModel):
    """Current saved connection, with no provider-cleanup success claim."""

    model_config = ConfigDict(extra="forbid")
    connection: GitHubUserConnectionSummary | None


class GitHubSetupAvailability(BaseModel):
    """Local registration availability, independent of provider health."""

    model_config = ConfigDict(extra="forbid")
    platform: Literal["configured", "incomplete", "absent"]
    callback_url: str | None
    user_tokens_must_not_expire: bool = True


class GitHubUserCreationReview(BaseModel):
    """Verified account and desired nonsecret settings before publication."""

    model_config = ConfigDict(extra="forbid")
    candidate: GitHubUserCandidateSummary
    name: str
    slug: str
    description: str | None
    prompt: str | None
    config: dict[str, object]
    enabled: bool
    always_expose_tools: bool


class GitHubUserCreatedOutput(BaseModel):
    """Exact successfully published Toolkit, without credential payloads."""

    toolkit_id: str
