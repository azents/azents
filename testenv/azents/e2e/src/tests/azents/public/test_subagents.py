"""Subagent product E2E tests."""

import json
import time
from dataclasses import dataclass
from typing import cast

import azentsadminclient
import azentspublicclient
import pytest
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

_SPAWN_MESSAGE = "Subagent E2E spawn child"
_SPAWN_RESPONSE = "Subagent child was spawned."
_CHILD_TASK = "Subagent E2E child task"
_CHILD_RESPONSE = "Subagent child completed."
_WAIT_MESSAGE = "Subagent E2E wait child"
_WAIT_CALL_ID = "call_subagent_wait_child"
_WAIT_RESPONSE = "Subagent wait observed child result."
_MAILBOX_MESSAGE = "Subagent E2E mailbox any sender"
_MAILBOX_IDLE_SPAWN_RESPONSE = "Subagent mailbox idle child was spawned."
_MAILBOX_WAIT_MESSAGE = "Subagent E2E wait for mailbox sender"
_MAILBOX_WAIT_CALL_ID = "call_subagent_mailbox_wait"
_MAILBOX_SENDER_CALL_ID = "call_subagent_mailbox_sender_message"
_MAILBOX_RESPONSE = "Subagent mailbox wait observed an intermediate message."
_MAILBOX_PROMOTION_MESSAGE = "Subagent E2E promote mailbox messages"
_MAILBOX_PROMOTION_RESPONSE = "Subagent mailbox messages were promoted."
_POST_OBSERVATION_MESSAGE = "Subagent E2E post-observation turn"
_POST_OBSERVATION_RESPONSE = "Subagent post-observation turn completed."
_NO_DESCENDANTS_MESSAGE = "Subagent E2E wait with no descendants"
_NO_DESCENDANTS_CALL_ID = "call_subagent_wait_no_descendants"
_NO_DESCENDANTS_RESPONSE = "Subagent no-descendant wait completed."
_ACTIVE_TIMEOUT_MESSAGE = "Subagent E2E active descendant timeout"
_ACTIVE_TIMEOUT_SPAWN_RESPONSE = "Subagent timeout child was spawned."
_ACTIVE_TIMEOUT_WAIT_MESSAGE = "Subagent E2E wait for active descendant timeout"
_ACTIVE_TIMEOUT_CALL_ID = "call_subagent_timeout_wait"
_ACTIVE_TIMEOUT_RESPONSE = "Subagent active-descendant timeout observed."
_INTERRUPT_SPAWN_MESSAGE = "Subagent E2E spawn interrupt child"
_INTERRUPT_SPAWN_RESPONSE = "Subagent interrupt child was spawned."
_INTERRUPT_MESSAGE = "Subagent E2E interrupt child"
_INTERRUPT_CALL_ID = "call_subagent_interrupt_child"
_INTERRUPT_RESPONSE = "Subagent interrupt request completed."
_INTERRUPT_OBSERVE_MESSAGE = "Subagent E2E observe interrupted result"
_INTERRUPT_OBSERVE_RESPONSE = "Subagent interrupted result was observed."
_FAILED_SPAWN_MESSAGE = "Subagent E2E spawn failed child"
_FAILED_SPAWN_RESPONSE = "Subagent failed child was spawned."
_FAILED_OBSERVE_MESSAGE = "Subagent E2E observe failed result"
_FAILED_OBSERVE_RESPONSE = "Subagent failed result was observed."
_FAILED_INTERNAL_MARKER = "SUBAGENT_INTERNAL_PROVIDER_FAILURE_MARKER"
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
    *,
    release_file_path: str | None = None,
) -> str:
    """Create an Agent with subagent tools and an optional release barrier."""
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
    if release_file_path is not None:
        toolkit_api = ToolkitV1Api(public_api_client)
        toolkit = toolkit_api.toolkit_v1_create_toolkit_config(
            handle=workspace.handle,
            toolkit_config_create_request=ToolkitConfigCreateRequest(
                toolkit_type="runtime_hook_qa",
                slug="subagentqa",
                name="Subagent Release Barrier",
                config={
                    "mode": "observe",
                    "delay_seconds": 0.0,
                    "release_file_path": release_file_path,
                },
                enabled=True,
            ),
            _headers=_headers(workspace.token),
        )
        toolkit_api.toolkit_v1_attach_toolkit_to_agent(
            handle=workspace.handle,
            agent_id=agent.id,
            agent_toolkit_attach_request=AgentToolkitAttachRequest(
                toolkit_id=toolkit.id
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


def _event_order_key(event: dict[str, object]) -> str:
    """Return the UUIDv7 ordering key for a persisted event."""
    event_id = event.get("id")
    if not isinstance(event_id, str):
        raise AssertionError(f"history event is missing an ID: {event!r}")
    return event_id


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


def _agent_message_payloads(
    *,
    public_url: str,
    token: str,
    session_id: str,
) -> list[dict[str, object]]:
    """Return durable agent-message payloads from session history."""
    return [
        _event_payload(event)
        for event in _history(
            public_url=public_url,
            token=token,
            session_id=session_id,
        )
        if event.get("kind") == "agent_message"
    ]


def _wait_for_agent_result(
    *,
    public_url: str,
    token: str,
    session_id: str,
    source_path: str,
    run_status: str,
    timeout: float = 120,
) -> dict[str, object]:
    """Wait for one terminal result from the expected source and status."""
    deadline = time.monotonic() + timeout
    last_payloads: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        last_payloads = _agent_message_payloads(
            public_url=public_url,
            token=token,
            session_id=session_id,
        )
        matches = [
            payload
            for payload in last_payloads
            if payload.get("message_kind") == "agent_result"
            and payload.get("source_path") == source_path
            and payload.get("run_status") == run_status
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise AssertionError(
                f"duplicate terminal results for {source_path}: {matches!r}"
            )
        time.sleep(0.5)
    raise TimeoutError(
        f"terminal result not observed: {source_path}, {run_status}, {last_payloads!r}"
    )


def _reset_mock_openai(mock_openai_url: str) -> None:
    """Clear the deterministic provider request journal."""
    requests.delete(f"{mock_openai_url}/v1/_requests", timeout=10).raise_for_status()


def _mock_openai_journal_text(mock_openai_url: str) -> str:
    """Return the deterministic provider journal as serialized JSON."""
    response = requests.get(f"{mock_openai_url}/v1/_requests", timeout=10)
    response.raise_for_status()
    return json.dumps(response.json(), ensure_ascii=False)


def _wait_for_mock_openai_journal_content(
    mock_openai_url: str,
    content: str,
    *,
    timeout: float = 30,
) -> None:
    """Wait until one provider request contains the exact multiline content."""
    deadline = time.monotonic() + timeout
    needle = json.dumps(content, ensure_ascii=False)[1:-1]
    last_journal = ""
    while time.monotonic() < deadline:
        last_journal = _mock_openai_journal_text(mock_openai_url)
        if needle in last_journal:
            return
        time.sleep(0.25)
    raise TimeoutError(
        f"mock provider journal did not include {content!r}: {last_journal}"
    )


def _container_logs(container: DockerContainer) -> str:
    """Return combined container stdout and stderr."""
    stdout, stderr = container.get_logs()
    return stdout.decode(errors="replace") + stderr.decode(errors="replace")


def _wait_for_release_barriers(
    container: DockerContainer,
    release_file_path: str,
    *,
    expected_count: int,
    timeout: float = 120,
) -> None:
    """Wait until the expected child tools are blocked on a release file."""
    deadline = time.monotonic() + timeout
    last_logs = ""
    while time.monotonic() < deadline:
        last_logs = _container_logs(container)
        if last_logs.count(release_file_path) >= expected_count:
            return
        time.sleep(0.25)
    raise TimeoutError(
        f"release barriers were not observed: {release_file_path}, "
        f"expected={expected_count}\n{last_logs[-4000:]}"
    )


def _set_release_file(
    container: DockerContainer,
    release_file_path: str,
    *,
    present: bool,
) -> None:
    """Create or remove a release file inside the worker container."""
    command = (
        ["touch", release_file_path] if present else ["rm", "-f", release_file_path]
    )
    result = container.get_wrapped_container().exec_run(command)
    if result.exit_code != 0:
        output = result.output.decode(errors="replace")
        raise AssertionError(
            f"failed to update release file {release_file_path}: {output}"
        )


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
) -> dict[str, object]:
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
            if output is None:
                continue
            last_outputs.append(output)
            if expected in output:
                return event
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
) -> dict[str, object]:
    """Wait until a session history contains a completed run marker."""
    deadline = time.monotonic() + timeout
    last_kinds: list[object] = []
    while time.monotonic() < deadline:
        events = _history(public_url=public_url, token=token, session_id=session_id)
        for event in events:
            if _run_marker_completed(event):
                return event
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
    name: str,
    expected_status: str | None,
    expected_unread: bool | None,
    timeout: float = 120,
) -> tuple[dict[str, object], _TreeNode]:
    """Wait until a named child appears with the expected projected state."""
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
        child = _find_node(_tree_nodes(tree), name)
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
            name="child_qa",
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
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_CHILD_RESPONSE,
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
            name="child_qa",
            expected_status="completed",
            expected_unread=False,
        )
        assert observed_child.terminal_result_message == _CHILD_RESPONSE
        completed_result = _wait_for_agent_result(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            source_path="/root/child_qa",
            run_status="completed",
        )
        assert completed_result.get("content") == _CHILD_RESPONSE
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_WAIT_RESPONSE,
        )
        _wait_for_session_run_state(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            expected="idle",
        )

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_POST_OBSERVATION_MESSAGE,
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_POST_OBSERVATION_RESPONSE,
        )
        _wait_for_session_run_state(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            expected="idle",
        )
        completed_results = [
            payload
            for payload in _agent_message_payloads(
                public_url=azents_public_server_url,
                token=workspace.token,
                session_id=root_session_id,
            )
            if payload.get("message_kind") == "agent_result"
            and payload.get("source_path") == "/root/child_qa"
            and payload.get("run_status") == "completed"
        ]
        assert len(completed_results) == 1

    def test_targetless_wait_observes_any_child_mailbox_message(
        self,
        request: pytest.FixtureRequest,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: DockerContainer,
        mock_openai_url: str,
    ) -> None:
        """Observe one child message while every descendant remains active."""
        _reset_mock_openai(mock_openai_url)
        release_file_path = f"/tmp/azents-subagent-mailbox-{unique()}"
        _set_release_file(
            azents_engine_worker_container,
            release_file_path,
            present=False,
        )
        request.addfinalizer(
            lambda: _set_release_file(
                azents_engine_worker_container,
                release_file_path,
                present=True,
            )
        )
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(
            public_api_client,
            workspace,
            release_file_path=release_file_path,
        )
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
            message=_MAILBOX_MESSAGE,
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_MAILBOX_IDLE_SPAWN_RESPONSE,
        )
        _, idle = _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="idle_child",
            expected_status="running",
            expected_unread=False,
        )
        _wait_for_session_run_state(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            expected="idle",
        )

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_MAILBOX_WAIT_MESSAGE,
        )
        _, sender = _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="sender_child",
            expected_status="running",
            expected_unread=False,
        )
        _wait_for_tool_result_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=sender.agent_session_id,
            call_id=_MAILBOX_SENDER_CALL_ID,
            expected="queued",
        )
        _wait_for_release_barriers(
            azents_engine_worker_container,
            release_file_path,
            expected_count=2,
        )
        wait_event = _wait_for_tool_result_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_MAILBOX_WAIT_CALL_ID,
            expected="Mailbox updated.",
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_MAILBOX_RESPONSE,
        )
        _set_release_file(
            azents_engine_worker_container,
            release_file_path,
            present=True,
        )
        _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="sender_child",
            expected_status="completed",
            expected_unread=True,
        )
        _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="idle_child",
            expected_status="completed",
            expected_unread=True,
        )
        sender_completed_event = _wait_for_run_complete(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=sender.agent_session_id,
        )
        idle_completed_event = _wait_for_run_complete(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=idle.agent_session_id,
        )
        wait_order = _event_order_key(wait_event)
        assert wait_order < _event_order_key(sender_completed_event)
        assert wait_order < _event_order_key(idle_completed_event)
        _wait_for_session_run_state(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            expected="idle",
        )

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_MAILBOX_PROMOTION_MESSAGE,
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_MAILBOX_PROMOTION_RESPONSE,
        )
        _wait_for_mock_openai_journal_content(
            mock_openai_url,
            "\n".join(
                [
                    "Message Type: MESSAGE",
                    "Task name: /root",
                    "Sender: /root/sender_child",
                    "Payload:",
                    "Subagent intermediate mailbox message.",
                ]
            ),
        )
        _wait_for_agent_result(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            source_path="/root/sender_child",
            run_status="completed",
        )
        _wait_for_agent_result(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            source_path="/root/idle_child",
            run_status="completed",
        )
        _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="sender_child",
            expected_status="completed",
            expected_unread=False,
        )
        _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="idle_child",
            expected_status="completed",
            expected_unread=False,
        )

    def test_targetless_wait_without_descendants_returns_immediately(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Return a no-descendants result without creating a child."""
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
            message=_NO_DESCENDANTS_MESSAGE,
        )
        _wait_for_tool_result_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_NO_DESCENDANTS_CALL_ID,
            expected="No descendant agents to wait for.",
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_NO_DESCENDANTS_RESPONSE,
        )
        nodes = _tree_nodes(
            _subagent_tree(
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=root_session_id,
            )
        )
        assert len(nodes) == 1
        assert nodes[0].name == "root"
        assert nodes[0].children == []
        _wait_for_session_run_state(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            expected="idle",
        )

    def test_targetless_wait_timeout_reports_active_descendant(
        self,
        request: pytest.FixtureRequest,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: DockerContainer,
    ) -> None:
        """Report an active descendant when a zero-duration wait expires."""
        release_file_path = f"/tmp/azents-subagent-timeout-{unique()}"
        _set_release_file(
            azents_engine_worker_container,
            release_file_path,
            present=False,
        )
        request.addfinalizer(
            lambda: _set_release_file(
                azents_engine_worker_container,
                release_file_path,
                present=True,
            )
        )
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(
            public_api_client,
            workspace,
            release_file_path=release_file_path,
        )
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
            message=_ACTIVE_TIMEOUT_MESSAGE,
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_ACTIVE_TIMEOUT_SPAWN_RESPONSE,
        )
        _, child = _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="timeout_child",
            expected_status="running",
            expected_unread=False,
        )
        _wait_for_release_barriers(
            azents_engine_worker_container,
            release_file_path,
            expected_count=1,
        )

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_ACTIVE_TIMEOUT_WAIT_MESSAGE,
        )
        wait_event = _wait_for_tool_result_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_ACTIVE_TIMEOUT_CALL_ID,
            expected="Wait timed out; active descendants: /root/timeout_child",
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_ACTIVE_TIMEOUT_RESPONSE,
        )
        _set_release_file(
            azents_engine_worker_container,
            release_file_path,
            present=True,
        )
        _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="timeout_child",
            expected_status="completed",
            expected_unread=True,
        )
        child_completed_event = _wait_for_run_complete(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=child.agent_session_id,
        )
        assert _event_order_key(wait_event) < _event_order_key(child_completed_event)
        _wait_for_session_run_state(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            expected="idle",
        )

    def test_interrupt_agent_delivers_stopped_child_result_safely(
        self,
        request: pytest.FixtureRequest,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: DockerContainer,
    ) -> None:
        """Stop an interrupted child and promote its safe terminal result."""
        release_file_path = f"/tmp/azents-subagent-interrupt-{unique()}"
        _set_release_file(
            azents_engine_worker_container,
            release_file_path,
            present=False,
        )
        request.addfinalizer(
            lambda: _set_release_file(
                azents_engine_worker_container,
                release_file_path,
                present=True,
            )
        )
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(
            public_api_client,
            workspace,
            release_file_path=release_file_path,
        )
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
            message=_INTERRUPT_SPAWN_MESSAGE,
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_INTERRUPT_SPAWN_RESPONSE,
        )
        _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="interrupt_child",
            expected_status="running",
            expected_unread=False,
        )
        _wait_for_release_barriers(
            azents_engine_worker_container,
            release_file_path,
            expected_count=1,
        )

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_INTERRUPT_MESSAGE,
        )
        _wait_for_tool_result_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_INTERRUPT_CALL_ID,
            expected="running",
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_INTERRUPT_RESPONSE,
        )
        _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="interrupt_child",
            expected_status="interrupted",
            expected_unread=True,
        )
        _wait_for_session_run_state(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            expected="idle",
        )

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_INTERRUPT_OBSERVE_MESSAGE,
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_INTERRUPT_OBSERVE_RESPONSE,
        )
        stopped_result = _wait_for_agent_result(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            source_path="/root/interrupt_child",
            run_status="stopped",
        )
        assert stopped_result.get("content") == "The agent run was stopped."
        _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="interrupt_child",
            expected_status="interrupted",
            expected_unread=False,
        )

    def test_failed_child_result_excludes_internal_provider_failure(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Promote a failed child result without internal provider text."""
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
            message=_FAILED_SPAWN_MESSAGE,
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_FAILED_SPAWN_RESPONSE,
        )
        _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="failed_child",
            expected_status="errored",
            expected_unread=True,
        )
        _wait_for_session_run_state(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            expected="idle",
        )

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_FAILED_OBSERVE_MESSAGE,
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_FAILED_OBSERVE_RESPONSE,
        )
        failed_result = _wait_for_agent_result(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            source_path="/root/failed_child",
            run_status="failed",
        )
        failed_content = failed_result.get("content")
        assert isinstance(failed_content, str)
        assert failed_content
        assert _FAILED_INTERNAL_MARKER not in failed_content
        _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="failed_child",
            expected_status="errored",
            expected_unread=False,
        )
