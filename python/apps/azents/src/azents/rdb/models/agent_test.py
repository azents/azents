"""Agent RDB model tests."""

from azents.core.enums import AgentRuntimeCapability
from azents.rdb.models.agent import RDBAgent
from azents.testing.model_selection import make_test_selectable_model_option_dicts


def test_agent_constructor_preserves_complete_candidate_shape() -> None:
    """Direct constructors retain the explicit canonical candidate shape."""
    agent = RDBAgent(
        workspace_id="workspace-1",
        name="Agent",
        model_selection={"model_identifier": "main"},
        lightweight_model_selection={"model_identifier": "lightweight"},
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=({"model_identifier": "main"}),
            lightweight_model_selection=({"model_identifier": "lightweight"}),
        ),
        main_model_label="default",
        lightweight_model_label="lightweight",
    )

    assert agent.tool_search_enabled is True
    assert agent.runtime_capability is AgentRuntimeCapability.MANAGED
    assert agent.runtime_capability_version == 1
    assert agent.selectable_model_options is not None
    assert [
        option["candidates"][0]["settings"] for option in agent.selectable_model_options
    ] == [
        {
            "context_window_tokens": None,
            "max_output_tokens": None,
            "builtin_tools": [],
        },
        {
            "context_window_tokens": None,
            "max_output_tokens": None,
            "builtin_tools": [],
        },
    ]
    assert [
        (option["subagent_enabled"], option["subagent_guidance"])
        for option in agent.selectable_model_options
    ] == [(True, None), (True, None)]


def test_agent_constructor_preserves_explicit_tool_search_opt_out() -> None:
    """Direct constructors retain an explicit Tool Search opt-out."""
    agent = RDBAgent(
        workspace_id="workspace-1",
        name="Agent",
        model_selection={"model_identifier": "main"},
        lightweight_model_selection={"model_identifier": "lightweight"},
        tool_search_enabled=False,
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=({"model_identifier": "main"}),
            lightweight_model_selection=({"model_identifier": "lightweight"}),
        ),
        main_model_label="default",
        lightweight_model_label="lightweight",
    )

    assert agent.tool_search_enabled is False
