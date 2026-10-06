"""Bounded cursor pages for human-facing Saved Memory lists."""

import base64
import binascii

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, ValidationError

from azents.rdb.models.memory import RDBAgentMemory
from azents.rdb.session_capabilities import ReadSession
from azents.repos.memory import MemoryRepository, _make_search_filter
from azents.repos.memory.data import Memory


class MemoryUICursorError(ValueError):
    """The cursor is malformed or belongs to a different list."""


class MemoryUIPage(BaseModel):
    """One bounded Saved Memory page and its continuation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[Memory, ...]
    next_cursor: str | None


class _MemoryUICursor(BaseModel):
    """List identity and the exclusive stable continuation position."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str
    user_id: str | None
    type_filter: str | None
    query: str | None
    memory_type: str
    name: str
    memory_id: str


def _decode_cursor(value: str) -> _MemoryUICursor:
    try:
        payload = base64.b64decode(
            (value + "=" * (-len(value) % 4)).encode("ascii"),
            altchars=b"-_",
            validate=True,
        ).decode("utf-8")
        return _MemoryUICursor.model_validate_json(payload)
    except (
        binascii.Error,
        UnicodeEncodeError,
        UnicodeDecodeError,
        ValidationError,
    ) as error:
        raise MemoryUICursorError("Saved Memory cursor is invalid.") from error


async def list_memory_page(
    session: ReadSession,
    *,
    repository: MemoryRepository,
    agent_id: str,
    user_id: str | None,
    type: str | None,
    query: str | None,
    cursor: str | None,
    limit: int,
) -> MemoryUIPage:
    """Read only a page plus lookahead in one exact Saved scope."""
    if not 1 <= limit <= 100:
        raise ValueError("Saved Memory page limit must be between 1 and 100.")
    normalized_query = query.strip() if query is not None else None
    if normalized_query == "":
        normalized_query = None
    position = _decode_cursor(cursor) if cursor is not None else None
    if position is not None and (
        position.agent_id != agent_id
        or position.user_id != user_id
        or position.type_filter != type
        or position.query != normalized_query
    ):
        raise MemoryUICursorError("Saved Memory cursor belongs to another list.")
    statement = sa.select(RDBAgentMemory).where(
        RDBAgentMemory.agent_id == agent_id,
        RDBAgentMemory.user_id.is_not_distinct_from(user_id),
    )
    if type is not None:
        statement = statement.where(RDBAgentMemory.type == type)
    if normalized_query is not None:
        statement = statement.where(_make_search_filter(normalized_query))
    if position is not None:
        statement = statement.where(
            sa.tuple_(RDBAgentMemory.type, RDBAgentMemory.name, RDBAgentMemory.id)
            > sa.tuple_(
                sa.literal(position.memory_type),
                sa.literal(position.name),
                sa.literal(position.memory_id),
            )
        )
    statement = statement.order_by(
        RDBAgentMemory.type, RDBAgentMemory.name, RDBAgentMemory.id
    ).limit(limit + 1)
    rows = list((await session.read_session.scalars(statement)).all())
    items = tuple(repository._build(row) for row in rows[:limit])
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        payload = _MemoryUICursor(
            agent_id=agent_id,
            user_id=user_id,
            type_filter=type,
            query=normalized_query,
            memory_type=last.type,
            name=last.name,
            memory_id=last.id,
        ).model_dump_json()
        next_cursor = (
            base64.urlsafe_b64encode(payload.encode("utf-8")).decode().rstrip("=")
        )
    return MemoryUIPage(items=items, next_cursor=next_cursor)
