"""Docker-free contracts for API-only and executing Agent preparation."""

from dataclasses import MISSING, dataclass, fields
from inspect import signature
from unittest.mock import Mock

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.models.agent_model_selection import AgentModelSelection
from azentspublicclient.models.agent_model_selection_input import (
    AgentModelSelectionInput,
)
from azentspublicclient.models.agent_response import AgentResponse
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.llm_provider_integration_response import (
    LLMProviderIntegrationResponse,
)
from azentspublicclient.models.model_catalog_entry_list_response import (
    ModelCatalogEntryListResponse,
)
from azentspublicclient.models.model_catalog_entry_response import (
    ModelCatalogEntryResponse,
)
from azentspublicclient.models.model_execution_option_definition import (
    ModelExecutionOptionDefinition,
)
from azentspublicclient.models.selectable_model_candidate_response import (
    SelectableModelCandidateResponse,
)
from azentspublicclient.models.selectable_model_option_response import (
    SelectableModelOptionResponse,
)

from support import utils
from tests.required.public import test_per_prompt_inference_profile as profiles


@dataclass(frozen=True)
class _Boundaries:
    public: Mock
    admin: Mock
    agent_api: Mock
    runtime_profile: Mock
    runtime_start: Mock
    get: Mock
    post: Mock


@pytest.fixture
def boundaries(monkeypatch: pytest.MonkeyPatch) -> _Boundaries:
    """Replace external SDK/HTTP boundaries while running the real helpers."""
    public = Mock(spec=azentspublicclient.ApiClient)
    admin = Mock(spec=azentsadminclient.ApiClient)
    workspace = Mock(spec=utils.PublicWorkspaceV1Api)
    integration_api = Mock(spec=utils.LLMProviderIntegrationV1Api)
    integration_api.llm_provider_integration_v1_create_integration.return_value = Mock(
        spec=LLMProviderIntegrationResponse, id="integration"
    )
    agent_api = Mock(spec=utils.AgentV1Api)
    agent_api.agent_v1_create_agent.return_value = Mock(spec=AgentResponse, id="agent")
    for module, workspace_name in (
        (utils, "PublicWorkspaceV1Api"),
        (profiles, "WorkspaceV1Api"),
    ):
        monkeypatch.setattr(module, workspace_name, Mock(return_value=workspace))
        monkeypatch.setattr(
            module, "LLMProviderIntegrationV1Api", Mock(return_value=integration_api)
        )
        monkeypatch.setattr(module, "unique", Mock(return_value="unique"))
        monkeypatch.setattr(
            module,
            "authenticate_user",
            Mock(return_value=utils.AuthenticatedUser("token", "refresh", "email")),
        )
    monkeypatch.setattr(utils, "AgentV1Api", Mock(return_value=agent_api))
    monkeypatch.setattr(
        utils,
        "model_selection_from_first_candidate",
        Mock(
            return_value=AgentModelSelectionInput(
                llm_provider_integration_id="integration", model_identifier="gpt-5.5"
            )
        ),
    )
    runtime_profile = Mock(return_value="managed-profile")
    runtime_start = Mock()
    for module in (utils, profiles):
        monkeypatch.setattr(module, "create_workspace_runtime_profile", runtime_profile)
        monkeypatch.setattr(module, "start_and_wait_for_agent_runtime", runtime_start)
    response = Mock(spec=requests.Response, status_code=200)
    response.json.return_value = {"id": "primary"}
    get = Mock(return_value=response)
    post = Mock(return_value=response)
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    return _Boundaries(
        public, admin, agent_api, runtime_profile, runtime_start, get, post
    )


@pytest.mark.parametrize("execution", [False, True])
def test_agent_preparation_keeps_configuration_and_execution_boundary(
    boundaries: _Boundaries, execution: bool
) -> None:
    """Only executing preparation starts compute and submits primary init input."""
    prepare = (
        utils.create_agent_session_setup if execution else utils.create_agent_setup
    )
    result = prepare(boundaries.public, boundaries.admin, "http://server")
    assert result.agent_id == "agent"
    assert result.access_token == "token"
    boundaries.runtime_profile.assert_called_once_with(
        boundaries.public,
        token="token",
        workspace_handle="ws-file-unique",
        provider_id="system-docker",
    )
    request = boundaries.agent_api.agent_v1_create_agent.call_args.kwargs[
        "agent_create_request"
    ]
    assert request.runtime_profile_id == "managed-profile"
    assert "runtime_capability" not in request.model_dump()
    assert request.main_model_label == request.lightweight_model_label == "default"
    assert request.selectable_model_options[0].candidates[0].model_selection == (
        AgentModelSelectionInput(
            llm_provider_integration_id="integration", model_identifier="gpt-5.5"
        )
    )
    if execution:
        assert isinstance(result, utils.AgentSessionSetup)
        assert result.session_id == "primary"
        boundaries.runtime_start.assert_called_once_with(
            boundaries.public,
            token="token",
            workspace_handle="ws-file-unique",
            agent_id="agent",
        )
        boundaries.get.assert_called_once_with(
            "http://server/chat/v1/agents/agent/team-primary-session",
            headers={"Authorization": "Bearer token"},
            timeout=10,
        )
        boundaries.post.assert_called_once()
        assert boundaries.post.call_args.args == (
            "http://server/chat/v1/sessions/primary/inputs",
        )
        assert boundaries.post.call_args.kwargs["json"] == {
            "agent_id": "agent",
            "client_request_id": "e2e-utils-init-unique",
            "message": "init",
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        }
    else:
        assert isinstance(result, utils.AgentSetup)
        boundaries.runtime_start.assert_not_called()
        boundaries.get.assert_not_called()
        boundaries.post.assert_not_called()


