"""Detached contracts for Toolkit-local GitHub user authorization."""

import dataclasses
import datetime
import enum
from typing import Literal, assert_never

from azents.core.toolkit_ownership import (
    AgentToolkitOwner,
    ToolkitOwner,
    ToolkitOwnerKind,
    UserToolkitOwner,
    WorkspaceToolkitOwner,
)
from azents.repos.toolkit.data import PersonalToolkitConfig, ToolkitConfig


class GitHubUserAttemptStatus(enum.StrEnum):
    """One-use local authorization attempt states."""

    PENDING = "pending"
    EXCHANGING = "exchanging"
    REVIEW = "review"


class GitHubUserConnectionStatus(enum.StrEnum):
    """Current saved credential usability."""

    CONNECTED = "connected"
    RECONNECT_REQUIRED = "reconnect_required"


class GitHubUserErrorCode(enum.StrEnum):
    """Safe management failures without provider credential payloads."""

    AUTHORITY = "authority"
    NOT_FOUND = "not_found"
    STALE = "stale"
    INVALID = "invalid"


class GitHubUserOAuthError(ValueError):
    """Expected authorization lifecycle rejection."""

    def __init__(self, code: GitHubUserErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclasses.dataclass(frozen=True)
class GitHubUserRequester:
    """Exact authenticated management and Toolkit ownership context."""

    user_id: str
    session_id: str
    workspace_id: str
    agent_id: str | None
    toolkit_id: str

    @property
    def owner(self) -> WorkspaceToolkitOwner | AgentToolkitOwner:
        """Expose the existing shared/Agent ownership as a closed owner target."""
        if self.agent_id is not None:
            return AgentToolkitOwner(
                kind=ToolkitOwnerKind.AGENT,
                workspace_id=self.workspace_id,
                agent_id=self.agent_id,
            )
        return WorkspaceToolkitOwner(
            kind=ToolkitOwnerKind.WORKSPACE,
            workspace_id=self.workspace_id,
        )


@dataclasses.dataclass(frozen=True)
class GitHubPersonalRequester:
    """Exact active owner, Auth Session and canonical personal Toolkit target."""

    user_id: str
    session_id: str
    toolkit_id: str
    owner: UserToolkitOwner

    def __post_init__(self) -> None:
        if self.owner.user_id != self.user_id:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.AUTHORITY, "GitHub personal owner does not match."
            )

    @property
    def workspace_id(self) -> None:
        """User-global setup has no owning Workspace."""
        return None

    @property
    def agent_id(self) -> None:
        """Agent origin is not connection ownership."""
        return None


GitHubToolkitRequester = GitHubUserRequester | GitHubPersonalRequester


def github_requester_for_owner(
    *,
    user_id: str,
    session_id: str,
    toolkit_id: str,
    owner: ToolkitOwner,
) -> GitHubToolkitRequester:
    """Decode persisted setup context into an exact closed management target."""
    match owner:
        case UserToolkitOwner():
            return GitHubPersonalRequester(user_id, session_id, toolkit_id, owner)
        case AgentToolkitOwner():
            return GitHubUserRequester(
                user_id, session_id, owner.workspace_id, owner.agent_id, toolkit_id
            )
        case WorkspaceToolkitOwner():
            return GitHubUserRequester(
                user_id, session_id, owner.workspace_id, None, toolkit_id
            )
        case _:
            assert_never(owner)


@dataclasses.dataclass(frozen=True)
class GitHubUserRegistration:
    """Selected App binding captured for setup or a bounded revocation attempt."""

    source: Literal["platform_user", "byoa_user"]
    app_id: str
    client_id: str
    client_secret: str | None = dataclasses.field(repr=False)
    toolkit_revision: int
    platform_generation: str | None


@dataclasses.dataclass(frozen=True)
class GitHubUserCandidate:
    """Provider-verified candidate that is not yet an execution credential."""

    access_token: str = dataclasses.field(repr=False)
    account_id: int
    account_login: str
    account_avatar_url: str | None


@dataclasses.dataclass(frozen=True)
class GitHubUserConnection:
    """Detached active credential, never a public response object."""

    id: str
    toolkit_id: str
    registration: GitHubUserRegistration
    access_token: str = dataclasses.field(repr=False)
    account_id: int
    account_login: str
    account_avatar_url: str | None
    status: GitHubUserConnectionStatus
    failure_reason: str | None


@dataclasses.dataclass(frozen=True)
class GitHubUserContext:
    """Authorized current Toolkit state for service preparation."""

    toolkit: ToolkitConfig | PersonalToolkitConfig = dataclasses.field(repr=False)
    connection: GitHubUserConnection | None


@dataclasses.dataclass(frozen=True)
class GitHubUserAttempt:
    """Bound one-use setup record after its database operation completes."""

    id: str
    requester: GitHubToolkitRequester
    registration: GitHubUserRegistration
    redirect_uri: str
    nonce: str = dataclasses.field(repr=False)
    code_verifier: str = dataclasses.field(repr=False)
    expires_at: datetime.datetime
    captured_connection_id: str | None
    status: GitHubUserAttemptStatus
    candidate: GitHubUserCandidate | None


@dataclasses.dataclass(frozen=True)
class GitHubUserRevocation:
    """Transient exact-token facts for cleanup after the local transaction."""

    registration: GitHubUserRegistration
    access_token: str = dataclasses.field(repr=False)


@dataclasses.dataclass(frozen=True)
class GitHubUserStartResult:
    """New setup and tokens discarded by its completed local reservation."""

    attempt: GitHubUserAttempt
    revocations: tuple[GitHubUserRevocation, ...]


@dataclasses.dataclass(frozen=True)
class GitHubUserConfirmResult:
    """Committed active connection and its captured superseded credential."""

    connection: GitHubUserConnection
    revocations: tuple[GitHubUserRevocation, ...]


@dataclasses.dataclass(frozen=True)
class GitHubUserConnectionSummary:
    """Allowlisted public metadata without access or client credentials."""

    id: str
    account_id: int
    account_login: str
    account_avatar_url: str | None
    app_id: str
    source: Literal["platform_user", "byoa_user"]
    status: GitHubUserConnectionStatus
    failure_reason: str | None
