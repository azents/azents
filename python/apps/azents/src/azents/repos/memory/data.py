"""Memory repository data models."""

import datetime
import enum
from typing import Annotated

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class MemoryScope(enum.StrEnum):
    """Memory scope."""

    AGENT = "agent"
    USER = "user"


class Memory(BaseModel):
    """Memory domain model."""

    id: str = Field(description="Memory ID")
    agent_id: str = Field(description="Agent ID")
    user_id: str | None = Field(default=None, description="User ID (NULL=agent scope)")
    scope: MemoryScope = Field(description="Scope")
    type: str = Field(description="Type (free-form string)")
    name: str = Field(description="Memory identifier")
    description: str = Field(description="One-line summary")
    content: str = Field(description="Memory body")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class MemoryCreate(BaseModel):
    """Memory create input."""

    scope: MemoryScope = Field(description="Scope")
    type: str = Field(description="Type (free-form string)")
    name: str = Field(description="Memory identifier")
    description: str = Field(description="One-line summary")
    content: str = Field(description="Memory body")


class MemoryUpdate(TypedDict, total=False):
    """Memory update input."""

    type: Annotated[str, Field(description="Type (free-form string)")]
    name: Annotated[str, Field(description="Memory identifier")]
    description: Annotated[str, Field(description="One-line summary")]
    content: Annotated[str, Field(description="Memory body")]


class MemorySummary(BaseModel):
    """Lightweight model for index injection."""

    name: str = Field(description="Memory identifier")
    type: str = Field(description="Type")
    description: str = Field(description="One-line summary")
