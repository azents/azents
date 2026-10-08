"""Detached contracts for Toolkit-local GitHub user authorization."""

import dataclasses
import datetime
import enum
from typing import Literal

from azents.repos.toolkit.data import ToolkitConfig


class GitHubUserAttemptStatus(enum.StrEnum):
    """One-use local authorization attempt states."""

    PENDING = "pending"
    EXCHANGING = "exchanging"
    REVIEW = "review"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class GitHubUserConnectionStatus(enum.StrEnum):
    """Current saved credential usability."""

    CONNECTED = "connected"
    RECONNECT_REQUIRED = "reconnect_required"


class GitHubUserCleanupStatus(enum.StrEnum):
    """Non-executable retired credential cleanup status."""

    PENDING = "pending"
    FAILED = "failed"


class GitHubUserErrorCode(enum.StrEnum):
    """Safe management failures without provider credential payloads."""

    AUTHORITY = "authority"
    NOT_FOUND = "not_found"
    STALE = "stale"
    INVALID = "invalid"
    CLEANUP_REQUIRED = "cleanup_required"


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


@dataclasses.dataclass(frozen=True)
class GitHubUserRegistration:
    """Selected App binding captured for setup or exact-token cleanup."""

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

    toolkit: ToolkitConfig = dataclasses.field(repr=False)
    connection: GitHubUserConnection | None
    cleanup_pending: bool


@dataclasses.dataclass(frozen=True)
class GitHubUserAttempt:
    """Bound one-use setup record after its database operation completes."""

    id: str
    requester: GitHubUserRequester
    registration: GitHubUserRegistration
    redirect_uri: str
    nonce: str = dataclasses.field(repr=False)
    code_verifier: str = dataclasses.field(repr=False)
    expires_at: datetime.datetime
    captured_connection_id: str | None
    status: GitHubUserAttemptStatus
    candidate: GitHubUserCandidate | None


@dataclasses.dataclass(frozen=True)
class GitHubUserCleanup:
    """Retired credential material usable only for single-token revocation."""

    id: str
    toolkit_id: str
    registration: GitHubUserRegistration
    access_token: str = dataclasses.field(repr=False)
    reason: str
    status: GitHubUserCleanupStatus
    failure_reason: str | None


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
    cleanup_pending: bool
