"""WorkspaceInvitation repository data models."""

import dataclasses
import datetime
from typing import Self

from pydantic import BaseModel, Field

from azents.core.enums import InvitationStatus, WorkspaceUserRole


class WorkspaceInvitation(BaseModel):
    """WorkspaceInvitation domain model."""

    id: str = Field(description="WorkspaceInvitation ID (UUID7 hex)")
    workspace_id: str = Field(description="Workspace ID")
    email: str = Field(description="Invitation target email")
    role: WorkspaceUserRole = Field(description="Invitation role")
    invited_by: str = Field(description="Inviting WorkspaceUser ID")
    status: InvitationStatus = Field(description="Invitation status")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def convert_from(cls, data: "WorkspaceInvitation") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


class WorkspaceInvitationCreate(BaseModel):
    """WorkspaceInvitation create schema."""

    workspace_id: str = Field(description="Workspace ID")
    email: str = Field(description="Invitation target email (lowercase-normalized)")
    role: WorkspaceUserRole = Field(description="Invitation role")
    invited_by: str = Field(description="Inviting WorkspaceUser ID")


class WorkspaceInvitationList(BaseModel):
    """WorkspaceInvitation list."""

    items: list[WorkspaceInvitation] = Field(description="Invitation list")


@dataclasses.dataclass(frozen=True)
class NotFound:
    """Invitation not found."""

    invitation_id: str
