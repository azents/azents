"""Historical Memory settings service contracts."""

import dataclasses
import datetime

from pydantic import BaseModel, ConfigDict
from typing_extensions import Self

from azents.core.historical_memory_settings import HistoricalMemorySettingsScope
from azents.repos.historical_memory.settings_data import (
    HistoricalMemorySettingsPage,
    HistoricalMemorySettingsRecord,
)


class HistoricalMemorySettingsOutput(BaseModel):
    """One Historical Memory settings response item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_session_id: str
    scope: HistoricalMemorySettingsScope
    source_title: str | None
    source_activity_through: datetime.datetime
    prepared_at: datetime.datetime
    summary: str

    @classmethod
    def convert_from(cls, data: HistoricalMemorySettingsRecord) -> Self:
        """Convert the repository contract to a service output."""
        return cls(
            source_session_id=data.source_session_id,
            scope=data.scope,
            source_title=data.source_title,
            source_activity_through=data.source_activity_through,
            prepared_at=data.prepared_at,
            summary=data.summary,
        )


class HistoricalMemorySettingsListOutput(BaseModel):
    """One Historical Memory settings page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[HistoricalMemorySettingsOutput, ...]
    next_cursor: str | None

    @classmethod
    def convert_from(cls, data: HistoricalMemorySettingsPage) -> Self:
        """Convert a repository page to the service response."""
        return cls(
            items=tuple(
                HistoricalMemorySettingsOutput.convert_from(item) for item in data.items
            ),
            next_cursor=data.next_cursor,
        )


@dataclasses.dataclass(frozen=True)
class HistoricalMemorySettingsNotFound:
    """The requested Historical Memory source is not currently visible."""

    source_session_id: str


@dataclasses.dataclass(frozen=True)
class HistoricalMemorySettingsCursorInvalid:
    """The supplied Historical Memory settings cursor is invalid."""

    message: str
