"""JoinRequest API v1 request/response schemas (Public)."""

from pydantic import BaseModel, Field

from azents.services.workspace_join_request.data import (
    JoinRequestOutput,
    MyJoinRequestOutput,
)


class CreateJoinRequestRequest(BaseModel):
    """Join request creation request."""

    message: str | None = Field(default=None, description="Join reason, optional")


class JoinRequestResponse(JoinRequestOutput):
    """Join request response schema."""

    pass


class JoinRequestListResponse(BaseModel):
    """Join request list response schema."""

    items: list[JoinRequestResponse] = Field(description="Join request list")
    total: int = Field(description="Total count")


class MyJoinRequestResponse(MyJoinRequestOutput):
    """My join request response schema."""

    pass
