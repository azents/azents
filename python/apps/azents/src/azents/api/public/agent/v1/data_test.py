"""Agent public API data model tests."""

import pytest
from pydantic import TypeAdapter, ValidationError

from azents.core.agent import SelectableModelCandidate, SelectableModelOption
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)

from .data import (
    AgentCreateRequest,
    AgentUpdateRequest,
    SelectableModelOptionResponse,
)


def test_agent_create_request_defaults_tool_search_to_enabled() -> None:
    """Omitted Tool Search input enables it for a new Agent."""
    request = AgentCreateRequest(name="Agent")

    assert request.tool_search_enabled is True


def test_agent_create_request_preserves_explicit_tool_search_opt_out() -> None:
    """An API caller can explicitly opt a new Agent out of Tool Search."""
    request = AgentCreateRequest(name="Agent", tool_search_enabled=False)

    assert request.tool_search_enabled is False


def test_agent_requests_reject_removed_singular_model_fields() -> None:
    """Stale public v1 callers fail instead of silently losing model intent."""
    with pytest.raises(ValidationError):
        AgentCreateRequest.model_validate(
            {
                "name": "Agent",
                "model_selection": {
                    "llm_provider_integration_id": "integration-1",
                    "model_identifier": "model-1",
                },
            }
        )
    with pytest.raises(ValidationError):
        TypeAdapter(AgentUpdateRequest).validate_python(
            {
                "lightweight_model_selection": {
                    "llm_provider_integration_id": "integration-1",
                    "model_identifier": "model-1",
                }
            }
        )


def test_selectable_model_option_response_projects_provider_descriptor() -> None:
    """Public selectable options include provider-specific execution metadata."""
    selection = make_test_model_selection(model_identifier="gpt-5.5").model_copy(
        update={"supported_execution_options": [ModelExecutionOptionId.FAST]}
    )
    response = SelectableModelOptionResponse.convert_from(
        SelectableModelOption(
            label="default",
            candidates=[
                SelectableModelCandidate(
                    model_selection=selection,
                    settings=make_test_model_settings(),
                )
            ],
            subagent_enabled=True,
            subagent_guidance=None,
        )
    )

    assert response.candidates[0].model_selection.supported_execution_options == [
        ModelExecutionOptionId.FAST
    ]
    assert [definition.id for definition in response.execution_option_definitions] == [
        ModelExecutionOptionId.FAST
    ]
    assert response.execution_option_definitions[0].cost_hint == (
        "Additional OpenAI API cost may apply."
    )
