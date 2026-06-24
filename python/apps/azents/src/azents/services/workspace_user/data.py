"""WorkspaceUser service data models."""

import dataclasses

from pydantic import BaseModel, Field

from azents.repos.workspace_user.data import (
    WorkspaceUser,
    WorkspaceUserRole,
    WorkspaceUserUpdate,
)


class WorkspaceUserOutput(WorkspaceUser):
    """WorkspaceUser output model."""

    pass


class WorkspaceUserCreateInput(BaseModel):
    """WorkspaceUser create input model (external, uses workspace_handle)."""

    workspace_handle: str = Field(description="Owning Workspace handle")
    user_id: str = Field(description="User ID")
    name: str = Field(description="Workspace display name")
    locale: str = Field(default="ko-KR", description="Workspace locale (BCP 47)")
    role: WorkspaceUserRole = Field(description="Role (owner, manager, member)")


class WorkspaceUserUpdateInput(WorkspaceUserUpdate):
    """WorkspaceUser update input model."""

    pass


class WorkspaceUserListOutput(BaseModel):
    """WorkspaceUser list output model."""

    items: list[WorkspaceUserOutput] = Field(description="WorkspaceUser list")


@dataclasses.dataclass(frozen=True)
class CannotModifySelf:
    """Cannot change or delete own role."""

    pass


@dataclasses.dataclass(frozen=True)
class CannotModifyOwner:
    """Cannot change or delete Owner role."""

    pass


@dataclasses.dataclass(frozen=True)
class InvalidRole:
    """Attempted to change to disallowed role."""

    pass


@dataclasses.dataclass(frozen=True)
class NotMemberOfWorkspace:
    """Target is not member of that workspace."""

    workspace_user_id: str
