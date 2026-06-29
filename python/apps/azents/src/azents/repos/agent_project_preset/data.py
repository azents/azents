"""Agent Project preset repository data models."""

import datetime

from pydantic import BaseModel, Field


class AgentProjectPreset(BaseModel):
    """Agent-owned Project path preset domain model."""

    id: str = Field(description="Project preset ID")
    agent_id: str = Field(description="Agent ID")
    path: str = Field(description="Absolute path under /workspace/agent")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")
