"""WorkspaceJoinRequest repository data models."""

import dataclasses
import datetime
from typing import NotRequired, Self

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from azents.core.enums import JoinRequestStatus


class WorkspaceJoinRequest(BaseModel):
    """WorkspaceJoinRequest domain model."""

    id: str = Field(description="Join request ID (UUID7 hex)")
    workspace_id: str = Field(description="Workspace ID")
    user_id: str = Field(description="Requesting User ID")
    message: str | None = Field(description="Join reason (optional)")
    status: JoinRequestStatus = Field(description="Request status (pending/muted)")
    last_notified_at: datetime.datetime | None = Field(
        description="Last notification send time"
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def convert_from(cls, data: "WorkspaceJoinRequest") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


class WorkspaceJoinRequestCreate(TypedDict):
    """WorkspaceJoinRequest create schema."""

    workspace_id: str
    user_id: str
    message: NotRequired[str | None]


class WorkspaceJoinRequestUpdate(TypedDict, total=False):
    """WorkspaceJoinRequest update schema (partial update)."""

    message: str | None
    status: JoinRequestStatus
    last_notified_at: datetime.datetime | None


class WorkspaceJoinRequestList(BaseModel):
    """WorkspaceJoinRequest list."""

    items: list[WorkspaceJoinRequest] = Field(description="Join request list")
    total: int = Field(description="Total count")


@dataclasses.dataclass(frozen=True)
class NotFound:
    """Join request not found."""

    join_request_id: str
