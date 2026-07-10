"""Runtime exec process tools product E2E test."""

import time
from typing import Any, cast

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from pydantic import TypeAdapter

from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
)

pytestmark = [
    pytest.mark.runtime_provider,
    pytest.mark.usefixtures("azents_runtime_provider_docker_container"),
]

_RUNTIME_PROVIDER_ID = "system-docker"
_QUICK_MESSAGE = "Runtime exec quick command"
_QUICK_CALL_ID = "call_runtime_exec_quick"
_QUICK_RESPONSE = "Runtime exec quick completed."
_QUICK_MARKER = "RUNTIME_EXEC_QUICK_MARKER"
_MISSING_MESSAGE = "Runtime exec missing process"
_MISSING_CALL_ID = "call_runtime_exec_missing"
_MISSING_RESPONSE = "Runtime exec missing process observed."
_OBJECT_DICT_ADAPTER: TypeAdapter[dict[object, object]] = TypeAdapter(
    dict[object, object]
)


def _headers(token: str) -> dict[str, str]:
    """Return bearer auth header."""
    return {"Authorization": f"Bearer {token}"}


def _object_dict(value: object) -> dict[object, object] | None:
    """Validate an external JSON object shape."""
    if not isinstance(value, dict):
        return None
    return _OBJECT_DICT_ADAPTER.validate_python(value)


def _api_host(public_api_client: azentspublicclient.ApiClient) -> str:
    """Return generated public API host string."""
    configuration = cast(Any, public_api_client).configuration
    return str(configuration.host)


def _create_shell_enabled_agent(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
) -> tuple[str, str, str]:
    """Create a workspace and shell-enabled runtime agent."""
    uniq = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"runtime-exec-{uniq}@example.com",
    )

    workspace_handle = f"runtime-exec-{uniq}"
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Runtime Exec {uniq}",
            workspace_handle=workspace_handle,
            owner_name=f"Owner {uniq}",
        ),
        _headers=_headers(token),
    )

    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=workspace_handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-runtime-exec-qa")),
        ),
        _headers=_headers(token),
    )
    model_selection = model_selection_from_first_candidate(
        _api_host(public_api_client),
        token,
        workspace_handle,
        integration.id,
    )

    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace_handle,
        agent_create_request=AgentCreateRequest(
            name=f"Runtime Exec Agent {uniq}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
            runtime_provider_id=_RUNTIME_PROVIDER_ID,
            shell_enabled=True,
        ),
        _headers=_headers(token),
    )
    return token, workspace_handle, agent.id


def _start_session(
    *,
    public_url: str,
    token: str,
    agent_id: str,
) -> str:
    """Resolve the agent team primary session id."""
    response = requests.get(
        f"{public_url}/chat/v1/agents/{agent_id}/team-primary-session",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    raw_payload: object = response.json()
    payload = _object_dict(raw_payload)
    if payload is None:
        raise AssertionError(f"Team primary response is not an object: {raw_payload!r}")
    session_id = payload.get("id")
    if not isinstance(session_id, str):
        raise AssertionError(f"Team primary response did not include id: {payload!r}")
    return session_id


def _wait_for_runtime_runner_ready(
    public_api_client: azentspublicclient.ApiClient,
    *,
    token: str,
    workspace_handle: str,
    agent_id: str,
) -> None:
    """Start and wait for a usable Runtime Runner."""
    api = AgentRuntimeV1Api(public_api_client)
    headers = _headers(token)
    api.agent_runtime_v1_start_agent_runtime(
        agent_id=agent_id,
        handle=workspace_handle,
        _headers=headers,
    )
    deadline = time.monotonic() + 120
    last_state: object | None = None
    while time.monotonic() < deadline:
        state = api.agent_runtime_v1_observe_agent_runtime(
            agent_id=agent_id,
            handle=workspace_handle,
            _headers=headers,
        )
        last_state = state
        if state.state.actions.use_runner:
            return
        time.sleep(1)
    raise AssertionError(f"runtime runner did not become ready: {last_state!r}")


def _run_message(
    *,
    public_url: str,
    token: str,
    session_id: str,
    agent_id: str,
    message: str,
) -> None:
    """Send a chat message through the REST write boundary."""
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"runtime-exec-message-{unique()}",
            "message": message,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
            },
        },
        timeout=10,
    )
    response.raise_for_status()


