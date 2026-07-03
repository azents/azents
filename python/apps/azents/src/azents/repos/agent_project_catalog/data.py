"""Agent Project catalog repository data models."""

import datetime
from dataclasses import dataclass

from pydantic import BaseModel, Field

from azents.core.enums import AgentProjectCatalogStatus


class AgentProjectCatalogEntry(BaseModel):
    """Agent-scoped Project catalog entry domain model."""

    id: str = Field(description="Project catalog entry ID")
    agent_id: str = Field(description="Agent ID")
    path: str = Field(description="Absolute path under /workspace/agent")
    status: AgentProjectCatalogStatus = Field(
        description="Filesystem status projection",
    )
    status_detail: str | None = Field(
        default=None,
        description="Optional status detail or error text",
    )
    checked_at: datetime.datetime | None = Field(
        default=None,
        description="Last filesystem status check time",
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


@dataclass(frozen=True)
class AgentProjectCatalogStatusPatch:
    """Status update for an Agent Project catalog path."""

    status: AgentProjectCatalogStatus
    status_detail: str | None
    checked_at: datetime.datetime
