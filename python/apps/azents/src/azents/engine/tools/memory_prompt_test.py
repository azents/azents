"""Memory prompt injection tests (DB-based)."""

from unittest.mock import AsyncMock

import pytest

from azents.engine.tools import builtin as builtin_module
from azents.repos.memory.data import MemorySummary


def _make_summary(
    name: str,
    type: str = "feedback",
    description: str = "test description",
) -> MemorySummary:
    return MemorySummary(name=name, type=type, description=description)


def _full_memory_rules_prompt() -> str:
    """Return the root-session memory rules prompt."""
    return """### Memory Rules

Use list_memories, get_memory, and search_memories.
Do not pass the full user sentence.
Types of memory
Scope selection

### Memory Write Rules

What NOT to save
Use save_memory and delete_memory.
"""


async def _collect_memory_prompt(
    repo: AsyncMock,
    session: AsyncMock,
    agent_id: str,
) -> str:
    """Collect Agent-scope Memory prompt with root-session rules."""
    return await builtin_module.collect_memory_prompt(
        repo,
        session,
        agent_id,
        _full_memory_rules_prompt(),
    )


class TestCollectMemoryPrompt:
    """collect_memory_prompt tests."""

    def _make_repo(
        self,
        agent_summaries: list[MemorySummary] | None = None,
    ) -> AsyncMock:
        """Create mock repo returning Team-visible Agent Memory."""
        repo = AsyncMock()

        async def _list_summaries(
            session: object,  # noqa: ARG001
            *,
            agent_id: str,  # noqa: ARG001
            user_id: str | None,
            type: str | None = None,  # noqa: ARG001
        ) -> list[MemorySummary]:
            assert user_id is None
            return agent_summaries or []

        repo.list_summaries = AsyncMock(side_effect=_list_summaries)
        return repo

    async def test_no_memories_returns_rules_only(self) -> None:
        """Rules are returned even when memory is absent."""
        repo = self._make_repo()
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag")
        assert "Memory Rules" in result
        assert "Agent Memories" not in result
        assert "Your Memories about this User" not in result

    async def test_agent_memories_included(self) -> None:
        """Agent memory is included in prompt."""
        repo = self._make_repo(
            agent_summaries=[
                _make_summary("no-mock", "feedback", "No mocking in tests"),
            ],
        )
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag")
        assert "Agent Memories (shared with all users)" in result
        assert "no-mock" in result
        assert "No mocking in tests" in result

    async def test_user_memory_section_is_not_projected(self) -> None:
        """Team execution never renders a User Memory prompt section."""
        repo = self._make_repo()
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag")
        assert "Your Memories about this User" not in result

    async def test_agent_scope_is_the_only_memory_scope_in_prompt(self) -> None:
        """Team prompt retains shared Agent Memory without User Memory."""
        repo = self._make_repo(
            agent_summaries=[
                _make_summary("deploy", "reference", "CI/CD pipeline"),
            ],
        )
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag")
        assert "Agent Memories" in result
        assert "deploy" in result
        assert "Your Memories about this User" not in result

    async def test_agent_scope_query_uses_no_user_id(self) -> None:
        """Agent Memory lookup explicitly uses the shared scope."""
        repo = self._make_repo(
            agent_summaries=[_make_summary("x")],
        )
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag")
        assert "Agent Memories" in result
        repo.list_summaries.assert_awaited_once_with(
            session,
            agent_id="ag",
            user_id=None,
        )

    async def test_agent_memory_section_precedes_memory_rules(self) -> None:
        """Agent Memory is injected before the model-facing rules."""
        repo = self._make_repo(
            agent_summaries=[_make_summary("a")],
        )
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag")
        agent_pos = result.index("Agent Memories")
        rules_pos = result.index("Memory Rules")
        assert agent_pos < rules_pos

    async def test_summaries_grouped_by_type(self) -> None:
        """Memories are grouped by type."""
        repo = self._make_repo(
            agent_summaries=[
                _make_summary("deploy", "reference", "CI/CD"),
                _make_summary("no-mock", "feedback", "No mocking"),
                _make_summary("infra", "reference", "Infra topology"),
            ],
        )
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag")
        assert "#### Feedback" in result
        assert "#### Reference" in result
        feedback_pos = result.index("#### Feedback")
        reference_pos = result.index("#### Reference")
        assert feedback_pos < reference_pos

    async def test_truncation_warning_at_100(self) -> None:
        """Cleanup guidance is displayed for 100 or more memories."""
        summaries = [
            _make_summary(f"mem{i}", "feedback", f"desc {i}") for i in range(100)
        ]
        repo = self._make_repo(agent_summaries=summaries)
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag")
        assert "cleaning up old memories" in result.lower()

    @pytest.mark.parametrize(
        "expected",
        [
            "Types of memory",
            "What NOT to save",
            "save_memory",
            "delete_memory",
            "Scope selection",
            "Do not pass the full user sentence",
        ],
        ids=[
            "memory-types",
            "save-exclusions",
            "save-tool",
            "delete-tool",
            "scope-selection",
            "keyword-search-guidance",
        ],
    )
    async def test_rules_contain_key_instructions(self, expected: str) -> None:
        """Rules prompt includes core instructions."""
        repo = self._make_repo()
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag")
        assert expected in result
