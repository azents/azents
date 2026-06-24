"""WorkspaceJoinRequest service data models."""

import dataclasses
import datetime
from typing import Self

from pydantic import BaseModel, Field

from azents.core.enums import JoinRequestStatus
from azents.repos.workspace_join_request.data import WorkspaceJoinRequest


class JoinRequestOutput(BaseModel):
    """Join request output model."""

    id: str = Field(description="Join request ID")
    workspace_id: str = Field(description="Workspace ID")
    user_id: str = Field(description="Requesting user ID")
    message: str | None = Field(description="Join reason")
    status: JoinRequestStatus = Field(description="Request status")
    created_at: datetime.datetime = Field(description="Created time")

    @classmethod
    def convert_from(cls, data: WorkspaceJoinRequest) -> Self:
        """Convert from domain model."""
        return cls.model_validate(data, from_attributes=True)


class JoinRequestListOutput(BaseModel):
    """Join request list output model."""

    items: list[JoinRequestOutput] = Field(description="Join request list")
    total: int = Field(description="Total count")


class MyJoinRequestOutput(BaseModel):
    """My join request status output model."""

    id: str = Field(description="Join request ID")
    status: JoinRequestStatus = Field(description="Request status")
    message: str | None = Field(description="Join reason")
    created_at: datetime.datetime = Field(description="Created time")

    @classmethod
    def convert_from(cls, data: WorkspaceJoinRequest) -> Self:
        """Convert from domain model."""
        return cls.model_validate(data, from_attributes=True)


@dataclasses.dataclass(frozen=True)
class AlreadyMember:
    """Already workspace member."""

    user_id: str


@dataclasses.dataclass(frozen=True)
class WorkspaceNotFound:
    """Workspace not found."""

    handle: str


@dataclasses.dataclass(frozen=True)
class JoinRequestNotFound:
    """Join request not found."""

    join_request_id: str


@dataclasses.dataclass(frozen=True)
class PendingRequestExists:
    """Pending join request already exists."""

    join_request_id: str
