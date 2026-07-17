"""Chat input buffer product-facing E2E test."""

import json
import time
from dataclasses import dataclass

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.toolkit_v1_api import ToolkitV1Api
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_model_selection_input import (
    AgentModelSelectionInput,
)
from azentspublicclient.models.agent_toolkit_attach_request import (
    AgentToolkitAttachRequest,
)
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from pydantic import TypeAdapter, ValidationError
from testcontainers.core.container import DockerContainer

from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
)

_INITIAL_MESSAGE = "Start chat input buffer long tool"
_FOLLOW_UP_MESSAGE = "First buffered follow-up should survive"
_SECOND_FOLLOW_UP_MESSAGE = "Second buffered follow-up should preserve FIFO order"
_DELETED_MESSAGE = "Deleted pending message must not reach the model"
_EDITED_MESSAGE = "Edited user message via REST"
_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


@dataclass(frozen=True)
class _Workspace:
    """chat input buffer E2E t t t resource t."""

    token: str
    handle: str
    model_selection: AgentModelSelectionInput


@dataclass(frozen=True)
class _PendingBuffer:
    """Live event t t pending buffer projection."""

    id: str
    content: str


def _headers(token: str) -> dict[str, str]:
    """Bearer auth header t t."""
    return {"Authorization": f"Bearer {token}"}


def _setup_workspace(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
) -> _Workspace:
    """workspacet model selection t t API t t."""
    uniq = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"chat-input-buffer-{uniq}@example.com",
    )
    handle = f"chat-input-buffer-{uniq}"

    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Chat Input Buffer QA {uniq}",
            workspace_handle=handle,
            owner_name=f"Owner {uniq}",
        ),
        _headers=_headers(token),
    )
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-chat-input-buffer-qa")),
        ),
        _headers=_headers(token),
    )
    return _Workspace(
        token=token,
        handle=handle,
        model_selection=model_selection_from_first_candidate(
            server_url,
            token,
            handle,
            integration.id,
        ),
    )


def _create_agent(
    public_api_client: azentspublicclient.ApiClient,
    workspace: _Workspace,
    *,
    delay_seconds: float,
    release_file_path: str | None,
) -> str:
    """Create an agent with a controllable deterministic QA tool."""
    toolkit_api = ToolkitV1Api(public_api_client)
    toolkit = toolkit_api.toolkit_v1_create_toolkit_config(
        handle=workspace.handle,
        toolkit_config_create_request=ToolkitConfigCreateRequest(
            toolkit_type="runtime_hook_qa",
            slug="bufferqa",
            name="Chat Input Buffer QA Toolkit",
            config={
                "mode": "observe",
                "delay_seconds": delay_seconds,
                "release_file_path": release_file_path,
            },
            enabled=True,
        ),
        _headers=_headers(workspace.token),
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name="Chat Input Buffer QA Agent",
            model_selection=workspace.model_selection,
            lightweight_model_selection=workspace.model_selection,
            type=AgentType.PUBLIC,
            shell_enabled=True,
        ),
        _headers=_headers(workspace.token),
    )
    toolkit_api.toolkit_v1_attach_toolkit_to_agent(
        handle=workspace.handle,
        agent_id=agent.id,
        agent_toolkit_attach_request=AgentToolkitAttachRequest(toolkit_id=toolkit.id),
        _headers=_headers(workspace.token),
    )
    return agent.id


def _object_item(raw_item: object, *, label: str) -> dict[str, object]:
    """JSON object t verifyt returnt."""
    try:
        return _JSON_OBJECT.validate_python(raw_item)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object: {raw_item!r}") from exc


def _object_items(raw_items: object, *, label: str) -> list[dict[str, object]]:
    """JSON list[object] t verifyt returnt."""
    try:
        return _JSON_OBJECT_LIST.validate_python(raw_items)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object list: {raw_items!r}") from exc


def _response_object(
    response: requests.Response,
    *,
    label: str,
) -> dict[str, object]:
    """HTTP response body t JSON object t verifyt returnt."""
    try:
        return _JSON_OBJECT.validate_json(response.text)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object: {response.text!r}") from exc


def _post_json(
    *,
    server_url: str,
    token: str,
    path: str,
    payload: dict[str, object],
) -> dict[str, object]:
    """Public REST JSON POST responset object t returnt."""
    response = requests.post(
        f"{server_url}{path}",
        headers={**_headers(token), "Content-Type": "application/json"},
        json=payload,
        timeout=10,
    )
    response.raise_for_status()
    return _response_object(response, label=f"POST {path} response")