def _history(public_url: str, token: str, session_id: str) -> list[dict[str, object]]:
    """Fetch raw REST history events."""
    response = requests.get(
        f"{public_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    raw_payload: object = response.json()
    payload = _object_dict(raw_payload)
    if payload is None:
        raise AssertionError(f"REST history response is not an object: {raw_payload!r}")
    items = payload.get("items")
    if not isinstance(items, list):
        raise AssertionError(f"REST history items is not a list: {payload!r}")
    raw_items = cast("list[object]", items)
    return [
        cast("dict[str, object]", item) for item in raw_items if isinstance(item, dict)
    ]


def _payload(event: dict[str, object]) -> dict[object, object]:
    """Return event payload as a validated object."""
    payload = _object_dict(event.get("payload"))
    if payload is None:
        raise AssertionError(f"event payload is not an object: {event!r}")
    return payload


def _wait_for_content(
    public_url: str,
    token: str,
    session_id: str,
    content: str,
) -> None:
    """Wait for an assistant message content to appear."""
    deadline = time.monotonic() + 90
    last_events: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        last_events = _history(public_url, token, session_id)
        for event in last_events:
            if event.get("kind") != "assistant_message":
                continue
            payload = _payload(event)
            if payload.get("content") == content:
                return
        time.sleep(0.5)
    raise TimeoutError(f"assistant content not observed: {content}, {last_events!r}")


def _tool_call_names(events: list[dict[str, object]]) -> list[str]:
    """Return raw client tool call names from REST history."""
    names: list[str] = []
    for event in events:
        if event.get("kind") != "client_tool_call":
            continue
        payload = _payload(event)
        name = payload.get("name")
        if isinstance(name, str):
            names.append(name)
    return names


def _tool_result(
    events: list[dict[str, object]],
    *,
    call_id: str,
) -> dict[object, object]:
    """Return the tool result payload for a call id."""
    for event in events:
        if event.get("kind") != "client_tool_result":
            continue
        payload = _payload(event)
        if payload.get("call_id") == call_id:
            return payload
    raise AssertionError(f"tool result not found for call_id={call_id}: {events!r}")


class TestRuntimeExecProcessTools:
    """Runtime exec process product behavior."""

    def test_exec_command_and_missing_process_observation_reach_history(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Process tools replace bash and persist process metadata in history."""
        del azents_engine_worker_container
        token, workspace_handle, agent_id = _create_shell_enabled_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        session_id = _start_session(
            public_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
        )
        _wait_for_runtime_runner_ready(
            public_api_client,
            token=token,
            workspace_handle=workspace_handle,
            agent_id=agent_id,
        )

        _run_message(
            public_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            agent_id=agent_id,
            message=_QUICK_MESSAGE,
        )
        _wait_for_content(
            azents_public_server_url,
            token,
            session_id,
            _QUICK_RESPONSE,
        )
        quick_events = _history(azents_public_server_url, token, session_id)
        names = _tool_call_names(quick_events)
        assert "exec_command" in names
        assert "bash" not in names
        quick_result = _tool_result(quick_events, call_id=_QUICK_CALL_ID)
        assert quick_result.get("status") == "completed"
        quick_output = quick_result.get("output")
        assert isinstance(quick_output, str)
        assert _QUICK_MARKER in quick_output
        assert "exit_code: 0" in quick_output
        quick_metadata = _object_dict(quick_result.get("metadata"))
        assert quick_metadata is not None
        assert quick_metadata.get("kind") == "exec_command_result"
        assert quick_metadata.get("status") == "exited_unread"
        assert quick_metadata.get("exit_code") == 0
        assert "session_id" not in quick_metadata
        assert isinstance(quick_metadata.get("process_id"), str)

        _run_message(
            public_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            agent_id=agent_id,
            message=_MISSING_MESSAGE,
        )
        _wait_for_content(
            azents_public_server_url,
            token,
            session_id,
            _MISSING_RESPONSE,
        )
        missing_events = _history(azents_public_server_url, token, session_id)
        names = _tool_call_names(missing_events)
        assert "write_stdin" in names
        assert "bash" not in names
        missing_result = _tool_result(missing_events, call_id=_MISSING_CALL_ID)
        assert missing_result.get("status") == "completed"
        missing_output = missing_result.get("output")
        assert isinstance(missing_output, str)
        assert "status: missing" in missing_output
        assert "missing_reason: not_found" in missing_output
        missing_metadata = _object_dict(missing_result.get("metadata"))
        assert missing_metadata is not None
        assert missing_metadata.get("kind") == "write_stdin_result"
        assert missing_metadata.get("status") == "missing"
        assert missing_metadata.get("missing_reason") == "not_found"
