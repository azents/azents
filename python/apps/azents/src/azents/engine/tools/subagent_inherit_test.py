"""Subagent toolkit inherit branch logic tests."""

from azents.engine.tools.subagent import resolve_toolkit_source_agent_id
from azents.repos.agent_subagent.data import SubagentToolkitInheritMode


class TestResolveToolkitSourceAgentId:
    """``resolve_toolkit_source_agent_id`` — DP6 exclusive inherit branch tests."""

    def test_returns_parent_when_mode_all(self) -> None:
        """``mode=ALL`` returns parent_agent_id."""
        parent_id = "parent-agent-1"
        subagent_id = "subagent-1"

        result = resolve_toolkit_source_agent_id(
            toolkit_inherit_mode=SubagentToolkitInheritMode.ALL,
            parent_agent_id=parent_id,
            subagent_id=subagent_id,
        )

        assert result == parent_id

    def test_returns_subagent_when_mode_none(self) -> None:
        """``mode=NONE`` returns subagent_id."""
        parent_id = "parent-agent-1"
        subagent_id = "subagent-1"

        result = resolve_toolkit_source_agent_id(
            toolkit_inherit_mode=SubagentToolkitInheritMode.NONE,
            parent_agent_id=parent_id,
            subagent_id=subagent_id,
        )

        assert result == subagent_id
