"""Read-only retained Session diagnostic projections for the Admin service."""

import dataclasses
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy.orm import lazyload

from azents.core.enums import EventKind
from azents.core.session_diagnostics import (
    SessionDiagnosticEvent,
    SessionDiagnosticEventPage,
    SessionDiagnosticFile,
    SessionDiagnosticMetadata,
)
from azents.engine.events.historical_memory_projection import (
    project_historical_memory_event,
)
from azents.engine.events.sensitive_text import redact_sensitive_text
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionSummaryPayload,
    Event,
    SystemReminderPayload,
    validate_persisted_event_payload,
)
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.session_execution_file import RDBSessionExecutionFile
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession

_DIAGNOSTIC_FILE_TOOLS = frozenset(
    {"read", "grep", "glob", "write", "edit", "delete", "apply_patch", "submit_memory"}
)
_EXCLUDED_KINDS = frozenset({EventKind.REASONING, EventKind.UNKNOWN_ADAPTER_OUTPUT})
_EVENT_FIELD_CHARS = 65_536


def project_diagnostic_event(row: RDBEvent) -> SessionDiagnosticEvent:
    """Render typed canonical data while omitting native artifacts and hidden state."""
    event = Event(
        id=row.id,
        session_id=row.session_id,
        kind=row.kind,
        payload=validate_persisted_event_payload(row.kind, row.payload),
        created_at=row.created_at,
    )
    payload = event.payload
    if isinstance(payload, SystemReminderPayload):
        text = redact_sensitive_text(payload.text)
    elif isinstance(payload, CompactionSummaryPayload):
        text = redact_sensitive_text(payload.content)
    else:
        projection = project_historical_memory_event(event)
        text = None if projection is None else projection.text
    name: str | None = None
    call_id: str | None = None
    status: str | None = None
    arguments: str | None = None
    arguments_omitted = False
    if isinstance(payload, ClientToolCallPayload):
        name = payload.name
        call_id = payload.call_id
        if payload.name in _DIAGNOSTIC_FILE_TOOLS:
            arguments = redact_sensitive_text(payload.arguments)
        else:
            arguments_omitted = True
            text = f"[Client tool]\n{payload.name} (arguments omitted)"
    elif isinstance(payload, ClientToolResultPayload):
        name = payload.name
        call_id = payload.call_id
        status = payload.status
    truncated = (text is not None and len(text) > _EVENT_FIELD_CHARS) or (
        arguments is not None and len(arguments) > _EVENT_FIELD_CHARS
    )
    return SessionDiagnosticEvent(
        event_id=row.id,
        kind=row.kind,
        created_at=row.created_at,
        reverted=row.reverted,
        text=None if text is None else text[:_EVENT_FIELD_CHARS],
        tool_name=name,
        call_id=call_id,
        tool_status=status,
        arguments=None if arguments is None else arguments[:_EVENT_FIELD_CHARS],
        arguments_omitted=arguments_omitted,
        truncated=truncated or (text is not None and "... [truncated]" in text),
    )


@dataclasses.dataclass(frozen=True)
class SessionDiagnosticRepository:
    """Complete scoped diagnostic reads without mutation or Conversation lookup."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def metadata(
        self, *, session_id: str, workspace_id: str
    ) -> SessionDiagnosticMetadata | None:
        """Read exact common identity, including archived retained executions."""
        async with self.session_manager() as session:
            row = await session.read_session.scalar(
                sa.select(RDBAgentSession)
                .options(lazyload(RDBAgentSession.conversation))
                .where(
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.workspace_id == workspace_id,
                )
            )
            if row is None:
                return None
            return SessionDiagnosticMetadata(
                session_id=row.id,
                agent_id=row.agent_id,
                workspace_id=row.workspace_id,
                lifecycle_root_session_id=row.lifecycle_root_session_id,
                status=row.status,
                run_state=row.run_state,
                owner_generation=row.owner_generation,
                created_at=row.created_at,
                started_at=row.started_at,
                ended_at=row.ended_at,
                archived_at=row.archived_at,
                purge_after=row.purge_after,
                archive_retention_days=row.archive_retention_days_snapshot,
            )

    async def events(
        self,
        *,
        session_id: str,
        workspace_id: str,
        after: str | None,
        limit: int,
    ) -> SessionDiagnosticEventPage | None:
        """Page safe canonical records, preserving their reverted marker."""
        async with self.session_manager() as session:
            exists = await session.read_session.scalar(
                sa.select(RDBAgentSession.id).where(
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.workspace_id == workspace_id,
                )
            )
            if exists is None:
                return None
            query = (
                sa.select(RDBEvent)
                .where(
                    RDBEvent.session_id == session_id,
                    RDBEvent.kind.not_in(_EXCLUDED_KINDS),
                )
                .order_by(RDBEvent.id)
                .limit(limit + 1)
            )
            if after is not None:
                query = query.where(RDBEvent.id > after)
            rows = list(await session.read_session.scalars(query))
            more = len(rows) > limit
            rows = rows[:limit]
            return SessionDiagnosticEventPage(
                items=[project_diagnostic_event(row) for row in rows],
                next_cursor=rows[-1].id if more else None,
            )

    async def file(
        self,
        *,
        session_id: str,
        workspace_id: str,
        path: str,
        offset: int,
        limit: int,
    ) -> SessionDiagnosticFile | None:
        """Read a bounded slice of one retained current file under exact scope."""
        async with self.session_manager() as session:
            row = (
                await session.read_session.execute(
                    sa.select(
                        RDBSessionExecutionFile.writable,
                        RDBSessionExecutionFile.content,
                    )
                    .join(
                        RDBAgentSession,
                        RDBAgentSession.id == RDBSessionExecutionFile.session_id,
                    )
                    .where(
                        RDBSessionExecutionFile.session_id == session_id,
                        RDBSessionExecutionFile.path == path,
                        RDBAgentSession.workspace_id == workspace_id,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            writable, content = row
            safe_content = redact_sensitive_text(content)
            page = safe_content[offset : offset + limit]
            next_offset = offset + len(page)
            return SessionDiagnosticFile(
                path=path,
                writable=writable,
                content=page,
                next_offset=next_offset if next_offset < len(safe_content) else None,
            )