def _write_new_session_message(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    message: str,
    client_request_id: str,
) -> dict[str, object]:
    """t session t messaget REST write boundary t t."""
    session_response = requests.get(
        f"{server_url}/chat/v1/agents/{agent_id}/team-primary-session",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    session_response.raise_for_status()
    session_payload = _response_object(
        session_response,
        label="GET team primary session response",
    )
    session_id = session_payload.get("id")
    if not isinstance(session_id, str):
        raise AssertionError(
            f"Team primary response did not include id: {session_payload!r}"
        )
    return _post_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/sessions/{session_id}/inputs",
        payload={
            "agent_id": agent_id,
            "client_request_id": client_request_id,
            "message": message,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
            },
        },
    )


def _write_session_message(
    *,
    server_url: str,
    token: str,
    session_id: str,
    agent_id: str,
    message: str,
    client_request_id: str,
) -> dict[str, object]:
    """t session messaget REST write boundary t t."""
    return _post_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/sessions/{session_id}/inputs",
        payload={
            "agent_id": agent_id,
            "client_request_id": client_request_id,
            "message": message,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
            },
        },
    )


def _write_edit_message(
    *,
    server_url: str,
    token: str,
    session_id: str,
    agent_id: str,
    message_id: str,
    message: str,
    client_request_id: str,
) -> dict[str, object]:
    """user message t REST write boundary t t."""
    return _post_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/sessions/{session_id}/edit-message",
        payload={
            "agent_id": agent_id,
            "client_request_id": client_request_id,
            "message_id": message_id,
            "message": message,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
            },
        },
    )


def _stop_session_run(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> dict[str, object]:
    """t session run t REST control boundary t t."""
    return _post_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/sessions/{session_id}/stop",
        payload={},
    )


def _write_command(
    *,
    server_url: str,
    token: str,
    session_id: str,
    agent_id: str,
    command: str,
    client_request_id: str,
) -> dict[str, object]:
    """t t REST write boundary t t."""
    return _post_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/sessions/{session_id}/inputs",
        payload={
            "agent_id": agent_id,
            "client_request_id": client_request_id,
            "message": "",
            "action": {"type": "command", "name": command},
            "inference_profile": None,
        },
    )


def _session_id_from_write(response: dict[str, object]) -> str:
    """REST write responset session_id t t."""
    session_id = response.get("session_id")
    if not isinstance(session_id, str):
        raise AssertionError(
            f"REST write response did not include session_id: {response!r}"
        )
    return session_id


def _accepted_write(response: dict[str, object]) -> dict[str, object]:
    """REST write accepted object t t."""
    return _object_item(response.get("accepted"), label="write accepted")


