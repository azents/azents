"""GitHub Toolkit credential type definitions.

Defines credential models for GitHub authentication modes.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class GitHubSecretsPAT(BaseModel):
    """Personal Access Token authentication."""

    type: Literal["pat"] = "pat"
    token: str = Field(description="GitHub PAT (ghp_... or fine-grained)")


class GitHubInstallationTarget(BaseModel):
    """Account metadata for a GitHub App installation target."""

    installation_id: str = Field(description="GitHub App Installation ID")
    account_login: str = Field(description="Installed account or organization login")
    account_type: str = Field(
        description="GitHub account type, such as User or Organization"
    )
    account_avatar_url: str | None = Field(
        description="Installed account avatar URL",
    )


class GitHubSecretsApp(BaseModel):
    """GitHub App (BYOA) authentication.

    Stores user-provided GitHub App credentials and accessible installations.
    """

    type: Literal["github_app"] = "github_app"
    app_id: str = Field(description="GitHub App ID")
    private_key: str = Field(description="Private key in PEM format")
    installations: list[GitHubInstallationTarget] = Field(
        min_length=1,
        description="GitHub App installations available to this toolkit",
    )


class GitHubSecretsAppPlatform(BaseModel):
    """GitHub App (Platform) authentication.

    Stores only installation targets for the Azents-provided GitHub App.
    The app ID and private key are read from server environment variables.
    """

    type: Literal["github_app_platform"] = "github_app_platform"
    app_id: str | None = Field(
        default=None,
        description="Internal Platform GitHub App identity binding",
    )
    installations: list[GitHubInstallationTarget] = Field(
        min_length=1,
        description="GitHub App installations available to this toolkit",
    )


GitHubSecrets = Annotated[
    GitHubSecretsPAT | GitHubSecretsApp | GitHubSecretsAppPlatform,
    Field(discriminator="type"),
]
"""GitHub Toolkit credential discriminated union."""
