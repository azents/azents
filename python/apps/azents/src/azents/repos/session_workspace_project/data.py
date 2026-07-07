"""Session Workspace Project repository data models."""

import datetime

from pydantic import BaseModel, Field


class SessionWorkspaceProject(BaseModel):
    """AgentSession scoped Project domain model."""

    id: str = Field(description="Project ID")
    session_id: str = Field(description="AgentSession ID")
    path: str = Field(description="Absolute path under /workspace/agent")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class SessionWorkspaceProjectCreate(BaseModel):
    """Session Workspace Project create schema."""

    session_id: str = Field(description="AgentSession ID")
    path: str = Field(description="Absolute path under /workspace/agent")
