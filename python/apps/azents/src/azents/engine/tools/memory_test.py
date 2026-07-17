"""Memory tool tests."""

import json
from contextlib import asynccontextmanager
from typing import AsyncIterator, cast
from unittest.mock import ANY, AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.engine.run.types import FunctionTool
from azents.engine.tools.memory import make_search_memories_tool
from azents.rdb.session import SessionManager
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import MemorySearchMatch, MemorySummary


@asynccontextmanager
async def _session_context() -> AsyncIterator[AsyncSession]:
    """Provide a mock database session."""
    yield cast(AsyncSession, AsyncMock())


def _make_tool(repo: AsyncMock) -> FunctionTool:
    """Create a search_memories tool with mocked dependencies."""
    return make_search_memories_tool(
        repo=cast(MemoryRepository, repo),
        agent_id="agent-1",
        user_id="user-1",
        session_manager=cast(SessionManager[AsyncSession], _session_context),
    )


class TestSearchMemoriesTool:
    """search_memories fallback behavior tests."""

    async def test_returns_exact_matches_without_partial_search(self) -> None:
        """Exact all-term matches preserve the existing concise output."""
        repo = AsyncMock(spec=MemoryRepository)
        repo.search.return_value = [
            MemorySummary(
                name="exact-memory",
                type="feedback",
                description="Exact description",
            )
        ]
        tool = _make_tool(repo)

        result = await tool.handler(
            json.dumps({"query": "exact memory", "scope": "user"})
        )

        assert result == ("1. **exact-memory** (feedback) — Exact description")
        repo.search.assert_awaited_once_with(
            ANY,
            agent_id="agent-1",
            user_id="user-1",
            include_agent_scope=False,
            query="exact memory",
        )
        repo.search_partial.assert_not_awaited()

    async def test_returns_ranked_partial_matches_after_exact_miss(self) -> None:
        """An exact miss returns labeled partial candidates with match counts."""
        repo = AsyncMock(spec=MemoryRepository)
        repo.search.return_value = []
        repo.search_partial.return_value = [
            MemorySearchMatch(
                name="two-terms",
                type="project",
                description="Two matched terms",
                matched_terms=2,
                total_terms=4,
            ),
            MemorySearchMatch(
                name="one-term",
                type="feedback",
                description="One matched term",
                matched_terms=1,
                total_terms=4,
            ),
        ]
        tool = _make_tool(repo)

        result = await tool.handler(json.dumps({"query": "one two three four"}))

        assert isinstance(result, str)
        assert result.startswith("No exact all-term match was found.")
        assert "Partial matches:" in result
        assert "**two-terms**" in result
        assert "matched 2/4 terms" in result
        assert result.index("**two-terms**") < result.index("**one-term**")
        repo.search_partial.assert_awaited_once_with(
            ANY,
            agent_id="agent-1",
            user_id="user-1",
            include_agent_scope=True,
            query="one two three four",
        )

    async def test_empty_search_result_points_to_loaded_summaries(self) -> None:
        """No lexical candidates directs the model back to the loaded index."""
        repo = AsyncMock(spec=MemoryRepository)
        repo.search.return_value = []
        repo.search_partial.return_value = []
        tool = _make_tool(repo)

        result = await tool.handler(json.dumps({"query": "missing terms"}))

        assert isinstance(result, str)
        assert 'No lexical candidates found for "missing terms".' in result
        assert "Check the loaded memory summaries" in result
        assert "creating a new memory" in result
