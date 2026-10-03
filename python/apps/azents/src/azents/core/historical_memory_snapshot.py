"""Historical Memory boundary snapshot contracts."""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from azents.core.enums import AgentSessionProductMode
from azents.core.historical_memory_consolidation import ConsolidationUnitKey
from azents.core.toolkit_state import ToolkitStateModel

SavedMemoryScope = Literal["agent", "user"]


def _require_aware(value: datetime.datetime) -> datetime.datetime:
    """Require one timezone-aware timestamp."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Memory snapshot timestamps must be timezone-aware.")
    return value


class SavedMemorySnapshotEntry(BaseModel):
    """One Saved Memory index entry frozen at a context boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: str = Field(min_length=32, max_length=32)
    scope: SavedMemoryScope
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    description_snapshot: str
    updated_at_snapshot: datetime.datetime
    vfs_path: str = Field(pattern=r"^azents://memory/saved/")

    _validate_updated_at = field_validator("updated_at_snapshot")(_require_aware)


class ConsolidatedMemorySnapshotEntry(BaseModel):
    """One complete immutable unit revision frozen at a context boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit: ConsolidationUnitKey
    unit_id: str = Field(min_length=32, max_length=32)
    revision_id: str = Field(min_length=32, max_length=32)
    rendered_block: str = Field(min_length=1)
    published_at: datetime.datetime

    _validate_published_at = field_validator("published_at")(_require_aware)

    @field_validator("rendered_block")
    @classmethod
    def require_whole_budget(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 10_000:
            raise ValueError(
                "Consolidated Memory block exceeds its independent budget."
            )
        return value


class MemorySnapshotConsumer(BaseModel):
    """Current root Session authority used for Memory snapshot operations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=32, max_length=32)
    agent_id: str = Field(min_length=32, max_length=32)
    workspace_id: str = Field(min_length=32, max_length=32)
    product_mode: AgentSessionProductMode
    associated_user_id: str | None = Field(min_length=32, max_length=32)
    model_input_head_event_id: str | None = Field(min_length=32, max_length=32)


class MemoryContextSnapshotState(ToolkitStateModel):
    """Saved and Historical Memory selected for one model-input boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["consolidated_memory"]
    schema_version: Literal[2]
    boundary_head_event_id: str | None = Field(
        min_length=32,
        max_length=32,
    )
    created_at: datetime.datetime
    saved_entries: list[SavedMemorySnapshotEntry]
    historical_entries: list[ConsolidatedMemorySnapshotEntry] = Field(max_length=2)

    _validate_created_at = field_validator("created_at")(_require_aware)

    @model_validator(mode="after")
    def require_distinct_units(self) -> "MemoryContextSnapshotState":
        scopes = [entry.unit.scope for entry in self.historical_entries]
        if len(scopes) != len(set(scopes)):
            raise ValueError("Consolidated Memory snapshot repeats a scope.")
        if self.historical_entries:
            first = self.historical_entries[0].unit
            if any(
                entry.unit.agent_id != first.agent_id
                or entry.unit.workspace_id != first.workspace_id
                for entry in self.historical_entries
            ):
                raise ValueError(
                    "Consolidated Memory snapshot crosses an Agent boundary."
                )
        return self
