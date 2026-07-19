"""Agent RDB model tests."""

from azents.rdb.models.agent import RDBAgent


def test_agent_constructor_materializes_complete_selectable_model_settings() -> None:
    """Direct constructors produce the complete stored settings shape."""
    agent = RDBAgent(
        workspace_id="workspace-1",
        name="Agent",
        model_selection={"model_identifier": "main"},
        lightweight_model_selection={"model_identifier": "lightweight"},
    )

    assert agent.tool_search_enabled is False
    assert agent.selectable_model_options is not None
    assert [option["settings"] for option in agent.selectable_model_options] == [
        {
            "context_window_tokens": None,
            "max_output_tokens": None,
            "builtin_tools": [],
            "subagent_enabled": True,
            "subagent_guidance": None,
        },
        {
            "context_window_tokens": None,
            "max_output_tokens": None,
            "builtin_tools": [],
            "subagent_enabled": True,
            "subagent_guidance": None,
        },
    ]
