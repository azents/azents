"""WorkspaceInvitation service data models."""

import dataclasses
import datetime
from typing import Self

from pydantic import BaseModel, Field

from azents.core.enums import InvitationStatus, WorkspaceUserRole
from azents.repos.workspace_invitation.data import WorkspaceInvitation


class InvitationOutput(WorkspaceInvitation):
    """Invitation output model."""

    pass


class ReceivedInvitationOutput(BaseModel):
    """Received invitation output model (including workspace info)."""

    id: str = Field(description="Invitation ID")
    workspace_id: str = Field(description="Workspace ID")
    workspace_name: str = Field(description="Workspace name")
    workspace_handle: str = Field(description="Workspace handle")
    email: str = Field(description="Invitation target email")
    role: WorkspaceUserRole = Field(description="Invitation role")
    status: InvitationStatus = Field(description="Invitation status")
    created_at: datetime.datetime = Field(description="Created time")

    @classmethod
    def convert_from(cls, data: "ReceivedInvitationOutput") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


class ReceivedInvitationListOutput(BaseModel):
    """Received invitation list output model."""

    items: list[ReceivedInvitationOutput] = Field(
        description="Received invitation list"
    )


class InvitationListOutput(BaseModel):
    """Invitation list output model."""

    items: list[InvitationOutput] = Field(description="Invitation list")


class CreateInvitationInput(BaseModel):
    """Invitation create input model."""

    email: str = Field(description="Invitation target email")
    role: WorkspaceUserRole = Field(description="Invitation role")


class AcceptDeclineOutput(BaseModel):
    """Invitation accept/decline output model."""

    id: str = Field(description="Invitation ID")
    status: InvitationStatus = Field(description="Changed status")

    @classmethod
    def convert_from(cls, data: "AcceptDeclineOutput") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


@dataclasses.dataclass(frozen=True)
class AlreadyMember:
    """Already workspace member."""

    email: str


@dataclasses.dataclass(frozen=True)
class InvitationNotFound:
    """Invitation not found."""

    invitation_id: str


@dataclasses.dataclass(frozen=True)
class AlreadyProcessed:
    """Invitation already processed (accepted/declined)."""

    invitation_id: str
    status: InvitationStatus


@dataclasses.dataclass(frozen=True)
class WorkspaceNotFound:
    """Workspace not found."""

    handle: str
