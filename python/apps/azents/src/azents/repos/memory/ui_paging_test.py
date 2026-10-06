"""Saved Memory cursor paging regressions."""

from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.memory_scope import MemoryScope
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.memory import MemoryRepository
from azents.repos.memory.__init___test import _create_agent, _create_workspace
from azents.repos.memory.data import MemoryCreate
from azents.repos.memory.ui_paging import (
    MemoryUICursorError,
    _decode_cursor,
    list_memory_page,
)


async def test_pages_reach_all_entries_beyond_one_hundred(
    rdb_session: WriteSession,
) -> None:
    workspace_id = await _create_workspace(rdb_session, "memory-ui-page-ws")
    agent_id = await _create_agent(rdb_session, workspace_id)
    repository = MemoryRepository()
    expected = []
    for index in range(137):
        row = await repository.create(
            rdb_session,
            agent_id=agent_id,
            user_id=None,
            create=MemoryCreate(
                scope=MemoryScope.AGENT,
                type="project" if index % 2 else "feedback",
                name=f"entry-{index:03}",
                description="Saved memory",
                content="Body",
            ),
        )
        expected.append(row)
    seen = []
    cursor = None
    while True:
        page = await list_memory_page(
            rdb_session,
            repository=repository,
            agent_id=agent_id,
            user_id=None,
            type=None,
            query=None,
            cursor=cursor,
            limit=20,
        )
        assert len(page.items) <= 20
        seen.extend(row.id for row in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == [
        row.id for row in sorted(expected, key=lambda m: (m.type, m.name, m.id))
    ]
    assert len(set(seen)) == 137


async def test_exact_scope_and_all_term_search_are_preserved(
    rdb_session: WriteSession,
) -> None:
    workspace_id = await _create_workspace(rdb_session, "memory-ui-scope-ws")
    agent_id = await _create_agent(rdb_session, workspace_id)
    repository = MemoryRepository()
    for user_id, name, content, kind in [
        (None, "agent-alpha", "BETA", "project"),
        ("user-one", "personal-alpha", "beta", "project"),
        ("user-two", "other-alpha", "beta", "project"),
        ("user-one", "missing-beta", "alpha", "project"),
        ("user-one", "type-alpha", "beta", "feedback"),
    ]:
        await repository.create(
            rdb_session,
            agent_id=agent_id,
            user_id=user_id,
            create=MemoryCreate(
                scope=MemoryScope.AGENT if user_id is None else MemoryScope.USER,
                type=kind,
                name=name,
                description="Search entry",
                content=content,
            ),
        )
    page = await list_memory_page(
        rdb_session,
        repository=repository,
        agent_id=agent_id,
        user_id="user-one",
        type="project",
        query="ALPHA beta",
        cursor=None,
        limit=1,
    )
    assert [row.name for row in page.items] == ["missing-beta"]
    assert page.next_cursor is not None
    for other_agent, other_user, other_type, other_query in [
        ("another-agent", "user-one", "project", "ALPHA beta"),
        (agent_id, "user-two", "project", "ALPHA beta"),
        (agent_id, "user-one", None, "ALPHA beta"),
        (agent_id, "user-one", "project", "alpha"),
    ]:
        with pytest.raises(MemoryUICursorError, match="another list"):
            await list_memory_page(
                rdb_session,
                repository=repository,
                agent_id=other_agent,
                user_id=other_user,
                type=other_type,
                query=other_query,
                cursor=page.next_cursor,
                limit=1,
            )
    second = await list_memory_page(
        rdb_session,
        repository=repository,
        agent_id=agent_id,
        user_id="user-one",
        type="project",
        query="ALPHA beta",
        cursor=page.next_cursor,
        limit=1,
    )
    assert [row.name for row in second.items] == ["personal-alpha"]
    assert second.next_cursor is None


@pytest.mark.parametrize("cursor", ["", "!bad!", "한글", "e30", "////"])
def test_malformed_cursor_rejected(cursor: str) -> None:
    with pytest.raises(MemoryUICursorError):
        _decode_cursor(cursor)


@pytest.mark.parametrize("limit", [0, -1, 101])
async def test_invalid_limit_does_not_query(limit: int) -> None:
    raw_session = AsyncMock(spec=AsyncSession)
    with pytest.raises(ValueError, match="between 1 and 100"):
        await list_memory_page(
            ReadWriteSession(raw_session),
            repository=MemoryRepository(),
            agent_id="agent",
            user_id=None,
            type=None,
            query=None,
            cursor=None,
            limit=limit,
        )
    raw_session.scalars.assert_not_awaited()


async def test_query_fetches_only_page_and_lookahead() -> None:
    raw_session = AsyncMock(spec=AsyncSession)
    rows = Mock()
    rows.all.return_value = []
    raw_session.scalars.return_value = rows
    page = await list_memory_page(
        ReadWriteSession(raw_session),
        repository=MemoryRepository(),
        agent_id="agent",
        user_id=None,
        type=None,
        query=None,
        cursor=None,
        limit=20,
    )
    assert page.items == ()
    assert page.next_cursor is None
    statement = raw_session.scalars.call_args.args[0]
    assert isinstance(statement, sa.Select)
    compiled = statement.compile(dialect=postgresql.dialect())
    assert 21 in compiled.params.values()
    assert "LIMIT" in str(compiled)
    assert "agent_memories.type, agent_memories.name, agent_memories.id" in str(
        compiled
    )
