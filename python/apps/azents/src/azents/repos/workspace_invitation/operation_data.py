"""Detached outcomes of completed Workspace invitation operations."""

from dataclasses import dataclass

from azents.core.enums import InvitationStatus
from azents.repos.workspace.data import Workspace
from azents.repos.workspace_invitation.data import WorkspaceInvitation


@dataclass(frozen=True)
class AlreadyMember:
    """The email belongs to an existing Workspace member."""

    email: str


@dataclass(frozen=True)
class InvitationNotFound:
    """The invitation is absent or is not owned by the requester."""

    invitation_id: str


@dataclass(frozen=True)
class AlreadyProcessed:
    """The invitation is no longer pending."""

    invitation_id: str
    status: InvitationStatus


@dataclass(frozen=True)
class WorkspaceNotFound:
    """The Workspace handle does not exist."""

    handle: str


@dataclass(frozen=True)
class CreatedInvitation:
    """Committed invitation and signup-token preparation decision."""

    invitation: WorkspaceInvitation
    needs_signup_token: bool


@dataclass(frozen=True)
class ReceivedInvitation:
    """Pending invitation with its detached Workspace information."""

    invitation: WorkspaceInvitation
    workspace: Workspace
