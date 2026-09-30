"""Docker-free preservation checks for minimal and initialized Agent setup."""

import json
from dataclasses import asdict, fields
from unittest.mock import Mock

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.models.agent_model_selection_input import (
    AgentModelSelectionInput,
)

from support import utils


def _actor() -> utils.AgentSetup:
    """Supply the same generated Workspace suffix used by the existing helper."""
    return utils.AgentSetup(
        access_token="owner-token",
        email="file-test-fixture@example.com",
        workspace_handle="ws-file-fixture",
        agent_id="agent-1",
    )


def _response(payload: dict[str, object], status: int) -> requests.Response:
    """Create an in-memory response without opening any transport."""
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(payload).encode()
    return response


def test_minimal_agent_setup_preserves_valid_creation_without_runtime_or_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the prefix's real request models run; all external boundaries are mocked."""
    public = Mock(spec=azentspublicclient.ApiClient)
    admin = Mock(spec=azentsadminclient.ApiClient)
    authentication = Mock(
        return_value=utils.AuthenticatedUser(
            access_token="owner-token",
            refresh_token="refresh-token",
            email="file-test-fixture@example.com",
        )
    )
    workspace = Mock()
    integration = Mock()
    integration.llm_provider_integration_v1_create_integration.return_value = Mock(
        id="integration-1"
    )
    agent = Mock()
    agent.agent_v1_create_agent.return_value = Mock(id="agent-1")
    selection = AgentModelSelectionInput(
        llm_provider_integration_id="integration-1", model_identifier="model-1"
    )
    catalog = Mock(return_value=selection)
    profile = Mock(return_value="profile-1")
    runtime = Mock()
    get = Mock()
    post = Mock()
    monkeypatch.setattr(utils, "unique", lambda: "fixture")
    monkeypatch.setattr(utils, "authenticate_user", authentication)
    monkeypatch.setattr(utils, "PublicWorkspaceV1Api", Mock(return_value=workspace))
    monkeypatch.setattr(
        utils, "LLMProviderIntegrationV1Api", Mock(return_value=integration)
    )
    monkeypatch.setattr(utils, "AgentV1Api", Mock(return_value=agent))
    monkeypatch.setattr(utils, "model_selection_from_first_candidate", catalog)
    monkeypatch.setattr(utils, "create_workspace_runtime_profile", profile)
    monkeypatch.setattr(utils, "start_and_wait_for_agent_runtime", runtime)
    monkeypatch.setattr(utils.http_requests, "get", get)
    monkeypatch.setattr(utils.http_requests, "post", post)

    setup = utils.create_agent_setup(public, admin, "https://public.fixture")

    assert setup == _actor()
    assert [field.name for field in fields(setup)] == [
        "access_token",
        "email",
        "workspace_handle",
        "agent_id",
    ]
    authentication.assert_called_once_with(
        public, admin, email="file-test-fixture@example.com"
    )
    workspace.workspace_v1_create_workspace.assert_called_once()
    workspace_request = workspace.workspace_v1_create_workspace.call_args.args[0]
    assert workspace_request.workspace_handle == "ws-file-fixture"
    integration.llm_provider_integration_v1_create_integration.assert_called_once()
    catalog.assert_called_once_with(
        "https://public.fixture", "owner-token", "ws-file-fixture", "integration-1"
    )
    profile.assert_called_once_with(
        public,
        token="owner-token",
        workspace_handle="ws-file-fixture",
        provider_id="system-docker",
    )
    creation = agent.agent_v1_create_agent.call_args.kwargs
    assert creation["handle"] == "ws-file-fixture"
    assert creation["_headers"] == {"Authorization": "Bearer owner-token"}
    request = creation["agent_create_request"]
    assert request.name == "File Agent fixture"
    assert request.runtime_profile_id == "profile-1"
    assert request.main_model_label == request.lightweight_model_label == "default"
    assert (
        request.selectable_model_options[0].candidates[0].model_selection == selection
    )
    runtime.assert_not_called()
    get.assert_not_called()
    post.assert_not_called()


