"""Toolkit State repository data models."""

import datetime
from typing import Any

from pydantic import BaseModel, Field


class ToolkitStateRecord(BaseModel):
    """Toolkit State storage row domain model."""

    id: str = Field(description="Toolkit State ID")
    agent_id: str = Field(description="Agent ID")
    session_id: str = Field(description="AgentSession ID")
    toolkit_namespace: str = Field(description="Toolkit namespace")
    state_name: str = Field(description="State name")
    state_json: dict[str, Any] = Field(description="State JSON payload")
    schema_version: int = Field(description="Payload schema version")
    version: int = Field(description="Row version")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class ToolkitStateUpsert(BaseModel):
    """Toolkit State whole-state replace input model."""

    agent_id: str = Field(description="Agent ID")
    session_id: str = Field(description="AgentSession ID")
    toolkit_namespace: str = Field(description="Toolkit namespace")
    state_name: str = Field(description="State name")
    state_json: dict[str, Any] = Field(description="State JSON payload")
    schema_version: int = Field(description="Payload schema version")
    expected_version: int | None = Field(
        default=None,
        description="CAS expected row version. None means create-only.",
    )
