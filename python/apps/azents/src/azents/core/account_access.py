"""Pure account and Workspace admission outcomes."""

import dataclasses
from enum import StrEnum

from azents.core.enums import WorkspaceUserRole


class ActiveAccountSubjectStatus(StrEnum):
    """Database status of a User and its exact authentication Session."""

    ACTIVE = "active"
    USER_MISSING = "user_missing"
    USER_DISABLED = "user_disabled"
    SESSION_MISSING = "session_missing"
    SESSION_FOREIGN = "session_foreign"
    SESSION_REVOKED = "session_revoked"
    SESSION_EXPIRED = "session_expired"


@dataclasses.dataclass(frozen=True)
class AccountWorkspaceMembership:
    """Detached current Workspace membership authority."""

    workspace_user_id: str
    role: WorkspaceUserRole


@dataclasses.dataclass(frozen=True)
class WorkspaceMembershipAccess:
    """Resolved Workspace and its nullable current User membership."""

    workspace_id: str | None
    membership: AccountWorkspaceMembership | None