def test_full_agent_setup_retains_start_session_and_initial_input_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The full lifecycle still runs once, in order, with identical payloads."""
    public = Mock(spec=azentspublicclient.ApiClient)
    admin = Mock(spec=azentsadminclient.ApiClient)
    minimal = Mock(return_value=_actor())
    runtime = Mock()
    get = Mock(return_value=_response({"id": "session-1"}, 200))
    post = Mock(return_value=_response({}, 200))
    trace = Mock()
    trace.attach_mock(minimal, "minimal")
    trace.attach_mock(runtime, "start")
    trace.attach_mock(get, "get")
    trace.attach_mock(post, "post")
    monkeypatch.setattr(utils, "create_agent_setup", minimal)
    monkeypatch.setattr(utils, "start_and_wait_for_agent_runtime", runtime)
    monkeypatch.setattr(utils.http_requests, "get", get)
    monkeypatch.setattr(utils.http_requests, "post", post)

    setup = utils.create_agent_session_setup(public, admin, "https://public.fixture")

    assert [item[0] for item in trace.mock_calls] == ["minimal", "start", "get", "post"]
    minimal.assert_called_once_with(public, admin, "https://public.fixture")
    runtime.assert_called_once_with(
        public,
        token="owner-token",
        workspace_handle="ws-file-fixture",
        agent_id="agent-1",
    )
    get.assert_called_once_with(
        "https://public.fixture/chat/v1/agents/agent-1/team-primary-session",
        headers={"Authorization": "Bearer owner-token"},
        timeout=10,
    )
    post.assert_called_once_with(
        "https://public.fixture/chat/v1/sessions/session-1/inputs",
        headers={
            "Authorization": "Bearer owner-token",
            "Content-Type": "application/json",
        },
        json={
            "agent_id": "agent-1",
            "client_request_id": "e2e-utils-init-fixture",
            "message": "init",
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    assert isinstance(setup, utils.AgentSessionSetup)
    assert isinstance(setup, utils.AgentSetup)
    assert asdict(setup) == {**asdict(_actor()), "session_id": "session-1"}
    assert [field.name for field in fields(setup)] == [
        "access_token",
        "email",
        "workspace_handle",
        "agent_id",
        "session_id",
    ]


@pytest.mark.parametrize("payload", [{}, {"id": None}, {"id": 123}])
def test_full_agent_setup_rejects_missing_session_before_initial_input(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    """Malformed Session identity keeps the original visible failure boundary."""
    monkeypatch.setattr(utils, "create_agent_setup", Mock(return_value=_actor()))
    monkeypatch.setattr(utils, "start_and_wait_for_agent_runtime", Mock())
    monkeypatch.setattr(
        utils.http_requests, "get", Mock(return_value=_response(payload, 200))
    )
    post = Mock()
    monkeypatch.setattr(utils.http_requests, "post", post)
    with pytest.raises(
        RuntimeError, match="Team primary session response did not include id"
    ):
        utils.create_agent_session_setup(Mock(), Mock(), "https://public.fixture")
    post.assert_not_called()


@pytest.mark.parametrize("stage", ["session", "init"])
def test_full_agent_setup_preserves_http_error_propagation(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    """An unsuccessful setup request never becomes a successful helper result."""
    monkeypatch.setattr(utils, "create_agent_setup", Mock(return_value=_actor()))
    monkeypatch.setattr(utils, "start_and_wait_for_agent_runtime", Mock())
    get = Mock(
        return_value=_response({"id": "session-1"}, 500 if stage == "session" else 200)
    )
    post = Mock(return_value=_response({}, 500))
    monkeypatch.setattr(utils.http_requests, "get", get)
    monkeypatch.setattr(utils.http_requests, "post", post)
    with pytest.raises(requests.HTTPError):
        utils.create_agent_session_setup(Mock(), Mock(), "https://public.fixture")
    if stage == "session":
        post.assert_not_called()
    else:
        post.assert_called_once()


def test_chat_session_wrapper_preserves_existing_named_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing callers still receive token, Session ID, and Agent ID."""
    public = Mock(spec=azentspublicclient.ApiClient)
    admin = Mock(spec=azentsadminclient.ApiClient)
    full = utils.AgentSessionSetup(**asdict(_actor()), session_id="session-1")
    setup = Mock(return_value=full)
    monkeypatch.setattr(utils, "create_agent_session_setup", setup)
    result = utils.create_chat_session_with_agent(
        public, admin, "https://public.fixture"
    )
    assert result == utils.AgentChatSession(
        access_token="owner-token", session_id="session-1", agent_id="agent-1"
    )
    setup.assert_called_once_with(public, admin, "https://public.fixture")
