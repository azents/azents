"""Typed records for the live Memory VFS repository boundary."""

import dataclasses
import datetime
from typing import Literal, NamedTuple

from azents.engine.events.types import Event

MemoryVfsScope = Literal["agent", "team", "user"]
MemoryVfsUriNamespace = Literal["all", "readme", "saved", "historical", "sources"]
MemoryVfsSourceFileKind = Literal["session", "events", "tool-results"]


@dataclasses.dataclass(frozen=True)
class MemoryVfsAuthority:
    """Server-derived Memory VFS visibility boundary."""

    root_session_id: str
    agent_id: str
    workspace_id: str
    associated_user_id: str | None
    memory_enabled: bool


@dataclasses.dataclass(frozen=True)
class SavedMemoryVfsRecord:
    """One currently visible Saved Memory file."""

    memory_id: str
    scope: Literal["agent", "user"]
    memory_type: str
    name: str
    description: str
    content: str
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class HistoricalMemoryVfsRecord:
    """One currently visible prepared Historical Memory summary."""

    source_session_id: str
    scope: Literal["team", "user"]
    source_title: str | None
    source_activity_through: datetime.datetime
    prepared_at: datetime.datetime
    summary: str


@dataclasses.dataclass(frozen=True)
class SourceSessionVfsRecord:
    """One currently visible root Session source."""

    session_id: str
    scope: Literal["team", "user"]
    title: str | None
    handle: str
    last_activity_at: datetime.datetime
    latest_visible_event_id: str | None
    summary_available: bool


@dataclasses.dataclass(frozen=True)
class SourceEventVfsRecord:
    """One currently visible persisted source event and navigation."""

    scope: Literal["team", "user"]
    event: Event
    previous_event_id: str | None
    next_event_id: str | None
    paired_client_result: Event | None


@dataclasses.dataclass(frozen=True)
class ToolResultVfsRecord:
    """One currently visible exact persisted tool-result text."""

    scope: Literal["team", "user"]
    session_id: str
    event_id: str
    tool_name: str
    status: str
    text: str
    created_at: datetime.datetime


type MemoryVfsRecord = (
    SavedMemoryVfsRecord
    | HistoricalMemoryVfsRecord
    | SourceSessionVfsRecord
    | SourceEventVfsRecord
    | ToolResultVfsRecord
)


class MemoryVfsUriPage(NamedTuple):
    """One bounded deterministic URI page."""

    uris: tuple[str, ...]
    has_more: bool


class MemoryVfsRecordPage(NamedTuple):
    """One bounded deterministic rendered-record candidate page."""

    records: tuple[MemoryVfsRecord, ...]
    has_more: bool


@dataclasses.dataclass(frozen=True)
class MemoryVfsUriQuery:
    """Indexed URI inventory scope derived from one canonical glob pattern."""

    namespace: MemoryVfsUriNamespace
    saved_scopes: tuple[Literal["agent", "user"], ...]
    source_scopes: tuple[Literal["team", "user"], ...]
    session_id: str | None
    source_file_kinds: tuple[MemoryVfsSourceFileKind, ...]
    include_readme: bool
