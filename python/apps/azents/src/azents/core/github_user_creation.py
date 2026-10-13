"""Detached unpublished GitHub user-account creation authority."""

import dataclasses
import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from azents.core.github_setup import GitHubSetupTransport
from azents.core.github_user_oauth import (
    GitHubUserAttemptStatus,
    GitHubUserCandidate,
    GitHubUserRegistration,
    GitHubUserRevocation,
)
from azents.core.toolkit_identifiers import (
    IdentifierValidationError,
    resolve_create_identifiers,
)
from azents.core.tools import GitHubToolkitConfig
from azents.repos.toolkit.data import ToolkitCreate


@dataclasses.dataclass(frozen=True)
class GitHubUserCreationSubject:
    """Exact current manager, authentication Session and desired ownership."""

    user_id: str
    session_id: str
    workspace_id: str
    agent_id: str | None


@dataclasses.dataclass(frozen=True)
class GitHubUserCreationAttempt:
    """A pending authorization, never a saved or executable Toolkit."""

    id: str
    subject: GitHubUserCreationSubject
    desired: ToolkitCreate = dataclasses.field(repr=False)
    registration: GitHubUserRegistration
    redirect_uri: str
    nonce: str = dataclasses.field(repr=False)
    code_verifier: str = dataclasses.field(repr=False)
    expires_at: datetime.datetime
    status: GitHubUserAttemptStatus
    candidate: GitHubUserCandidate | None


@dataclasses.dataclass(frozen=True)
class GitHubUserCreationStart:
    """Reserved creation and exact candidates replaced by this reservation."""

    attempt: GitHubUserCreationAttempt
    revocations: tuple[GitHubUserRevocation, ...]


class GitHubUserCreationFinalSettings(GitHubSetupTransport):
    """Complete final non-authentication input, never an attempt-settings patch."""

    name: str | None = Field(max_length=255)
    slug: str | None
    description: str | None
    prompt: str | None
    enabled: bool
    always_expose_tools: bool
    inject_runtime_environment: bool
    runtime_risk_acknowledged: bool

    @model_validator(mode="after")
    def require_runtime_consent(self) -> "GitHubUserCreationFinalSettings":
        if self.inject_runtime_environment and not self.runtime_risk_acknowledged:
            raise ValueError("Runtime token injection requires risk acknowledgment.")
        return self

    def prepare(self, *, canonical_name: str) -> "GitHubUserCreationSettings":
        """Normalize identifiers before entering the publication transaction."""
        identifiers = resolve_create_identifiers(
            toolkit_type="github",
            canonical_name=canonical_name,
            submitted_name=self.name,
            submitted_slug=self.slug,
        )
        if isinstance(identifiers, IdentifierValidationError):
            raise ValueError("Invalid Toolkit name or slug.")
        return GitHubUserCreationSettings(
            name=identifiers.name,
            slug=identifiers.slug,
            description=self.description,
            prompt=self.prompt,
            enabled=self.enabled,
            always_expose_tools=self.always_expose_tools,
            toolsets=tuple(self.toolsets),
            timeout=self.timeout,
            inject_runtime_environment=self.inject_runtime_environment,
        )


class GitHubUserCreationConfirmRequest(BaseModel):
    """Exact creation attempt plus complete final reviewed settings."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    attempt_id: str = Field(min_length=1, max_length=64)
    settings: GitHubUserCreationFinalSettings


@dataclasses.dataclass(frozen=True)
class GitHubUserCreationSettings:
    """Validated non-authentication overlay; authority comes from the locked attempt."""

    name: str
    slug: str
    description: str | None
    prompt: str | None
    enabled: bool
    always_expose_tools: bool
    toolsets: tuple[str, ...]
    timeout: float
    inject_runtime_environment: bool

    def apply(self, desired: ToolkitCreate) -> ToolkitCreate:
        """Combine only allowlisted settings with this attempt's retained authority."""
        previous = GitHubToolkitConfig.model_validate(desired.config)
        config = GitHubToolkitConfig(
            github_auth_type=previous.github_auth_type,
            toolsets=list(self.toolsets),
            timeout=self.timeout,
            inject_runtime_environment=self.inject_runtime_environment,
        )
        return ToolkitCreate(
            workspace_id=desired.workspace_id,
            owner_agent_id=desired.owner_agent_id,
            toolkit_type=desired.toolkit_type,
            credentials=desired.credentials,
            name=self.name,
            slug=self.slug,
            description=self.description,
            prompt=self.prompt,
            enabled=self.enabled,
            always_expose_tools=self.always_expose_tools,
            config=config.model_dump(),
        )
