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

### Memory Write Rules

Types of memory
What NOT to save
Use save_memory and delete_memory.
Scope selection
"""


async def _collect_memory_prompt(
    repo: AsyncMock,
    session: AsyncMock,
    agent_id: str,
    user_id: str,
) -> str:
    """Collect memory prompt with root-session read/write rules."""
    return await builtin_module.collect_memory_prompt(
        repo,
        session,
        agent_id,
        user_id,
        _full_memory_rules_prompt(),
    )


class TestCollectMemoryPrompt:
    """collect_memory_prompt tests."""

    def _make_repo(
        self,
        agent_summaries: list[MemorySummary] | None = None,
        user_summaries: list[MemorySummary] | None = None,
    ) -> AsyncMock:
        """Create mock repo with return values by agent/user scope."""
        repo = AsyncMock()

        async def _list_summaries(
            session: object,  # noqa: ARG001
            *,
            agent_id: str,  # noqa: ARG001
            user_id: str | None,
            type: str | None = None,  # noqa: ARG001
        ) -> list[MemorySummary]:
            if user_id is None:
                return agent_summaries or []
            return user_summaries or []

        repo.list_summaries = _list_summaries
        return repo

    async def test_no_memories_returns_rules_only(self) -> None:
        """Rules are returned even when memory is absent."""
        repo = self._make_repo()
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag", "u")
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
        result = await _collect_memory_prompt(repo, session, "ag", "")
        assert "Agent Memories (shared with all users)" in result
        assert "no-mock" in result
        assert "No mocking in tests" in result

    async def test_user_memories_included(self) -> None:
        """User memory is included in prompt."""
        repo = self._make_repo(
            user_summaries=[
                _make_summary("profile", "user", "Go expert, React beginner"),
            ],
        )
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag", "u")
        assert "Your Memories about this User" in result
        assert "profile" in result
        assert "Go expert" in result

    async def test_both_scopes_included(self) -> None:
        """Both agent and user memory are included in prompt."""
        repo = self._make_repo(
            agent_summaries=[
                _make_summary("deploy", "reference", "CI/CD pipeline"),
            ],
            user_summaries=[
                _make_summary("profile", "user", "Senior engineer"),
            ],
        )
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag", "u")
        assert "Agent Memories" in result
        assert "Your Memories about this User" in result
        assert "deploy" in result
        assert "profile" in result

    async def test_no_agent_id_skips_agent_section(self) -> None:
        """Omit Agent Memories section when agent_id is empty."""
        repo = self._make_repo(
            agent_summaries=[_make_summary("x")],
        )
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "", "u")
        assert "Agent Memories" not in result
        assert "Memory Rules" in result

    async def test_no_user_id_skips_user_section(self) -> None:
        """Omit User Memories section when user_id is empty."""
        repo = self._make_repo(
            user_summaries=[_make_summary("x")],
        )
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag", "")
        assert "Your Memories about this User" not in result
        assert "Memory Rules" in result

    async def test_agent_section_before_user_section(self) -> None:
        """Agent Memories are displayed before User Memories."""
        repo = self._make_repo(
            agent_summaries=[_make_summary("a")],
            user_summaries=[_make_summary("b")],
        )
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag", "u")
        agent_pos = result.index("Agent Memories")
        user_pos = result.index("Your Memories about this User")
        assert agent_pos < user_pos

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
        result = await _collect_memory_prompt(repo, session, "ag", "")
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
        result = await _collect_memory_prompt(repo, session, "ag", "")
        assert "cleaning up old memories" in result.lower()

    @pytest.mark.parametrize(
        "expected",
        [
            "Types of memory",
            "What NOT to save",
            "save_memory",
            "delete_memory",
            "Scope selection",
        ],
        ids=[
            "memory-types",
            "save-exclusions",
            "save-tool",
            "delete-tool",
            "scope-selection",
        ],
    )
    async def test_rules_contain_key_instructions(self, expected: str) -> None:
        """Rules prompt includes core instructions."""
        repo = self._make_repo()
        session = AsyncMock()
        result = await _collect_memory_prompt(repo, session, "ag", "u")
        assert expected in result
