"""Historical Memory settings query contracts."""

import datetime

from pydantic import BaseModel, ConfigDict, Field

from azents.core.historical_memory_settings import HistoricalMemorySettingsScope


class HistoricalMemorySettingsRecord(BaseModel):
    """One currently visible prepared Historical Memory source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_session_id: str = Field(min_length=32, max_length=32)
    scope: HistoricalMemorySettingsScope
    source_title: str | None
    source_activity_through: datetime.datetime
    prepared_at: datetime.datetime
    summary: str


class HistoricalMemorySettingsPage(BaseModel):
    """One stable cursor page of Historical Memory settings records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[HistoricalMemorySettingsRecord, ...]
    next_cursor: str | None


class HistoricalMemorySettingsCursorError(ValueError):
    """The supplied opaque Historical Memory settings cursor is invalid."""
