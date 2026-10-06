"""Bounded canonical Session diagnostics without provider-private artifacts."""

import datetime

from pydantic import BaseModel, ConfigDict

from azents.core.enums import AgentSessionRunState, AgentSessionStatus, EventKind


class SessionDiagnosticMetadata(BaseModel):
    """Common retained execution metadata; no public Conversation identity."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    agent_id: str
    workspace_id: str
    lifecycle_root_session_id: str | None
    status: AgentSessionStatus
    run_state: AgentSessionRunState
    owner_generation: int
    created_at: datetime.datetime
    started_at: datetime.datetime
    ended_at: datetime.datetime | None
    archived_at: datetime.datetime | None
    purge_after: datetime.datetime | None
    archive_retention_days: int | None


class SessionDiagnosticEvent(BaseModel):
    """Safe canonical event projection, including retained reverted records."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    kind: EventKind
    created_at: datetime.datetime
    reverted: bool
    text: str | None
    tool_name: str | None
    call_id: str | None
    tool_status: str | None
    arguments: str | None
    arguments_omitted: bool
    truncated: bool


class SessionDiagnosticEventPage(BaseModel):
    """Forward cursor page of canonical diagnostic event projections."""

    model_config = ConfigDict(frozen=True)

    items: list[SessionDiagnosticEvent]
    next_cursor: str | None


class SessionDiagnosticFile(BaseModel):
    """Bounded current durable file content; not file history or restoration."""

    model_config = ConfigDict(frozen=True)

    path: str
    writable: bool
    content: str
    next_offset: int | None
