"""Authorized transcript discovery over canonical Session events."""

import datetime
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
    EventKind,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import JSONValue, RDBEvent

SEARCHABLE_KINDS = frozenset(
    {
        EventKind.USER_MESSAGE,
        EventKind.ACTION_MESSAGE,
        EventKind.EXTERNAL_CHANNEL_MESSAGE,
        EventKind.ASSISTANT_MESSAGE,
    }
)
VISIBLE_KINDS = SEARCHABLE_KINDS | frozenset(
    {
        EventKind.CLIENT_TOOL_CALL,
        EventKind.CLIENT_TOOL_RESULT,
        EventKind.PROVIDER_TOOL_CALL,
    }
)
_TEXT_PARTS_PATH = sa.cast(
    '$.content[*] ? (@.type == "input_text" || @.type == "text" || '
    '@.type == "output_text").text',
    JSONPATH,
)


@dataclass(frozen=True)
class SessionHistoryScope:
    """Bound execution scope, never supplied by the model."""

    agent_id: str
    workspace_id: str
    associated_user_id: str | None


@dataclass(frozen=True)
class SessionSearchHit:
    """Minimal root Session discovery result."""

    session_id: str
    title: str | None
    handle: str
    mode: AgentSessionProductMode
    updated_at: datetime.datetime
    event_id: str | None


@dataclass(frozen=True)
class EventSearchHit:
    """One matching message location within an authorized Session."""

    event_id: str
    kind: EventKind
    payload: dict[str, JSONValue]
    created_at: datetime.datetime


@dataclass(frozen=True)
class SearchPage[T]:
    """Bounded search result with a continuation value."""

    items: list[T]
    has_more: bool


def _message_match(query: str) -> sa.ColumnElement[bool]:
    """Match only semantic conversation text, never file or tool metadata."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    content = RDBEvent.payload["content"]
    typed_text = sa.cast(
        sa.func.jsonb_path_query_array(RDBEvent.payload, _TEXT_PARTS_PATH),
        sa.Text,
    )
    return sa.and_(
        RDBEvent.kind.in_(SEARCHABLE_KINDS),
        sa.or_(
            sa.and_(
                RDBEvent.kind.in_(
                    (EventKind.USER_MESSAGE, EventKind.ASSISTANT_MESSAGE)
                ),
                sa.or_(
                    sa.and_(
                        sa.func.jsonb_typeof(content) == "string",
                        content.as_string().ilike(pattern, escape="\\"),
                    ),
                    typed_text.ilike(pattern, escape="\\"),
                ),
            ),
            sa.and_(
                RDBEvent.kind == EventKind.ACTION_MESSAGE,
                RDBEvent.payload["message"].as_string().ilike(pattern, escape="\\"),
            ),
            sa.and_(
                RDBEvent.kind == EventKind.EXTERNAL_CHANNEL_MESSAGE,
                RDBEvent.payload["body"].as_string().ilike(pattern, escape="\\"),
            ),
        ),
    )


class SessionHistoryRepository:
    """Read-only SQL confined to the active Agent/Workspace/owner scope."""

    async def search_roots(
        self,
        session: AsyncSession,
        *,
        scope: SessionHistoryScope,
        query: str,
        limit: int,
        before: tuple[datetime.datetime, str] | None,
    ) -> SearchPage[SessionSearchHit]:
        """Discover permitted active root Sessions; never scan an arbitrary tenant."""
        visibility = RDBAgentSession.product_mode == AgentSessionProductMode.TEAM
        if scope.associated_user_id is not None:
            visibility = sa.or_(
                visibility,
                sa.and_(
                    RDBAgentSession.product_mode == AgentSessionProductMode.USER,
                    RDBAgentSession.associated_user_id == scope.associated_user_id,
                ),
            )
        match_id = (
            sa.select(RDBEvent.id)
            .where(
                RDBEvent.session_id == RDBAgentSession.id,
                RDBEvent.reverted.is_(False),
                _message_match(query),
            )
            .order_by(RDBEvent.id.desc())
            .limit(1)
            .correlate(RDBAgentSession)
            .scalar_subquery()
        )
        statement = sa.select(
            RDBAgentSession,
            match_id.label("matching_event_id") if query else sa.null(),
        ).where(
            RDBAgentSession.agent_id == scope.agent_id,
            RDBAgentSession.workspace_id == scope.workspace_id,
            RDBAgentSession.session_kind == AgentSessionKind.ROOT,
            RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            visibility,
        )
        if query:
            escaped = (
                query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            statement = statement.where(
                sa.or_(
                    RDBAgentSession.title.ilike(pattern, escape="\\"),
                    RDBAgentSession.handle.ilike(pattern, escape="\\"),
                    match_id.is_not(None),
                )
            )
        if before is not None:
            updated_at, session_id = before
            statement = statement.where(
                sa.or_(
                    RDBAgentSession.updated_at < updated_at,
                    sa.and_(
                        RDBAgentSession.updated_at == updated_at,
                        RDBAgentSession.id < session_id,
                    ),
                )
            )
        statement = statement.order_by(
            RDBAgentSession.updated_at.desc(), RDBAgentSession.id.desc()
        ).limit(limit + 1)
        rows = list((await session.execute(statement)).all())
        hits = [
            SessionSearchHit(
                session_id=row.id,
                title=row.title,
                handle=row.handle,
                mode=row.product_mode,
                updated_at=row.updated_at,
                event_id=event_id,
            )
            for row, event_id in rows[:limit]
        ]
        return SearchPage(items=hits, has_more=len(rows) > limit)

    async def search_events(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        query: str,
        limit: int,
        before: str | None,
    ) -> SearchPage[EventSearchHit]:
        """Search visible messages within one independently authorized Session."""
        statement = sa.select(RDBEvent).where(
            RDBEvent.session_id == session_id,
            RDBEvent.reverted.is_(False),
            _message_match(query),
        )
        if before is not None:
            statement = statement.where(RDBEvent.id < before)
        rows = list(
            (
                await session.execute(
                    statement.order_by(RDBEvent.id.desc()).limit(limit + 1)
                )
            ).scalars()
        )
        return SearchPage(
            items=[
                EventSearchHit(
                    event_id=row.id,
                    kind=row.kind,
                    payload=row.payload,
                    created_at=row.created_at,
                )
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )
