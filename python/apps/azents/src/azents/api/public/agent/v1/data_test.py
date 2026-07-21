"""Agent public API data model tests."""

from .data import AgentCreateRequest


def test_agent_create_request_defaults_tool_search_to_enabled() -> None:
    """Omitted Tool Search input enables it for a new Agent."""
    request = AgentCreateRequest(name="Agent")

    assert request.tool_search_enabled is True


def test_agent_create_request_preserves_explicit_tool_search_opt_out() -> None:
    """An API caller can explicitly opt a new Agent out of Tool Search."""
    request = AgentCreateRequest(name="Agent", tool_search_enabled=False)

    assert request.tool_search_enabled is False
