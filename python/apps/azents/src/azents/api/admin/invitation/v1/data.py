"""Invitation API v1 response schemas (Admin)."""

from pydantic import BaseModel, Field

from azents.services.workspace_invitation.data import InvitationOutput


class InvitationResponse(InvitationOutput):
    """Invitation response schema."""

    pass


class InvitationListResponse(BaseModel):
    """Invitation list response schema."""

    items: list[InvitationResponse] = Field(description="Invitation list")
