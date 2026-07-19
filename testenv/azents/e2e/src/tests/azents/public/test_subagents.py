"""Subagent product E2E tests."""

import time
from dataclasses import dataclass
from typing import cast

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_model_selection_input import (
    AgentModelSelectionInput,
)
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from pydantic import TypeAdapter, ValidationError

from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
)

_SPAWN_MESSAGE = "Subagent E2E spawn child"
_SPAWN_RESPONSE = "Subagent child was spawned."
_CHILD_TASK = "Subagent E2E child task"
_CHILD_RESPONSE = "Subagent child completed."
_WAIT_MESSAGE = "Subagent E2E wait child"
_WAIT_CALL_ID = "call_subagent_wait_child"
_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


@dataclass(frozen=True)
class _Workspace:
    """Subagent E2E workspace state."""

    token: str
    handle: str
    model_selection: AgentModelSelectionInput


@dataclass(frozen=True)
class _TreeNode:
    """Projected Subagent Tree node fields used by the E2E."""

    session_agent_id: str
    agent_session_id: str
    name: str
    status: str
    unread_result: bool
    terminal_result_message: str | None
    children: list["_TreeNode"]


def _headers(token: str) -> dict[str, str]:
    """Return bearer auth headers."""
    return {"Authorization": f"Bearer {token}"}


def _json_object_payload(payload: object, *, label: str) -> dict[str, object]:
    """Validate a JSON object payload."""
    try:
        return _JSON_OBJECT.validate_python(payload)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object: {payload!r}") from exc


def _json_object_list_payload(
    payload: object,
    *,
    label: str,
) -> list[dict[str, object]]:
    """Validate a JSON object list payload."""
    try:
        return _JSON_OBJECT_LIST.validate_python(payload)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object list: {payload!r}") from exc


def _json_object(response: requests.Response) -> dict[str, object]:
    """Return a validated JSON object response."""
    return _json_object_payload(response.json(), label="HTTP JSON response")


def _setup_workspace(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
) -> _Workspace:
    """Create a workspace with deterministic model selection."""
    uniq = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"subagent-e2e-{uniq}@example.com",
    )
    handle = f"subagent-e2e-{uniq}"

    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Subagent E2E {uniq}",
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
            secrets=Secrets(ApiKeySecrets(api_key="sk-subagent-e2e")),
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
) -> str:
    """Create an Agent that receives the auto-bound subagent toolkit."""
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name="Subagent E2E Agent",
            model_selection=workspace.model_selection,
            lightweight_model_selection=workspace.model_selection,
            type=AgentType.PUBLIC,
            shell_enabled=True,
        ),
        _headers=_headers(workspace.token),
    )
    return agent.id


def _team_primary_session(
    *,
    public_url: str,
    token: str,
    agent_id: str,
) -> str:
    """Resolve the team primary root session."""
    response = requests.get(
        f"{public_url}/chat/v1/agents/{agent_id}/team-primary-session",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    payload = _json_object(response)
    session_id = payload.get("id")
    if not isinstance(session_id, str):
        raise AssertionError(f"Team primary response did not include id: {payload!r}")
    return session_id


def _run_message(
    *,
    public_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    message: str,
) -> None:
    """Send a chat message through the REST write boundary."""
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"subagent-e2e-message-{unique()}",
            "message": message,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
            },
        },
        timeout=10,
    )
    response.raise_for_status()


