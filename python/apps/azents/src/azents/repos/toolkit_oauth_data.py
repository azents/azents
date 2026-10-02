"""Detached inputs and outcomes for completed shared Toolkit OAuth operations."""

import dataclasses
from enum import StrEnum

from azents.core.account_access import ActiveAccountSubjectStatus
from azents.repos.mcp_oauth_connection.data import MCPOAuthConnection
from azents.repos.toolkit.data import ToolkitConfig


@dataclasses.dataclass(frozen=True)
class ToolkitOAuthRequester:
    """Trusted scalar identity admitted before external OAuth work."""

    user_id: str
    session_id: str
    workspace_id: str


@dataclasses.dataclass(frozen=True)
class GithubInstallationRecord:
    """One provider row decoded for the existing ordered installation sync."""

    installation_id: int
    account_login: str
    account_type: str
    account_avatar_url: str


@dataclasses.dataclass(frozen=True)
class SharedOAuthContext:
    """Ordered shared Toolkit and connection read snapshots, including absence."""

    toolkit: ToolkitConfig | None
    connection: MCPOAuthConnection | None


class ToolkitOAuthDenialReason(StrEnum):
    """Existing admission categories in their original precedence."""

    INACTIVE_SUBJECT = "inactive_subject"
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    MEMBERSHIP_REQUIRED = "membership_required"
    WRITE_PERMISSION_REQUIRED = "write_permission_required"
    TOOLKIT_NOT_FOUND = "toolkit_not_found"


@dataclasses.dataclass(frozen=True)
class ToolkitOAuthDenied:
    """Expected detached denial without HTTP or provider error conversion."""

    reason: ToolkitOAuthDenialReason
    subject_status: ActiveAccountSubjectStatus | None
