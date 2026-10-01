"""Historical Memory boundary snapshot contracts."""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from azents.core.enums import AgentSessionProductMode
from azents.core.toolkit_state import ToolkitStateModel

SavedMemoryScope = Literal["agent", "user"]
HistoricalMemorySourceScope = Literal["team", "user"]


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


class HistoricalMemorySnapshotEntry(BaseModel):
    """One Historical Memory summary frozen at a context boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_session_id: str = Field(min_length=32, max_length=32)
    source_scope: HistoricalMemorySourceScope
    source_title_snapshot: str | None
    source_activity_through: datetime.datetime
    prepared_at: datetime.datetime
    summary_snapshot: str = Field(min_length=1)
    summary_vfs_path: str = Field(pattern=r"^azents://memory/historical/")
    source_vfs_path: str = Field(pattern=r"^azents://memory/sources/")

    _validate_source_activity = field_validator("source_activity_through")(
        _require_aware
    )
    _validate_prepared_at = field_validator("prepared_at")(_require_aware)


class HistoricalMemorySnapshotCandidate(BaseModel):
    """One currently authorized prepared source available for selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_session_id: str = Field(min_length=32, max_length=32)
    source_scope: HistoricalMemorySourceScope
    source_title: str | None
    source_activity_through: datetime.datetime
    prepared_at: datetime.datetime
    summary: str = Field(min_length=1)

    _validate_source_activity = field_validator("source_activity_through")(
        _require_aware
    )
    _validate_prepared_at = field_validator("prepared_at")(_require_aware)


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

    schema_version: int = Field(default=1, ge=1)
    boundary_head_event_id: str | None = Field(
        min_length=32,
        max_length=32,
    )
    created_at: datetime.datetime
    saved_entries: list[SavedMemorySnapshotEntry]
    historical_entries: list[HistoricalMemorySnapshotEntry]

    _validate_created_at = field_validator("created_at")(_require_aware)
