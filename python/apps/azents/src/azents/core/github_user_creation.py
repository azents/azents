"""Detached unpublished GitHub user-account creation authority."""

import dataclasses
import datetime

from azents.core.github_user_oauth import (
    GitHubUserAttemptStatus,
    GitHubUserCandidate,
    GitHubUserRegistration,
    GitHubUserRevocation,
)
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