def _profile_option(label: str, options: list[str]) -> Mock:
    """Supply declared response metadata consumed by real catalog assertions."""
    definitions = [
        ModelExecutionOptionDefinition(
            id=option,
            label=option,
            description="Supported option",
            cost_hint="Configured cost",
            control="boolean",
            exclusive_group="processing_speed" if label in {"Astra", "Sol"} else None,
        )
        for option in options
    ]
    selection = Mock(spec=AgentModelSelection, supported_execution_options=options)
    candidate = Mock(spec=SelectableModelCandidateResponse, model_selection=selection)
    return Mock(
        spec=SelectableModelOptionResponse,
        label=label,
        candidates=[candidate],
        execution_option_definitions=definitions,
    )


@pytest.mark.parametrize("execution", [False, True])
def test_profile_preparation_runs_same_catalog_contract_without_unused_start(
    monkeypatch: pytest.MonkeyPatch, boundaries: _Boundaries, execution: bool
) -> None:
    """Both paths build managed configuration and read the actual primary route."""
    configured = [
        ("Quality", "gpt-5.5", ["fast"]),
        ("Fast", "gpt-5.5-mini", []),
        ("Astra", "gpt-6-astra", ["fast", "ultrafast"]),
        ("Sol", "gpt-5.6-sol", ["fast", "ultrafast"]),
    ]
    catalog = Mock(
        spec=ModelCatalogEntryListResponse,
        entries=[
            Mock(
                spec=ModelCatalogEntryResponse,
                provider_model_identifier=identifier,
                supported_execution_options=options,
            )
            for _, identifier, options in configured
        ],
    )
    created = Mock(
        spec=AgentResponse,
        id="agent",
        selectable_model_options=[
            _profile_option(label, options) for label, _, options in configured
        ],
    )
    primary = Mock(spec=AgentSessionResponse, id="primary")
    decode = Mock(side_effect=[catalog, created, primary])
    monkeypatch.setattr(profiles, "_response_model", decode)
    prepare = (
        profiles._setup_profile_agent if execution else profiles.setup_profile_api_agent
    )
    result = prepare(
        boundaries.public, boundaries.admin, "http://server", speed_targets=True
    )
    assert result == profiles.ProfileAgentSetup("token", "agent", "primary")
    assert [call.args[1] for call in decode.call_args_list] == [
        ModelCatalogEntryListResponse,
        AgentResponse,
        AgentSessionResponse,
    ]
    boundaries.runtime_profile.assert_called_once_with(
        boundaries.public,
        token="token",
        workspace_handle="per-prompt-profile-unique",
        provider_id="system-docker",
    )
    boundaries.post.assert_called_once()
    payload = boundaries.post.call_args.kwargs["json"]
    assert payload["runtime_profile_id"] == "managed-profile"
    assert "runtime_capability" not in payload
    assert payload["main_model_label"] == "Quality"
    assert payload["lightweight_model_label"] == "Fast"
    assert [option["label"] for option in payload["selectable_model_options"]] == [
        "Quality",
        "Fast",
        "Astra",
        "Sol",
    ]
    assert boundaries.get.call_count == 2
    assert boundaries.get.call_args.args == (
        "http://server/chat/v1/agents/agent/team-primary-session",
    )
    assert boundaries.get.call_args.kwargs == {
        "headers": {"Authorization": "Bearer token"},
        "timeout": 10,
    }
    if execution:
        boundaries.runtime_start.assert_called_once_with(
            boundaries.public,
            token="token",
            workspace_handle="per-prompt-profile-unique",
            agent_id="agent",
        )
    else:
        boundaries.runtime_start.assert_not_called()


def test_execution_preparation_does_not_continue_after_runtime_failure(
    boundaries: _Boundaries,
) -> None:
    """A failed real start cannot be replaced with API-only continuation."""
    boundaries.runtime_start.side_effect = RuntimeError("Runtime start failed")
    with pytest.raises(RuntimeError, match="Runtime start failed"):
        utils.create_agent_session_setup(
            boundaries.public, boundaries.admin, "http://server"
        )
    boundaries.get.assert_not_called()
    boundaries.post.assert_not_called()


def test_agent_setup_fields_and_profile_api_options_are_required(
    boundaries: _Boundaries,
) -> None:
    """New identity fields and API option choices cannot use hidden defaults."""
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(utils.AgentSetup)
    )
    with pytest.raises(TypeError, match="speed_targets"):
        signature(profiles.setup_profile_api_agent).bind(
            boundaries.public, boundaries.admin, "http://server"
        )
