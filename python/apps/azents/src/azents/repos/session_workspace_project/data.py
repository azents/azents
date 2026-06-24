"""Session Workspace Project repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import SessionWorkspaceProjectRegistrationRequestStatus


class SessionWorkspaceProject(BaseModel):
    """AgentRuntime scoped Project domain model."""

    id: str = Field(description="Project ID")
    agent_runtime_id: str = Field(description="AgentRuntime ID")
    path: str = Field(description="Absolute path under /workspace/agent")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class SessionWorkspaceProjectCreate(BaseModel):
    """Session Workspace Project create schema."""

    agent_runtime_id: str = Field(description="AgentRuntime ID")
    path: str = Field(description="Absolute path under /workspace/agent")


class SessionWorkspaceProjectRegistrationRequest(BaseModel):
    """Session Workspace Project registration request domain model."""

    id: str = Field(description="Request ID")
    agent_runtime_id: str = Field(description="AgentRuntime ID")
    path: str = Field(description="Requested Project path")
    reason: str = Field(description="Request reason provided by Agent")
    status: SessionWorkspaceProjectRegistrationRequestStatus = Field(
        description="Request status"
    )
    project_id: str | None = Field(
        default=None,
        description="Project ID created after approval",
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class SessionWorkspaceProjectRegistrationRequestCreate(BaseModel):
    """Session Workspace Project registration request create schema."""

    agent_runtime_id: str = Field(description="AgentRuntime ID")
    path: str = Field(description="Requested Project path")
    reason: str = Field(description="Request reason provided by Agent")
