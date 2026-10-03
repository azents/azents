"""Completed Engine Memory operation tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionKind, AgentSessionProductMode
from azents.core.memory_scope import MemoryScope
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import MemoryCreate, MemorySummary
from azents.repos.memory.operations import MemoryOperationRepository


async def test_memory_operations_close_transactions_before_returning() -> None:
    """Memory results return only after their repository transaction closes."""
    session = AsyncMock(spec=AsyncSession)
    transaction_active = False

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        nonlocal transaction_active
        assert not transaction_active
        transaction_active = True
        try:
            yield session
        finally:
            transaction_active = False

    memory = AsyncMock(spec=MemoryRepository)
    sessions = AsyncMock(spec=AgentSessionRepository)
    summary = MemorySummary(name="rule", type="feedback", description="Use tests")

    async def list_summaries(
        current_session: AsyncSession,
        *,
        agent_id: str,
        user_id: str | None,
        type: str | None = None,
    ) -> list[MemorySummary]:
        assert transaction_active
        assert current_session is session
        assert agent_id == "agent-1"
        del user_id, type
        return [summary]

    memory.list_summaries.side_effect = list_summaries
    memory.search.return_value = []
    memory.search_partial.return_value = []
    memory.delete_by_name.return_value = True
    sessions.get_by_id.return_value = SimpleNamespace(
        session_kind=AgentSessionKind.ROOT,
        product_mode=AgentSessionProductMode.TEAM,
        associated_user_id=None,
    )
    operations = MemoryOperationRepository(
        session_manager=session_manager,
        memory_repository=memory,
        agent_session_repository=sessions,
    )

    await operations.save(
        agent_id="agent-1",
        user_id=None,
        create=MemoryCreate(
            scope=MemoryScope.AGENT,
            type="feedback",
            name="rule",
            description="Use tests",
            content="Always test.",
        ),
    )
    assert not transaction_active

    groups = await operations.load_prompt_summaries(
        agent_id="agent-1",
        user_id=None,
    )
    assert groups.agent == [summary]
    assert not transaction_active

    result = await operations.search(
        agent_id="agent-1",
        user_id=None,
        include_agent_scope=True,
        query="tests",
    )
    assert result.exact == []
    assert result.partial == []
    assert not transaction_active

    assert await operations.delete(
        agent_id="agent-1",
        user_id=None,
        name="rule",
    )
    assert not transaction_active

    assert await operations.resolve_associated_user_id(session_id="session-1") is None
    assert not transaction_active
