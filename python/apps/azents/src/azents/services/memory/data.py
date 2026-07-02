"""Memory service data models."""

import dataclasses
import datetime
from typing import Annotated

from pydantic import BaseModel, Field
from typing_extensions import Self, TypedDict

from azents.repos.memory.data import Memory, MemoryScope


class MemoryOutput(BaseModel):
    """Memory output model."""

    id: str = Field(description="Memory ID")
    agent_id: str = Field(description="Agent ID")
    user_id: str | None = Field(default=None, description="User ID")
    scope: MemoryScope = Field(description="Scope")
    type: str = Field(description="Type")
    name: str = Field(description="Memory identifier")
    description: str = Field(description="One-line summary")
    content: str = Field(description="Memory body")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def convert_from(cls, data: Memory) -> Self:
        """Convert domain model to service output."""
        return cls(
            id=data.id,
            agent_id=data.agent_id,
            user_id=data.user_id,
            scope=data.scope,
            type=data.type,
            name=data.name,
            description=data.description,
            content=data.content,
            created_at=data.created_at,
            updated_at=data.updated_at,
        )


class MemoryListOutput(BaseModel):
    """Memory list output."""

    items: list[MemoryOutput] = Field(description="Memory list")


class MemoryCreateInput(BaseModel):
    """Memory create input."""

    scope: MemoryScope = Field(description="Scope")
    type: str = Field(description="Type")
    name: str = Field(description="Memory identifier")
    description: str = Field(description="One-line summary")
    content: str = Field(description="Memory body")


class MemoryUpdateInput(TypedDict, total=False):
    """Memory update input."""

    type: Annotated[str, Field(description="Type")]
    name: Annotated[str, Field(description="Memory identifier")]
    description: Annotated[str, Field(description="One-line summary")]
    content: Annotated[str, Field(description="Memory body")]


@dataclasses.dataclass(frozen=True)
class MemoryNotFound:
    """Memory was not found or is not visible to the requester."""

    memory_id: str


@dataclasses.dataclass(frozen=True)
class DuplicateMemory:
    """Memory name already exists in the same scope."""

    agent_id: str
    user_id: str | None
    name: str