def _list_history(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> dict[str, object]:
    """REST history event page t fetcht."""
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/history",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return _response_object(response, label="list history response")


def _list_live(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> dict[str, object]:
    """REST live event projection list t fetcht."""
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/live",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return _response_object(response, label="list live response")


def _assert_legacy_messages_get_removed(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> None:
    """Legacy aggregate messages GET t public surface t t t verifyt."""
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/messages",
        headers=_headers(token),
        timeout=10,
    )
    if response.status_code not in {404, 405}:
        raise AssertionError(
            f"legacy messages GET endpoint still exists: {response.text}"
        )


def _assert_split_rest_contract(
    history_payload: dict[str, object],
    live_payload: dict[str, object],
) -> None:
    """History/live response shape t verifyt.

    Legacy aggregate bootstrap shape t t t t.
    """
    assert isinstance(history_payload.get("items"), list)
    assert isinstance(history_payload.get("has_more"), bool)
    assert "next_cursor" in history_payload
    live_partial_history = _object_item(
        live_payload.get("partial_history"), label="live partial_history"
    )
    assert isinstance(live_partial_history.get("items"), list)
    assert isinstance(live_payload.get("input_buffers"), list)
    assert "items" not in live_payload
    legacy_fields = {"run_state"}
    assert legacy_fields.isdisjoint(history_payload)
    assert legacy_fields.isdisjoint(live_payload)


def _pending_buffers(payload: dict[str, object]) -> list[_PendingBuffer]:
    """Return pending user-message buffers from the live projection."""
    raw_buffers = payload.get("input_buffers")
    buffers: list[_PendingBuffer] = []
    for raw_buffer in _object_items(raw_buffers, label="live input_buffers"):
        if raw_buffer.get("kind") != "user_message":
            continue
        event_payload = _object_item(raw_buffer.get("payload"), label="live payload")
        metadata = _object_item(event_payload.get("metadata"), label="live metadata")
        if metadata.get("live_projection") != "input_buffer":
            continue
        buffer_id = raw_buffer.get("id")
        content = event_payload.get("content")
        if not isinstance(buffer_id, str) or not isinstance(content, str):
            raise AssertionError(f"invalid input buffer projection: {raw_buffer!r}")
        buffers.append(_PendingBuffer(id=buffer_id, content=content))
    return buffers


def _input_buffer_contents(payload: dict[str, object]) -> list[str]:
    """Return pending input-buffer contents from the live projection."""
    return [buffer.content for buffer in _pending_buffers(payload)]


def _run_marker_statuses(payload: dict[str, object]) -> list[str]:
    """History response t run_marker status listt returnt."""
    raw_items = payload.get("items")
    statuses: list[str] = []
    for raw_item in _object_items(raw_items, label="history items"):
        if raw_item.get("kind") != "run_marker":
            continue
        event_payload = _object_item(raw_item.get("payload"), label="history payload")
        status = event_payload.get("status")
        if isinstance(status, str):
            statuses.append(status)
    return statuses


def _message_contents(payload: dict[str, object]) -> list[str]:
    """History response t user/assistant event content listt returnt."""
    raw_items = payload.get("items")
    contents: list[str] = []
    for raw_item in _object_items(raw_items, label="history items"):
        if raw_item.get("kind") not in {"user_message", "assistant_message"}:
            continue
        event_payload = _object_item(raw_item.get("payload"), label="history payload")
        content = event_payload.get("content")
        if isinstance(content, str):
            contents.append(content)
    return contents


def _find_user_message_id(payload: dict[str, object], content: str) -> str | None:
    """History response t t user_message id t t."""
    raw_items = payload.get("items")
    for raw_item in _object_items(raw_items, label="history items"):
        if raw_item.get("kind") != "user_message":
            continue
        event_payload = _object_item(raw_item.get("payload"), label="history payload")
        if event_payload.get("content") != content:
            continue
        event_id = raw_item.get("id")
        if not isinstance(event_id, str):
            raise AssertionError(f"user_message id is not a string: {raw_item!r}")
        return event_id
    return None


def _wait_for_history_user_message_id(
    *,
    server_url: str,
    token: str,
    session_id: str,
    content: str,
    timeout: float = 120,
) -> str:
    """REST history t t user_message t t t t."""
    deadline = time.monotonic() + timeout
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        history_payload = _list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        last_payload = history_payload
        message_id = _find_user_message_id(history_payload, content)
        if message_id is not None:
            return message_id
        time.sleep(0.5)
    raise TimeoutError(f"user_message id was not observed: {content}, {last_payload!r}")


def _wait_for_interrupted_stopped_state(
    *,
    server_url: str,
    token: str,
    session_id: str,
    timeout: float = 120,
) -> dict[str, object]:
    """Wait for durable interruption and recoverable stopped live state."""
    deadline = time.monotonic() + timeout
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        history_payload = _list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        live_payload = _list_live(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        last_payload = {"history": history_payload, "live": live_payload}
        run_payload = live_payload.get("run")
        if run_payload is None:
            time.sleep(0.5)
            continue
        run = _object_item(run_payload, label="recoverable stopped run")
        recovery_payload = run.get("recovery")
        if recovery_payload is None:
            time.sleep(0.5)
            continue
        recovery = _object_item(recovery_payload, label="stopped run recovery")
        if (
            "interrupted" in _run_marker_statuses(history_payload)
            and run.get("status") == "stopped"
            and recovery.get("source_run_id") == run.get("run_id")
        ):
            return history_payload
        time.sleep(0.5)
    raise TimeoutError(f"interrupted stopped state was not observed: {last_payload!r}")


def _wait_for_idle_rest_state(
    *,
    server_url: str,
    token: str,
    session_id: str,
    expected_message: str,
    timeout: float = 120,
) -> None:
    """Wait until REST history/live both expose the completed idle state."""
    deadline = time.monotonic() + timeout
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        history_payload = _list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        live_payload = _list_live(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        last_payload = {"history": history_payload, "live": live_payload}
        _assert_split_rest_contract(history_payload, live_payload)
        if (
            expected_message in _message_contents(history_payload)
            and live_payload.get("run") is None
            and live_payload.get("session_run_state") == "idle"
        ):
            return
        time.sleep(0.5)
    raise TimeoutError(f"idle REST state was not observed: {last_payload!r}")


def _wait_for_running_rest_state(
    *,
    server_url: str,
    token: str,
    session_id: str,
    expected_message: str,
    timeout: float = 60,
) -> None:
    """REST history/live t t messaget running run t t."""
    deadline = time.monotonic() + timeout
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        history_payload = _list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        live_payload = _list_live(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        last_payload = {"history": history_payload, "live": live_payload}
        _assert_split_rest_contract(history_payload, live_payload)
        raw_run = live_payload.get("run")
        run_status = (
            _object_item(raw_run, label="live run").get("status")
            if raw_run is not None
            else None
        )
        if (
            expected_message in _message_contents(history_payload)
            and run_status == "running"
        ):
            return
        time.sleep(0.5)
    raise TimeoutError(f"running REST state was not observed: {last_payload!r}")


def _wait_for_rest_state(
    *,
    server_url: str,
    token: str,
    session_id: str,
    expected_message: str | None = None,
    expected_pending: list[str] | None = None,
    timeout: float = 120,
) -> dict[str, object]:
    """REST history/live t t statet t t polling t."""
    deadline = time.monotonic() + timeout
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        history_payload = _list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        live_payload = _list_live(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        _assert_split_rest_contract(history_payload, live_payload)
        payload: dict[str, object] = {"history": history_payload, "live": live_payload}
        last_payload = payload
        messages_match = expected_message is None or (
            expected_message in _message_contents(history_payload)
        )
        pending_match = (
            expected_pending is None
            or _input_buffer_contents(live_payload) == expected_pending
        )
        if messages_match and pending_match:
            return payload
        time.sleep(0.5)
    raise TimeoutError(f"REST state was not observed: {last_payload!r}")


def _wait_for_pending_buffer(
    *,
    server_url: str,
    token: str,
    session_id: str,
    expected: _PendingBuffer,
    timeout: float = 30,
) -> None:
    """Wait until a specific buffer remains pending in the live projection."""
    deadline = time.monotonic() + timeout
    last_buffers: list[_PendingBuffer] = []
    while time.monotonic() < deadline:
        live_payload = _list_live(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        last_buffers = _pending_buffers(live_payload)
        if expected in last_buffers:
            return
        time.sleep(0.25)
    raise TimeoutError(
        f"pending buffer was not observed: {expected!r}, {last_buffers!r}"
    )


def _container_logs(container: DockerContainer) -> str:
    """Return combined container stdout and stderr."""
    stdout, stderr = container.get_logs()
    return stdout.decode(errors="replace") + stderr.decode(errors="replace")


def _wait_for_tool_release_barrier(
    container: DockerContainer,
    release_file_path: str,
    *,
    timeout: float = 60,
) -> None:
    """Wait until the QA tool reports that it is blocked on its release file."""
    deadline = time.monotonic() + timeout
    last_logs = ""
    while time.monotonic() < deadline:
        last_logs = _container_logs(container)
        if release_file_path in last_logs:
            return
        time.sleep(0.25)
    raise TimeoutError(
        f"tool release barrier was not observed: {release_file_path}\n"
        f"{last_logs[-4000:]}"
    )


def _set_release_file(
    container: DockerContainer,
    release_file_path: str,
    *,
    present: bool,
) -> None:
    """Create or remove the QA tool release file inside the worker container."""
    command = (
        ["touch", release_file_path] if present else ["rm", "-f", release_file_path]
    )
    result = container.get_wrapped_container().exec_run(command)
    if result.exit_code != 0:
        output = result.output.decode(errors="replace")
        raise AssertionError(
            f"failed to update tool release file {release_file_path}: {output}"
        )


def _delete_input_buffer(
    *,
    server_url: str,
    token: str,
    session_id: str,
    buffer_id: str,
) -> None:
    """pending input buffer t public REST API t deletet."""
    response = requests.delete(
        f"{server_url}/chat/v1/sessions/{session_id}/input-buffers/{buffer_id}",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()


def _reset_mock_openai(mock_openai_url: str) -> None:
    """AIMock request journal t initializet."""
    requests.delete(f"{mock_openai_url}/v1/_requests", timeout=10).raise_for_status()


def _mock_openai_journal_text(mock_openai_url: str) -> str:
    """AIMock journal t JSON stringt returnt."""
    payload = requests.get(f"{mock_openai_url}/v1/_requests", timeout=10).json()
    return json.dumps(payload, ensure_ascii=False)


def _wait_for_mock_openai_journal_contains(
    mock_openai_url: str,
    content: str,
    *,
    timeout: float = 30,
) -> None:
    """AIMock journal t t stringt t t t."""
    deadline = time.monotonic() + timeout
    last_journal = ""
    while time.monotonic() < deadline:
        last_journal = _mock_openai_journal_text(mock_openai_url)
        if content in last_journal:
            return
        time.sleep(0.25)
    raise TimeoutError(
        f"mock OpenAI journal did not include {content!r}: {last_journal}"
    )


class TestChatInputBuffer:
    """chat input buffer user patht E2E t verifyt."""

    def test_running_follow_ups_are_buffered_then_promoted_in_fifo_order(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        mock_openai_url: str,
    ) -> None:
        """Promote multiple running-session follow-ups in FIFO order."""
        del azents_engine_worker_container
        _reset_mock_openai(mock_openai_url)
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(
            public_api_client,
            workspace,
            delay_seconds=5.0,
            release_file_path=None,
        )

        initial_response = _write_new_session_message(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_INITIAL_MESSAGE,
            client_request_id=f"initial-{unique()}",
        )
        session_id = _session_id_from_write(initial_response)
        _assert_legacy_messages_get_removed(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
        )
        _wait_for_running_rest_state(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            expected_message=_INITIAL_MESSAGE,
            timeout=60,
        )

        client_request_id = f"follow-up-{unique()}"
        follow_up_response = _write_session_message(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            agent_id=agent_id,
            message=_FOLLOW_UP_MESSAGE,
            client_request_id=client_request_id,
        )
        retry_response = _write_session_message(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            agent_id=agent_id,
            message=_FOLLOW_UP_MESSAGE,
            client_request_id=client_request_id,
        )
        assert follow_up_response["client_request_id"] == client_request_id
        assert retry_response["client_request_id"] == client_request_id
        assert _accepted_write(follow_up_response) == _accepted_write(retry_response)
        second_follow_up_response = _write_session_message(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            agent_id=agent_id,
            message=_SECOND_FOLLOW_UP_MESSAGE,
            client_request_id=f"second-follow-up-{unique()}",
        )
        follow_up_buffer = _PendingBuffer(
            id=str(_accepted_write(follow_up_response)["id"]),
            content=_FOLLOW_UP_MESSAGE,
        )
        second_follow_up_buffer = _PendingBuffer(
            id=str(_accepted_write(second_follow_up_response)["id"]),
            content=_SECOND_FOLLOW_UP_MESSAGE,
        )
        pending_payload = _list_live(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
        )
        assert _input_buffer_contents(pending_payload) == [
            _FOLLOW_UP_MESSAGE,
            _SECOND_FOLLOW_UP_MESSAGE,
        ]
        history_payload = _list_history(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
        )
        assert _FOLLOW_UP_MESSAGE not in _message_contents(history_payload)
        assert _SECOND_FOLLOW_UP_MESSAGE not in _message_contents(history_payload)

        final_payload = _wait_for_rest_state(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            expected_message=_SECOND_FOLLOW_UP_MESSAGE,
            expected_pending=[],
        )

        final_live = _object_item(final_payload.get("live"), label="final live")
        final_history = _object_item(
            final_payload.get("history"),
            label="final history",
        )
        assert follow_up_buffer.id not in json.dumps(final_live)
        assert second_follow_up_buffer.id not in json.dumps(final_live)
        assert _input_buffer_contents(final_live) == []
        final_contents = _message_contents(final_history)
        first_follow_up_index = final_contents.index(_FOLLOW_UP_MESSAGE)
        second_follow_up_index = final_contents.index(_SECOND_FOLLOW_UP_MESSAGE)
        assert first_follow_up_index < second_follow_up_index
        _wait_for_mock_openai_journal_contains(mock_openai_url, _FOLLOW_UP_MESSAGE)
        _wait_for_mock_openai_journal_contains(
            mock_openai_url,
            _SECOND_FOLLOW_UP_MESSAGE,
        )

    def test_pending_buffer_delete_prevents_model_injection(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: DockerContainer,
        mock_openai_url: str,
    ) -> None:
        """Delete a pending buffer before the blocked tool can finish."""
        _reset_mock_openai(mock_openai_url)
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        release_file_path = f"/tmp/azents-runtime-hook-qa-{unique()}"
        _set_release_file(
            azents_engine_worker_container,
            release_file_path,
            present=False,
        )
        agent_id = _create_agent(
            public_api_client,
            workspace,
            delay_seconds=0.0,
            release_file_path=release_file_path,
        )

        session_id: str | None = None
        try:
            initial_response = _write_new_session_message(
                server_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                message=_INITIAL_MESSAGE,
                client_request_id=f"initial-delete-{unique()}",
            )
            session_id = _session_id_from_write(initial_response)
            _assert_legacy_messages_get_removed(
                server_url=azents_public_server_url,
                token=workspace.token,
                session_id=session_id,
            )
            _wait_for_tool_release_barrier(
                azents_engine_worker_container,
                release_file_path,
            )
            deleted_response = _write_session_message(
                server_url=azents_public_server_url,
                token=workspace.token,
                session_id=session_id,
                agent_id=agent_id,
                message=_DELETED_MESSAGE,
                client_request_id=f"deleted-{unique()}",
            )
            deleted_buffer = _PendingBuffer(
                id=str(_accepted_write(deleted_response)["id"]),
                content=_DELETED_MESSAGE,
            )
            _wait_for_pending_buffer(
                server_url=azents_public_server_url,
                token=workspace.token,
                session_id=session_id,
                expected=deleted_buffer,
            )
            _delete_input_buffer(
                server_url=azents_public_server_url,
                token=workspace.token,
                session_id=session_id,
                buffer_id=deleted_buffer.id,
            )
            pending_payload = _list_live(
                server_url=azents_public_server_url,
                token=workspace.token,
                session_id=session_id,
            )
            assert _pending_buffers(pending_payload) == []
        finally:
            _set_release_file(
                azents_engine_worker_container,
                release_file_path,
                present=True,
            )

        assert session_id is not None
        _wait_for_idle_rest_state(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            expected_message=_INITIAL_MESSAGE,
        )
        final_history = _list_history(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
        )
        assert _DELETED_MESSAGE not in _message_contents(final_history)
        assert _DELETED_MESSAGE not in _mock_openai_journal_text(mock_openai_url)

    def test_rest_stop_interrupts_running_session(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """REST stop endpoint t running session t interrupted t t."""
        del azents_engine_worker_container
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(
            public_api_client,
            workspace,
            delay_seconds=30.0,
            release_file_path=None,
        )
        initial_response = _write_new_session_message(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_INITIAL_MESSAGE,
            client_request_id=f"initial-stop-{unique()}",
        )
        session_id = _session_id_from_write(initial_response)
        _wait_for_running_rest_state(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            expected_message=_INITIAL_MESSAGE,
            timeout=60,
        )

        stop_response = _stop_session_run(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
        )

        assert stop_response["session_id"] == session_id
        history_payload = _wait_for_interrupted_stopped_state(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
        )
        assert "interrupted" in _run_marker_statuses(history_payload)

    def test_edit_and_command_are_rest_writes(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """edit/command REST write t accepted target t reload hint t returnt."""
        del azents_engine_worker_container
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(
            public_api_client,
            workspace,
            delay_seconds=3.0,
            release_file_path=None,
        )
        initial_response = _write_new_session_message(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_INITIAL_MESSAGE,
            client_request_id=f"initial-edit-command-{unique()}",
        )
        session_id = _session_id_from_write(initial_response)
        _wait_for_idle_rest_state(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            expected_message=_INITIAL_MESSAGE,
        )
        message_id = _wait_for_history_user_message_id(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            content=_INITIAL_MESSAGE,
        )

        edit_response = _write_edit_message(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            agent_id=agent_id,
            message_id=message_id,
            message=_EDITED_MESSAGE,
            client_request_id=f"edit-{unique()}",
        )
        edit_accepted = _accepted_write(edit_response)
        assert edit_accepted["type"] == "edit_message"
        assert edit_accepted["id"] == message_id
        assert edit_response["history_reload_required"] is True

        _wait_for_idle_rest_state(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            expected_message=_EDITED_MESSAGE,
        )
        command_response = _write_command(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            agent_id=agent_id,
            command="compact",
            client_request_id=f"command-{unique()}",
        )
        command_accepted = _accepted_write(command_response)
        assert command_accepted["type"] == "command"
        assert isinstance(command_accepted["id"], str)
        assert command_accepted["id"]
        assert command_response["history_reload_required"] is True
