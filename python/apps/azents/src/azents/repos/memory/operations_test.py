"""Completed Engine Memory operation tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionKind, AgentSessionProductMode
from azents.core.memory_scope import MemoryScope
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.tooling.toolkit_state_test import _create_agent_and_session
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.goal.store import GoalStateStore
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import MemoryCreate, MemorySummary
from azents.repos.memory.operations import MemoryOperationRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError


async def test_shared_memory_and_goal_events_reject_obsolete_owner_mutation(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Private state stays plain; shared content/Event writes use exact owners."""
    sessions = AgentSessionRepository()
    async with rdb_session_manager() as session:
        fixture = await _create_agent_and_session(session, "critical-tool-owner")
        current = await sessions.get_by_id(session, fixture.agent_session_id)
        assert current is not None
        owner = SessionExecutionOwner(current.id, current.owner_generation)
    memory = MemoryOperationRepository(
        session_manager=rdb_session_manager,
        memory_repository=MemoryRepository(),
        agent_session_repository=sessions,
        owner=owner,
    )
    goal = GoalStateStore(session_manager=rdb_session_manager, owner=owner)
    stored = MemoryCreate(
        scope=MemoryScope.AGENT,
        type="feedback",
        name="current",
        description="Current rule",
        content="Current owned content.",
    )
    await memory.save(agent_id=fixture.agent_id, user_id=None, create=stored)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == owner.session_id)
            .values(owner_generation=owner.owner_generation + 1)
        )
    assert (
        await memory.get(agent_id=fixture.agent_id, user_id=None, name=stored.name)
        is not None
    )
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await memory.save(
            agent_id=fixture.agent_id,
            user_id=None,
            create=stored.model_copy(update={"content": "Obsolete content"}),
        )
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await memory.delete(agent_id=fixture.agent_id, user_id=None, name=stored.name)
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await goal.append_briefing_event(
            fixture.agent_session_id,
            objective="Obsolete result",
            created_at="2026-10-05T00:00:00Z",
            completed_at="2026-10-05T00:01:00Z",
            duration_seconds=60,
        )
    current_memory = await memory.get(
        agent_id=fixture.agent_id, user_id=None, name=stored.name
    )
    assert current_memory is not None
    assert current_memory.content == stored.content
    private = await goal.create(
        agent_id=fixture.agent_id,
        session_id=fixture.agent_session_id,
        objective="Private descriptive state",
        updated_at="2026-10-05T00:02:00Z",
    )
    assert private.objective == "Private descriptive state"


async def test_memory_operations_close_transactions_before_returning() -> None:
    """Memory results return only after their repository transaction closes."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    transaction_active = False

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
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
        current_session: WriteSession,
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
        owner=None,
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
