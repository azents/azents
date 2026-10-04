"""Detached outcomes of completed Workspace join-request operations."""

from dataclasses import dataclass

from azents.repos.workspace_join_request.data import WorkspaceJoinRequest


@dataclass(frozen=True)
class AlreadyMember:
    """The requester already belongs to the Workspace."""

    user_id: str


@dataclass(frozen=True)
class WorkspaceNotFound:
    """The Workspace handle does not exist."""

    handle: str


@dataclass(frozen=True)
class JoinRequestNotFound:
    """The join request does not exist."""

    join_request_id: str


@dataclass(frozen=True)
class PendingRequestExists:
    """The requester already has a pending request."""

    join_request_id: str


@dataclass(frozen=True)
class RequestedJoin:
    """Committed request and notification decision."""

    join_request: WorkspaceJoinRequest
    should_send_notification: bool


@dataclass(frozen=True)
class ApprovedJoin:
    """Committed membership and identity for post-commit approval delivery."""

    workspace_id: str
    user_id: str
