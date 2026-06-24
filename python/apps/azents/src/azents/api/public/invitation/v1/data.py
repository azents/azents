"""Invitation API v1 request/response schemas (Public)."""

from pydantic import BaseModel, Field

from azents.core.enums import WorkspaceUserRole
from azents.services.workspace_invitation.data import (
    AcceptDeclineOutput,
    InvitationOutput,
    ReceivedInvitationOutput,
)


class CreateInvitationRequest(BaseModel):
    """Invitation creation request."""

    email: str = Field(description="Invitation target email")
    role: WorkspaceUserRole = Field(
        default=WorkspaceUserRole.MEMBER,
        description="Invitation role (member, manager)",
    )


class InvitationResponse(InvitationOutput):
    """Invitation response schema."""

    pass


class ReceivedInvitationResponse(ReceivedInvitationOutput):
    """Received invitation response schema."""

    pass


class ReceivedInvitationListResponse(BaseModel):
    """Received invitation list response schema."""

    items: list[ReceivedInvitationResponse] = Field(
        description="Received invitation list"
    )


class InvitationListResponse(BaseModel):
    """Invitation list response schema."""

    items: list[InvitationResponse] = Field(description="Invitation list")


class AcceptDeclineResponse(AcceptDeclineOutput):
    """Invitation accept/reject response schema."""

    pass
