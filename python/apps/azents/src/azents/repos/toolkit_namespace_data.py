"""Toolkit namespace repository data models."""

import datetime

from pydantic import BaseModel, Field


class AgentToolkitNamespaceReservation(BaseModel):
    """One durable Agent-local Toolkit namespace reservation."""

    id: str = Field(description="Reservation ID")
    agent_id: str = Field(description="Agent ID")
    toolkit_id: str | None = Field(
        description="Active Toolkit ID, or None when retired"
    )
    base_slug: str = Field(description="Toolkit base Slug at allocation time")
    ordinal: int = Field(ge=1, description="Monotonic ordinal consumed for the base")
    namespace: str = Field(description="Final Agent-local Toolkit namespace")
    created_at: datetime.datetime = Field(description="Creation time")
