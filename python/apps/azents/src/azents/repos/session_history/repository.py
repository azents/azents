"""Authorized transcript discovery over canonical Session events."""

import datetime
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH
from sqlalchemy.orm import aliased

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
    EventKind,
)
from azents.core.json_value import JSONValue
from azents.engine.events.conversational_tool_projection import (
    ConversationalToolProjection,
    project_conversational_tool_call,
    project_routine_notification_result,
)
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    upgrade_persisted_client_tool_payload,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.event import RDBEvent
from azents.rdb.session_capabilities import ReadSession

SEARCHABLE_KINDS = frozenset(
    {
        EventKind.USER_MESSAGE,
        EventKind.ACTION_MESSAGE,
        EventKind.EXTERNAL_CHANNEL_MESSAGE,
        EventKind.ASSISTANT_MESSAGE,
        EventKind.SCHEDULED_TASK_RESULT,
        EventKind.ROUTINE_NOTIFICATION,
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


def _decoded_json(text: sa.ColumnElement[str]) -> sa.ColumnElement[JSONValue]:
    """Guard historical string-to-JSON casts, including malformed tool payloads."""
    return sa.cast(
        sa.case(
            (sa.func.pg_input_is_valid(text, "jsonb"), text),
            else_=sa.null(),
        ),
        sa.JSON,
    )


def _conversational_tool_text() -> sa.ColumnElement[str]:
    """Project public channel messages and newly emitted Routine notices."""
    arguments = _decoded_json(RDBEvent.payload["arguments"].as_string())
    output = _decoded_json(RDBEvent.payload["output"].as_string())
    notification = aliased(RDBEvent)
    has_chat_notification = (
        sa.select(notification.id)
        .where(
            notification.session_id == RDBEvent.session_id,
            notification.reverted.is_(False),
            notification.kind == EventKind.ROUTINE_NOTIFICATION,
            notification.payload["execution_id"].as_string()
            == output["execution"]["context"]["execution_id"].as_string(),
        )
        .correlate(RDBEvent)
        .exists()
    )
    return sa.case(
        (
            sa.and_(
                RDBEvent.kind == EventKind.CLIENT_TOOL_CALL,
                RDBEvent.payload["name"].as_string() == "channel_action",
                RDBEvent.payload["wire_dialect"].as_string() == "json_function",
                arguments["mode"].as_string().is_distinct_from("ignore"),
                sa.func.json_typeof(arguments["message"]) == "string",
            ),
            arguments["message"].as_string(),
        ),
        (
            sa.and_(
                RDBEvent.kind == EventKind.CLIENT_TOOL_RESULT,
                RDBEvent.payload["name"].as_string() == "record_routine_result",
                RDBEvent.payload["status"].as_string() == "completed",
                sa.cast(output["created"], JSONB) == sa.cast(sa.literal("true"), JSONB),
                sa.cast(output["execution"]["work"]["notify"], JSONB)
                == sa.cast(sa.literal("true"), JSONB),
                sa.func.json_typeof(output["execution"]["work"]["message"]) == "string",
                ~has_chat_notification,
            ),
            output["execution"]["work"]["message"].as_string(),
        ),
        else_=sa.null(),
    )


def _output_match(
    output: sa.ColumnElement[JSONValue], pattern: str
) -> sa.ColumnElement[bool]:
    """Match text only, excluding native data, references and file metadata."""
    parts = sa.cast(
        sa.func.jsonb_path_query_array(
            output,
            sa.cast(
                '$[*] ? (@.type == "input_text" || @.type == "text" || '
                '@.type == "output_text").text',
                JSONPATH,
            ),
        ),
        sa.Text,
    )
    return sa.or_(
        sa.and_(
            sa.func.jsonb_typeof(output) == "string",
            output.as_string().ilike(pattern, escape="\\"),
        ),
        parts.ilike(pattern, escape="\\"),
    )


def _message_match(query: str, *, exclude_tools: bool) -> sa.ColumnElement[bool]:
    """Match conversation and optionally ordinary semantic tool output."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    content = RDBEvent.payload["content"]
    typed_text = sa.cast(
        sa.func.jsonb_path_query_array(RDBEvent.payload, _TEXT_PARTS_PATH),
        sa.Text,
    )
    messages = sa.and_(
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
            sa.and_(
                RDBEvent.kind == EventKind.SCHEDULED_TASK_RESULT,
                RDBEvent.payload["result"].as_string().ilike(pattern, escape="\\"),
            ),
            sa.and_(
                RDBEvent.kind == EventKind.ROUTINE_NOTIFICATION,
                content.as_string().ilike(pattern, escape="\\"),
            ),
        ),
    )
    conversation = sa.or_(
        messages, _conversational_tool_text().ilike(pattern, escape="\\")
    )
    if exclude_tools:
        return conversation
    return sa.or_(
        conversation,
        sa.and_(
            RDBEvent.kind == EventKind.CLIENT_TOOL_RESULT,
            sa.or_(
                RDBEvent.payload["name"].as_string().is_(None),
                RDBEvent.payload["name"]
                .as_string()
                .not_in(
                    (
                        "channel_action",
                        "record_routine_result",
                        "submit_scheduled_task_result",
                    )
                ),
            ),
            _output_match(RDBEvent.payload["output"], pattern),
        ),
        sa.and_(
            RDBEvent.kind == EventKind.PROVIDER_TOOL_CALL,
            _output_match(RDBEvent.payload["semantic"]["output"], pattern),
        ),
    )


class SessionHistoryRepository:
    """Read-only SQL confined to the active Agent/Workspace/owner scope."""

    async def search_roots(
        self,
        session: ReadSession,
        *,
        scope: SessionHistoryScope,
        query: str,
        exclude_tools: bool,
        limit: int,
        before: tuple[datetime.datetime, str] | None,
    ) -> SearchPage[SessionSearchHit]:
        """Discover permitted active root Sessions; never scan an arbitrary tenant."""
        visibility = RDBConversation.product_mode == AgentSessionProductMode.TEAM
        if scope.associated_user_id is not None:
            visibility = sa.or_(
                visibility,
                sa.and_(
                    RDBConversation.product_mode == AgentSessionProductMode.USER,
                    RDBConversation.associated_user_id == scope.associated_user_id,
                ),
            )
        match_id = (
            sa.select(RDBEvent.id)
            .where(
                RDBEvent.session_id == RDBAgentSession.id,
                RDBEvent.reverted.is_(False),
                _message_match(query, exclude_tools=exclude_tools),
            )
            .order_by(RDBEvent.id.desc())
            .limit(1)
            .correlate(RDBAgentSession)
            .scalar_subquery()
        )
        statement = (
            sa.select(
                RDBAgentSession,
                RDBConversation,
                match_id.label("matching_event_id") if query else sa.null(),
            )
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(
                RDBAgentSession.agent_id == scope.agent_id,
                RDBAgentSession.workspace_id == scope.workspace_id,
                RDBConversation.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                visibility,
            )
        )
        if query:
            escaped = (
                query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            statement = statement.where(
                sa.or_(
                    RDBConversation.title.ilike(pattern, escape="\\"),
                    RDBConversation.handle.ilike(pattern, escape="\\"),
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
        rows = list((await session.read_session.execute(statement)).all())
        hits = [
            SessionSearchHit(
                session_id=row.id,
                title=conversation.title,
                handle=conversation.handle,
                mode=conversation.product_mode,
                updated_at=row.updated_at,
                event_id=event_id,
            )
            for row, conversation, event_id in rows[:limit]
        ]
        return SearchPage(items=hits, has_more=len(rows) > limit)

    async def search_events(
        self,
        session: ReadSession,
        *,
        session_id: str,
        query: str,
        exclude_tools: bool,
        limit: int,
        before: str | None,
    ) -> SearchPage[EventSearchHit]:
        """Search visible messages within one independently authorized Session."""
        statement = sa.select(RDBEvent).where(
            RDBEvent.session_id == session_id,
            RDBEvent.reverted.is_(False),
            _message_match(query, exclude_tools=exclude_tools),
        )
        if before is not None:
            statement = statement.where(RDBEvent.id < before)
        rows = list(
            (
                await session.read_session.execute(
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

    async def conversation_projections(
        self,
        session: ReadSession,
        *,
        session_id: str,
        event_ids: list[str],
    ) -> dict[str, ConversationalToolProjection]:
        """Enrich a bounded page without exposing unrelated tool inputs."""
        rows = list(
            (
                await session.read_session.execute(
                    sa.select(RDBEvent).where(
                        RDBEvent.session_id == session_id,
                        RDBEvent.id.in_(event_ids),
                        RDBEvent.reverted.is_(False),
                        _conversational_tool_text().is_not(None),
                    )
                )
            ).scalars()
        )
        calls = {
            row.id: ClientToolCallPayload.model_validate(row.payload)
            for row in rows
            if row.kind is EventKind.CLIENT_TOOL_CALL
        }
        results: dict[str, ClientToolResultPayload] = {}
        if calls:
            result_rows = (
                await session.read_session.execute(
                    sa.select(RDBEvent)
                    .where(
                        RDBEvent.session_id == session_id,
                        RDBEvent.reverted.is_(False),
                        RDBEvent.kind == EventKind.CLIENT_TOOL_RESULT,
                        RDBEvent.payload["call_id"]
                        .as_string()
                        .in_([call.call_id for call in calls.values()]),
                    )
                    .order_by(RDBEvent.id)
                )
            ).scalars()
            for row in result_rows:
                result = ClientToolResultPayload.model_validate(
                    upgrade_persisted_client_tool_payload(row.kind, row.payload)
                )
                results[result.call_id] = result
        projections: dict[str, ConversationalToolProjection] = {}
        for row in rows:
            if row.id in calls:
                call = calls[row.id]
                projected = project_conversational_tool_call(
                    call, results.get(call.call_id)
                )
            else:
                projected = project_routine_notification_result(
                    ClientToolResultPayload.model_validate(row.payload)
                )
            if projected is not None and projected.text:
                projections[row.id] = projected
        return projections