def _history(
    *,
    public_url: str,
    token: str,
    session_id: str,
) -> list[dict[str, object]]:
    """Fetch raw REST history events."""
    response = requests.get(
        f"{public_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    payload = _json_object(response)
    return _json_object_list_payload(payload.get("items"), label="history items")


def _event_payload(event: dict[str, object]) -> dict[str, object]:
    """Return a validated event payload."""
    return _json_object_payload(event.get("payload"), label="event payload")


def _history_contents(
    *,
    public_url: str,
    token: str,
    session_id: str,
) -> list[str]:
    """Return model-visible text contents from history."""
    contents: list[str] = []
    for event in _history(public_url=public_url, token=token, session_id=session_id):
        if event.get("kind") not in {
            "user_message",
            "agent_message",
            "assistant_message",
        }:
            continue
        payload = _event_payload(event)
        content = payload.get("content")
        if isinstance(content, str):
            contents.append(content)
    return contents


def _tool_result_output_text(event: dict[str, object]) -> str | None:
    """Return persisted client tool result text for a history event."""
    if event.get("kind") != "client_tool_result":
        return None
    payload = _event_payload(event)
    output = payload.get("output")
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        texts: list[str] = []
        for part in cast("list[object]", output):
            if not isinstance(part, dict):
                continue
            part_dict = cast("dict[str, object]", part)
            text = part_dict.get("text")
            if isinstance(text, str):
                texts.append(text)
        return "\n".join(texts)
    if output is None:
        return None
    return str(output)


def _wait_for_tool_result_content(
    *,
    public_url: str,
    token: str,
    session_id: str,
    call_id: str,
    expected: str,
    timeout: float = 120,
) -> None:
    """Wait until a client tool result contains expected text."""
    deadline = time.monotonic() + timeout
    last_outputs: list[str] = []
    while time.monotonic() < deadline:
        last_outputs = []
        for event in _history(
            public_url=public_url, token=token, session_id=session_id
        ):
            payload = _event_payload(event)
            if payload.get("call_id") != call_id:
                continue
            output = _tool_result_output_text(event)
            if output is not None:
                last_outputs.append(output)
        if any(expected in output for output in last_outputs):
            return
        time.sleep(0.5)
    raise TimeoutError(
        f"tool result content not observed: {call_id}, {expected}, {last_outputs!r}"
    )


def _run_marker_completed(event: dict[str, object]) -> bool:
    """Return whether a history event is a completed run marker."""
    if event.get("kind") != "run_marker":
        return False
    return _event_payload(event).get("status") == "completed"


def _wait_for_run_complete(
    *,
    public_url: str,
    token: str,
    session_id: str,
    timeout: float = 120,
) -> None:
    """Wait until a session history contains a completed run marker."""
    deadline = time.monotonic() + timeout
    last_kinds: list[object] = []
    while time.monotonic() < deadline:
        events = _history(public_url=public_url, token=token, session_id=session_id)
        if any(_run_marker_completed(event) for event in events):
            return
        last_kinds = [event.get("kind") for event in events]
        time.sleep(0.5)
    raise TimeoutError(f"completed run marker not observed: {last_kinds!r}")


def _wait_for_content(
    *,
    public_url: str,
    token: str,
    session_id: str,
    expected: str,
    timeout: float = 120,
) -> None:
    """Wait until a session history contains expected text."""
    deadline = time.monotonic() + timeout
    last_contents: list[str] = []
    while time.monotonic() < deadline:
        last_contents = _history_contents(
            public_url=public_url,
            token=token,
            session_id=session_id,
        )
        if any(expected in content for content in last_contents):
            return
        time.sleep(0.5)
    raise TimeoutError(f"history content not observed: {expected}, {last_contents!r}")


def _tree_node(raw: dict[str, object]) -> _TreeNode:
    """Convert a raw tree node to the fields asserted by the E2E."""
    session_agent_id = raw.get("session_agent_id")
    agent_session_id = raw.get("agent_session_id")
    name = raw.get("name")
    status = raw.get("status")
    unread_result = raw.get("unread_result")
    if not isinstance(session_agent_id, str):
        raise AssertionError(f"tree node missing session_agent_id: {raw!r}")
    if not isinstance(agent_session_id, str):
        raise AssertionError(f"tree node missing agent_session_id: {raw!r}")
    if not isinstance(name, str):
        raise AssertionError(f"tree node missing name: {raw!r}")
    if not isinstance(status, str):
        raise AssertionError(f"tree node missing status: {raw!r}")
    if not isinstance(unread_result, bool):
        raise AssertionError(f"tree node missing unread_result: {raw!r}")
    terminal = raw.get("terminal_result_message")
    if terminal is not None and not isinstance(terminal, str):
        raise AssertionError(f"tree node has invalid terminal result: {raw!r}")
    return _TreeNode(
        session_agent_id=session_agent_id,
        agent_session_id=agent_session_id,
        name=name,
        status=status,
        unread_result=unread_result,
        terminal_result_message=terminal,
        children=[
            _tree_node(child)
            for child in _json_object_list_payload(
                raw.get("children"), label="children"
            )
        ],
    )


def _subagent_tree(
    *,
    public_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> dict[str, object]:
    """Fetch the Subagent Tree projection."""
    response = requests.get(
        f"{public_url}/chat/v1/agents/{agent_id}/sessions/{session_id}/subagents/tree",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return _json_object(response)


def _tree_nodes(tree: dict[str, object]) -> list[_TreeNode]:
    """Return validated tree root nodes."""
    return [
        _tree_node(raw)
        for raw in _json_object_list_payload(tree.get("nodes"), label="tree nodes")
    ]


def _find_node(nodes: list[_TreeNode], name: str) -> _TreeNode | None:
    """Find a named node in a projected tree."""
    for node in nodes:
        if node.name == name:
            return node
        child = _find_node(node.children, name)
        if child is not None:
            return child
    return None


def _wait_for_child_node(
    *,
    public_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    expected_status: str | None,
    expected_unread: bool | None,
    timeout: float = 120,
) -> tuple[dict[str, object], _TreeNode]:
    """Wait until child_qa appears with the expected projected state."""
    deadline = time.monotonic() + timeout
    last_tree: dict[str, object] | None = None
    while time.monotonic() < deadline:
        tree = _subagent_tree(
            public_url=public_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        last_tree = tree
        child = _find_node(_tree_nodes(tree), "child_qa")
        if child is not None:
            status_ok = expected_status is None or child.status == expected_status
            unread_ok = (
                expected_unread is None or child.unread_result is expected_unread
            )
            if status_ok and unread_ok:
                return tree, child
        time.sleep(0.5)
    raise TimeoutError(f"child node state was not observed: {last_tree!r}")


def _session_run_state(
    *,
    public_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> str:
    """Return the authoritative AgentSession run state."""
    response = requests.get(
        f"{public_url}/chat/v1/agents/{agent_id}/sessions/{session_id}",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    payload = _json_object(response)
    run_state = payload.get("run_state")
    if not isinstance(run_state, str):
        raise AssertionError(f"Session response did not include run_state: {payload!r}")
    return run_state


def _wait_for_session_run_state(
    *,
    public_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    expected: str,
    timeout: float = 120,
) -> None:
    """Wait until an AgentSession reaches the expected run state."""
    deadline = time.monotonic() + timeout
    last_state: str | None = None
    while time.monotonic() < deadline:
        last_state = _session_run_state(
            public_url=public_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        if last_state == expected:
            return
        time.sleep(0.5)
    raise TimeoutError(
        f"session run state not observed: {expected}, last_state={last_state!r}"
    )


def _session_ids(
    *,
    public_url: str,
    token: str,
    agent_id: str,
) -> set[str]:
    """Return ordinary agent-scoped session IDs."""
    response = requests.get(
        f"{public_url}/chat/v1/agents/{agent_id}/sessions",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    payload = _json_object(response)
    items = _json_object_list_payload(payload.get("items"), label="session items")
    ids: set[str] = set()
    for item in items:
        session_id = item.get("id")
        if isinstance(session_id, str):
            ids.add(session_id)
    return ids


class TestSubagents:
    """Subagent user-facing behavior E2E coverage."""

    def test_spawn_wait_tree_projection_and_child_detail_history(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Spawn a child, open child detail history, and observe it via wait_agent."""
        del azents_engine_worker_container
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(public_api_client, workspace)
        root_session_id = _team_primary_session(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
        )

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_SPAWN_MESSAGE,
        )
        root_tree, child = _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            expected_status="completed",
            expected_unread=True,
        )

        assert root_tree.get("root_agent_session_id") == root_session_id
        assert root_tree.get("current_session_agent_id") == root_tree.get(
            "root_session_agent_id"
        )
        assert child.terminal_result_message == _CHILD_RESPONSE
        assert child.agent_session_id not in _session_ids(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_SPAWN_RESPONSE,
        )
        _wait_for_run_complete(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
        )
        _wait_for_session_run_state(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            expected="idle",
        )

        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=child.agent_session_id,
            expected=_CHILD_TASK,
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=child.agent_session_id,
            expected=_CHILD_RESPONSE,
        )
        child_tree = _subagent_tree(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=child.agent_session_id,
        )
        assert child_tree.get("root_agent_session_id") == root_session_id
        assert child_tree.get("current_session_agent_id") == child.session_agent_id

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_WAIT_MESSAGE,
        )
        _wait_for_tool_result_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_WAIT_CALL_ID,
            expected="All descendant agents are idle.",
        )
        _, observed_child = _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            expected_status="completed",
            expected_unread=False,
        )
        assert observed_child.terminal_result_message == _CHILD_RESPONSE
