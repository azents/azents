"""Strict unpublished GitHub setup inputs and redacted observations."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class GitHubSetupModel(BaseModel):
    """Reject unrecognized setup fields and keep validation inputs private."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


GitHubSetupNumericID = Annotated[str, Field(pattern=r"^[1-9][0-9]*$")]


class GitHubSetupTransport(GitHubSetupModel):
    """Only supported MCP transport settings, without a provider URL override."""

    toolsets: list[str]
    timeout: float = Field(gt=0, allow_inf_nan=False)


class GitHubPATSetupVerification(GitHubSetupModel):
    github_auth_type: Literal["pat"]
    transport: GitHubSetupTransport
    token: str = Field(min_length=1, repr=False)


class GitHubAppSetupVerification(GitHubSetupModel):
    github_auth_type: Literal["github_app"]
    transport: GitHubSetupTransport
    app_id: GitHubSetupNumericID
    private_key: str = Field(min_length=1, repr=False)
    installation_ids: list[GitHubSetupNumericID] = Field(min_length=1)


class GitHubPlatformSetupVerification(GitHubSetupModel):
    github_auth_type: Literal["github_app_platform"]
    transport: GitHubSetupTransport
    installation_ids: list[GitHubSetupNumericID] = Field(min_length=1)


GitHubSetupVerificationRequest = Annotated[
    GitHubPATSetupVerification
    | GitHubAppSetupVerification
    | GitHubPlatformSetupVerification,
    Field(discriminator="github_auth_type"),
]


class GitHubSetupAppIdentity(GitHubSetupModel):
    app_id: str
    name: str
    slug: str


class GitHubSetupAppOutput(GitHubSetupModel):
    app: GitHubSetupAppIdentity | None


class GitHubSetupUserIdentity(GitHubSetupModel):
    type: Literal["user"]
    id: int
    login: str
    avatar_url: str | None


class GitHubSetupAppVerifiedIdentity(GitHubSetupAppIdentity):
    type: Literal["app"]


class GitHubSetupInstallationObservation(GitHubSetupModel):
    installation_id: str
    account_login: str | None
    account_type: str | None
    account_avatar_url: str | None
    status: Literal["ready", "denied", "unavailable"]
    message: str | None


class GitHubSetupConnectivity(GitHubSetupModel):
    status: Literal["ready", "failed"]
    message: str | None


class GitHubSetupVerificationOutput(GitHubSetupModel):
    identity: Annotated[
        GitHubSetupUserIdentity | GitHubSetupAppVerifiedIdentity,
        Field(discriminator="type"),
    ]
    installations: list[GitHubSetupInstallationObservation]
    connectivity: GitHubSetupConnectivity
