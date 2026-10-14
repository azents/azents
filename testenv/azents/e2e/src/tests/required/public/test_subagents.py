"""Subagent product E2E tests."""

import json
import time
from dataclasses import dataclass, replace
from typing import Literal, NamedTuple

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
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.agent_toolkit_attach_request import (
    AgentToolkitAttachRequest,
)
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.agent_update_request import AgentUpdateRequest
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.chat_event_response import ChatEventResponse
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.subagent_settings import SubagentSettings
from azentspublicclient.models.subagent_tree_node_response import (
    SubagentTreeNodeResponse,
)
from azentspublicclient.models.subagent_tree_response import SubagentTreeResponse
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from pydantic import BaseModel, ConfigDict, StrictStr
from testcontainers.core.container import DockerContainer

from support.observations import (
    ExtensionObservation,
    InputMessageObservation,
    RunMarkerObservation,
    ToolResultObservation,
    decode_history_page,
)
from support.runtime_profiles import (
    create_workspace_runtime_profile,
    start_and_wait_for_agent_runtime,
)
from support.system_bootstrap import SystemBootstrapEvidence
from support.utils import (
    authenticate_user,
    decode_docker_exec_output,
    model_selection_from_first_candidate,
    single_candidate_model_options,
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
_INTERRUPT_OBSERVE_MESSAGE = "Subagent E2E observe interrupted result"
_INTERRUPT_OBSERVE_RESPONSE = "Subagent interrupted result was observed."
_FAILED_SPAWN_MESSAGE = "Subagent E2E spawn failed child"
_FAILED_SPAWN_RESPONSE = "Subagent failed child was spawned."
_FAILED_OBSERVE_MESSAGE = "Subagent E2E observe failed result"
_FAILED_OBSERVE_RESPONSE = "Subagent failed result was observed."
_FAILED_INTERNAL_MARKER = "SUBAGENT_INTERNAL_PROVIDER_FAILURE_MARKER"
_BOUNDED_SPAWN_MESSAGES = (
    "Subagent E2E bounded spawn oldest",
    "Subagent E2E bounded spawn middle",
    "Subagent E2E bounded spawn newest",
)
_BOUNDED_CHILD_TASK = "Subagent E2E bounded child task"
_BOUNDED_CHILD_RESPONSE = "Subagent bounded child completed."
_BOUNDED_LIST_MESSAGE = "Subagent E2E bounded list"
_BOUNDED_LIST_CALL_ID = "call_subagent_bounded_list"
_BOUNDED_LIST_RESPONSE = "Subagent bounded list observed."
_BOUNDED_FOLLOWUP_MESSAGE = "Subagent E2E bounded historical followup"
_BOUNDED_FOLLOWUP_CALL_ID = "call_subagent_bounded_followup"
_BOUNDED_FOLLOWUP_TASK = "Subagent E2E bounded reused child task"
_BOUNDED_FOLLOWUP_RESPONSE = "Subagent bounded reused child completed."
_BOUNDED_RELIST_MESSAGE = "Subagent E2E bounded relist"
_BOUNDED_RELIST_CALL_ID = "call_subagent_bounded_relist"
_BOUNDED_RELIST_RESPONSE = "Subagent bounded relist observed."
_OVERFLOW_SPAWN_MESSAGE = "Subagent E2E active overflow spawn"
_OVERFLOW_SPAWN_RESPONSE = "Subagent active overflow children were spawned."
_OVERFLOW_CHILD_TASK = "Subagent E2E active overflow child task"
_OVERFLOW_CHILD_RESPONSE = "Subagent active overflow child completed."
_OVERFLOW_LIST_MESSAGE = "Subagent E2E active overflow list"
_OVERFLOW_LIST_CALL_ID = "call_subagent_active_overflow_list"
_OVERFLOW_LIST_RESPONSE = "Subagent active overflow list observed."
_OVERFLOW_REJECT_MESSAGE = "Subagent E2E active overflow reject spawn"
_OVERFLOW_REJECT_CALL_ID = "call_subagent_active_overflow_reject"
_OVERFLOW_REJECT_RESPONSE = "Subagent active overflow rejection observed."
_OVERFLOW_CONTRACTED_LIST_MESSAGE = "Subagent E2E active overflow contracted list"
_OVERFLOW_CONTRACTED_LIST_CALL_ID = "call_subagent_active_overflow_contracted_list"
_OVERFLOW_CONTRACTED_LIST_RESPONSE = "Subagent contracted list observed."


class _AgentMessageObservation(ExtensionObservation):
    message_kind: Literal[
        "spawn_agent", "send_message", "followup_task", "agent_result"
    ]
    source_path: StrictStr
    run_status: StrictStr | None = None
    content: StrictStr


class _OutputPartObservation(ExtensionObservation):
    text: StrictStr | None = None


class _WaitOutcomeObservation(ExtensionObservation):
    """The native WaitToolkit outcome, decoded independently of its event."""

    outcome: StrictStr
    reason: StrictStr | None = None


class _ListedAgentObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_name: StrictStr
    agent_status: StrictStr


class _ListedAgentsObservation(ExtensionObservation):
    """Interpret bounded list items while preserving opaque tool extensions."""

    agents: list[_ListedAgentObservation]


class _SessionIdObservation(ExtensionObservation):
    id: StrictStr


class _SessionIdsObservation(ExtensionObservation):
    items: list[_SessionIdObservation]


@dataclass(frozen=True)
class _Workspace:
    """Subagent E2E workspace state."""

    token: str
    handle: str
    model_selection: AgentModelSelectionInput
    runtime_profile_id: str


@dataclass(frozen=True)
class _SharedSubagentSetup:
    """Immutable setup shared by isolated Subagent journey Sessions."""

    public_api_client: azentspublicclient.ApiClient
    workspace: _Workspace
    standard_agent_id: str
    barrier_agent_id: str
    barrier_release_file_path: str
    barrier_log_baseline: int
    engine_worker_container: DockerContainer


class _TreeNode(SubagentTreeNodeResponse):
    """Decode the API node contract and retain opaque wire extensions."""

    model_config = ConfigDict(extra="allow")
    children: list["_TreeNode"]


class _TreeObservation(SubagentTreeResponse):
    """Decode the API tree before navigation; preserve uninspected extensions."""

    model_config = ConfigDict(extra="allow")
    nodes: list[_TreeNode]


class _ChildNodeObservation(NamedTuple):
    """Observed Subagent tree and the matching child node."""

    tree: _TreeObservation
    child: _TreeNode


def _headers(token: str) -> dict[str, str]:
    """Return bearer auth headers."""
    return {"Authorization": f"Bearer {token}"}


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
        runtime_profile_id=create_workspace_runtime_profile(
            public_api_client,
            token=token,
            workspace_handle=handle,
            provider_id="system-docker",
        ),
    )


def _create_agent(
    public_api_client: azentspublicclient.ApiClient,
    workspace: _Workspace,
    *,
    release_file_path: str | None = None,
    max_subagents: int | None = None,
) -> str:
    """Create an Agent with subagent tools and an optional release barrier."""
    agent_create_request = AgentCreateRequest(
        name="Subagent E2E Agent",
        selectable_model_options=single_candidate_model_options(
            workspace.model_selection
        ),
        main_model_label="default",
        lightweight_model_label="default",
        type=AgentType.PUBLIC,
        runtime_profile_id=workspace.runtime_profile_id,
    )
    if max_subagents is not None:
        agent_create_request.subagent_settings = SubagentSettings(
            max_subagents=max_subagents,
            max_depth=1,
        )
    if release_file_path is not None:
        agent_create_request.tool_search_enabled = False
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=agent_create_request,
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
    start_and_wait_for_agent_runtime(
        public_api_client,
        token=workspace.token,
        workspace_handle=workspace.handle,
        agent_id=agent.id,
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
    return _SessionIdObservation.model_validate(response.json()).id


def _create_root_session(
    *,
    public_url: str,
    token: str,
    agent_id: str,
) -> str:
    """Create one isolated root Session for a Subagent journey."""
    response = requests.post(
        f"{public_url}/chat/v1/agents/{agent_id}/sessions",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"existing_project_paths": [], "setup_actions": []},
        timeout=10,
    )
    response.raise_for_status()
    return _SessionIdObservation.model_validate(response.json()).id


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
                "enabled_execution_options": [],
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
) -> list[ChatEventResponse]:
    """Decode REST history before interpreting event decision fields."""
    response = requests.get(
        f"{public_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return decode_history_page(response.json()).items


def _event_order_key(event: ChatEventResponse) -> str:
    """Return the UUIDv7 ordering key for a persisted event."""
    return event.id


def _history_contents(
    *,
    public_url: str,
    token: str,
    session_id: str,
) -> list[str]:
    """Return model-visible text contents from history."""
    contents: list[str] = []
    for event in _history(public_url=public_url, token=token, session_id=session_id):
        if event.kind not in {
            "user_message",
            "agent_message",
            "assistant_message",
        }:
            continue
        content = InputMessageObservation.model_validate(event.payload).content
        if isinstance(content, str):
            contents.append(content)
    return contents


def _agent_message_payloads(
    *,
    public_url: str,
    token: str,
    session_id: str,
) -> list[_AgentMessageObservation]:
    """Return durable agent-message payloads from session history."""
    return [
        _AgentMessageObservation.model_validate(event.payload)
        for event in _history(
            public_url=public_url,
            token=token,
            session_id=session_id,
        )
        if event.kind == "agent_message"
    ]


def _wait_for_agent_result(
    *,
    public_url: str,
    token: str,
    session_id: str,
    source_path: str,
    run_status: str,
    timeout: float = 120,
) -> _AgentMessageObservation:
    """Wait for one terminal result from the expected source and status."""
    deadline = time.monotonic() + timeout
    last_payloads: list[_AgentMessageObservation] = []
    while time.monotonic() < deadline:
        last_payloads = _agent_message_payloads(
            public_url=public_url,
            token=token,
            session_id=session_id,
        )
        matches = [
            payload
            for payload in last_payloads
            if payload.message_kind == "agent_result"
            and payload.source_path == source_path
            and payload.run_status == run_status
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
    baseline_count: int,
    expected_count: int,
    timeout: float = 120,
) -> None:
    """Wait until the expected child tools are blocked on a release file."""
    deadline = time.monotonic() + timeout
    last_logs = ""
    target_count = baseline_count + expected_count
    while time.monotonic() < deadline:
        last_logs = _container_logs(container)
        if last_logs.count(release_file_path) >= target_count:
            return
        time.sleep(0.25)
    raise TimeoutError(
        f"release barriers were not observed: {release_file_path}, "
        f"baseline={baseline_count}, expected_new={expected_count}, "
        f"target={target_count}\n{last_logs[-4000:]}"
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
        output = decode_docker_exec_output(result.output)
        raise AssertionError(
            f"failed to update release file {release_file_path}: {output}"
        )


def _tool_result_output_text(event: ChatEventResponse) -> str | None:
    """Return persisted client tool result text for a history event."""
    if event.kind != "client_tool_result":
        return None
    output = ToolResultObservation.model_validate(event.payload).output
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        texts: list[str] = []
        for part in output:
            if not isinstance(part, dict):
                continue
            text = _OutputPartObservation.model_validate(part).text
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
) -> ChatEventResponse:
    """Wait until a client tool result contains expected text."""
    deadline = time.monotonic() + timeout
    last_outputs: list[str] = []
    while time.monotonic() < deadline:
        last_outputs = []
        for event in _history(
            public_url=public_url, token=token, session_id=session_id
        ):
            if event.kind != "client_tool_result":
                continue
            payload = ToolResultObservation.model_validate(event.payload)
            if payload.call_id != call_id:
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


def _wait_for_tool_result_outcome(
    *,
    public_url: str,
    token: str,
    session_id: str,
    call_id: str,
    outcome: str,
    reason: str | None = None,
    timeout: float = 120,
) -> ChatEventResponse:
    """Wait until a WaitToolkit result contains the expected JSON outcome."""
    deadline = time.monotonic() + timeout
    last_outputs: list[str] = []
    while time.monotonic() < deadline:
        last_outputs = []
        for event in _history(
            public_url=public_url, token=token, session_id=session_id
        ):
            if event.kind != "client_tool_result":
                continue
            payload = ToolResultObservation.model_validate(event.payload)
            if payload.call_id != call_id:
                continue
            output = _tool_result_output_text(event)
            if output is None:
                continue
            last_outputs.append(output)
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                parsed_outcome = _WaitOutcomeObservation.model_validate(parsed)
                if parsed_outcome.outcome == outcome and (
                    reason is None or parsed_outcome.reason == reason
                ):
                    return event
        time.sleep(0.5)
    raise TimeoutError(
        f"tool result outcome not observed: {call_id}, {(outcome, reason)!r}, "
        f"{last_outputs!r}"
    )


def _wait_for_listed_agents(
    *,
    public_url: str,
    token: str,
    session_id: str,
    call_id: str,
    timeout: float = 120,
) -> list[_ListedAgentObservation]:
    """Decode the native list_agents result at its embedded JSON boundary."""
    deadline = time.monotonic() + timeout
    last_outputs: list[str] = []
    while time.monotonic() < deadline:
        last_outputs = []
        for event in _history(
            public_url=public_url,
            token=token,
            session_id=session_id,
        ):
            if event.kind != "client_tool_result":
                continue
            payload = ToolResultObservation.model_validate(event.payload)
            if payload.call_id != call_id:
                continue
            output = _tool_result_output_text(event)
            if output is None:
                continue
            last_outputs.append(output)
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return _ListedAgentsObservation.model_validate(parsed).agents
        time.sleep(0.5)
    raise TimeoutError(f"JSON tool result not observed: {call_id}, {last_outputs!r}")


def _run_marker_completed(event: ChatEventResponse) -> bool:
    """Return whether a history event is a completed run marker."""
    if event.kind != "run_marker":
        return False
    return RunMarkerObservation.model_validate(event.payload).status == "completed"


def _wait_for_run_complete(
    *,
    public_url: str,
    token: str,
    session_id: str,
    timeout: float = 120,
) -> ChatEventResponse:
    """Wait until a session history contains a completed run marker."""
    deadline = time.monotonic() + timeout
    last_kinds: list[object] = []
    while time.monotonic() < deadline:
        events = _history(public_url=public_url, token=token, session_id=session_id)
        for event in events:
            if _run_marker_completed(event):
                return event
        last_kinds = [event.kind for event in events]
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


def _subagent_tree(
    *,
    public_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> _TreeObservation:
    """Fetch the Subagent Tree projection."""
    response = requests.get(
        f"{public_url}/chat/v1/agents/{agent_id}/sessions/{session_id}/subagents/tree",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return _TreeObservation.model_validate(response.json())


def _tree_nodes(tree: _TreeObservation) -> list[_TreeNode]:
    """Return validated tree root nodes."""
    return tree.nodes


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
    expected_latest_run_status: str | None = None,
    timeout: float = 120,
) -> _ChildNodeObservation:
    """Wait until a named child appears with the expected projected state."""
    deadline = time.monotonic() + timeout
    last_tree: _TreeObservation | None = None
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
            latest_run_status_ok = (
                expected_latest_run_status is None
                or child.latest_run_status == expected_latest_run_status
            )
            if status_ok and unread_ok and latest_run_status_ok:
                return _ChildNodeObservation(tree=tree, child=child)
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
    return AgentSessionResponse.model_validate(response.json()).run_state


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
    payload = _SessionIdsObservation.model_validate(response.json())
    return {item.id for item in payload.items}


@pytest.fixture(scope="class")
def shared_subagent_setup(
    request: pytest.FixtureRequest,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    system_bootstrap_evidence: SystemBootstrapEvidence,
    azents_engine_worker_container: DockerContainer,
) -> _SharedSubagentSetup:
    """Prepare one Workspace and two compatible Agent Runtimes."""
    public_api_client = azentspublicclient.ApiClient(
        configuration=azentspublicclient.Configuration(host=azents_public_server_url)
    )
    admin_api_client = azentsadminclient.ApiClient(
        configuration=azentsadminclient.Configuration(
            host=azents_admin_server_url,
            access_token=system_bootstrap_evidence.access_token,
        )
    )
    workspace = _setup_workspace(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    barrier_release_file_path = f"/tmp/azents-subagent-shared-{unique()}"
    _set_release_file(
        azents_engine_worker_container,
        barrier_release_file_path,
        present=True,
    )
    request.addfinalizer(
        lambda: _set_release_file(
            azents_engine_worker_container,
            barrier_release_file_path,
            present=True,
        )
    )
    return _SharedSubagentSetup(
        public_api_client=public_api_client,
        workspace=workspace,
        standard_agent_id=_create_agent(
            public_api_client,
            workspace,
            max_subagents=2,
        ),
        barrier_agent_id=_create_agent(
            public_api_client,
            workspace,
            release_file_path=barrier_release_file_path,
            max_subagents=3,
        ),
        barrier_release_file_path=barrier_release_file_path,
        barrier_log_baseline=0,
        engine_worker_container=azents_engine_worker_container,
    )


@pytest.fixture
def barrier_subagent_setup(
    request: pytest.FixtureRequest,
    shared_subagent_setup: _SharedSubagentSetup,
) -> _SharedSubagentSetup:
    """Reset the shared barrier Agent before one isolated journey."""
    setup = shared_subagent_setup
    AgentV1Api(setup.public_api_client).agent_v1_update_agent(
        handle=setup.workspace.handle,
        agent_id=setup.barrier_agent_id,
        agent_update_request=AgentUpdateRequest(
            subagent_settings=SubagentSettings(
                max_subagents=3,
                max_depth=1,
            )
        ),
        _headers=_headers(setup.workspace.token),
    )
    _set_release_file(
        setup.engine_worker_container,
        setup.barrier_release_file_path,
        present=False,
    )
    setup = replace(
        setup,
        barrier_log_baseline=_container_logs(setup.engine_worker_container).count(
            setup.barrier_release_file_path
        ),
    )
    request.addfinalizer(
        lambda: _set_release_file(
            setup.engine_worker_container,
            setup.barrier_release_file_path,
            present=True,
        )
    )
    return setup


class TestSubagents:
    """Subagent user-facing behavior E2E coverage."""

    def test_spawn_wait_tree_projection_and_child_detail_history(
        self,
        azents_public_server_url: str,
        shared_subagent_setup: _SharedSubagentSetup,
    ) -> None:
        """Spawn a child, open child detail history, and observe it via wait."""
        workspace = shared_subagent_setup.workspace
        agent_id = shared_subagent_setup.standard_agent_id
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

        assert root_tree.root_agent_session_id == root_session_id
        assert root_tree.current_session_agent_id == root_tree.root_session_agent_id
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
        assert child_tree.root_agent_session_id == root_session_id
        assert child_tree.current_session_agent_id == child.session_agent_id

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
        _wait_for_tool_result_outcome(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_WAIT_CALL_ID,
            outcome="not_waitable",
            reason="all_descendants_idle",
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
        assert completed_result.content == _CHILD_RESPONSE
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
            if payload.message_kind == "agent_result"
            and payload.source_path == "/root/child_qa"
            and payload.run_status == "completed"
        ]
        assert len(completed_results) == 1

    def test_targetless_wait_without_descendants_returns_immediately(
        self,
        azents_public_server_url: str,
        shared_subagent_setup: _SharedSubagentSetup,
    ) -> None:
        """Return a no-descendants result without creating a child."""
        workspace = shared_subagent_setup.workspace
        agent_id = shared_subagent_setup.standard_agent_id
        root_session_id = _create_root_session(
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
        _wait_for_tool_result_outcome(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_NO_DESCENDANTS_CALL_ID,
            outcome="not_waitable",
            reason="no_descendants",
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
        azents_public_server_url: str,
        barrier_subagent_setup: _SharedSubagentSetup,
    ) -> None:
        """Report a timeout when a zero-duration wait expires."""
        workspace = barrier_subagent_setup.workspace
        agent_id = barrier_subagent_setup.barrier_agent_id
        release_file_path = barrier_subagent_setup.barrier_release_file_path
        azents_engine_worker_container = barrier_subagent_setup.engine_worker_container
        root_session_id = _create_root_session(
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
            baseline_count=barrier_subagent_setup.barrier_log_baseline,
            expected_count=1,
        )

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_ACTIVE_TIMEOUT_WAIT_MESSAGE,
        )
        wait_event = _wait_for_tool_result_outcome(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_ACTIVE_TIMEOUT_CALL_ID,
            outcome="timed_out",
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
        azents_public_server_url: str,
        barrier_subagent_setup: _SharedSubagentSetup,
    ) -> None:
        """Stop an interrupted child and promote its safe terminal result."""
        workspace = barrier_subagent_setup.workspace
        agent_id = barrier_subagent_setup.barrier_agent_id
        root_session_id = _create_root_session(
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
            barrier_subagent_setup.engine_worker_container,
            barrier_subagent_setup.barrier_release_file_path,
            baseline_count=barrier_subagent_setup.barrier_log_baseline,
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
        _, interrupted_child = _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="interrupt_child",
            expected_status="interrupted",
            expected_unread=None,
            expected_latest_run_status="stopped",
        )
        assert interrupted_child.terminal_result_event_id is None
        assert interrupted_child.terminal_result_message is None
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
        assert stopped_result.content == "The agent run was stopped."
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
        azents_public_server_url: str,
        shared_subagent_setup: _SharedSubagentSetup,
    ) -> None:
        """Promote a failed child result without internal provider text."""
        workspace = shared_subagent_setup.workspace
        agent_id = shared_subagent_setup.standard_agent_id
        root_session_id = _create_root_session(
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
        failed_content = failed_result.content
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


class SubagentCapacityScenarios:
    """Reusable mailbox and capacity scenarios for a separate collector."""

    def test_targetless_wait_observes_any_child_mailbox_message(
        self,
        azents_public_server_url: str,
        barrier_subagent_setup: _SharedSubagentSetup,
        mock_openai_url: str,
    ) -> None:
        """Observe one child message while every descendant remains active."""
        _reset_mock_openai(mock_openai_url)
        workspace = barrier_subagent_setup.workspace
        agent_id = barrier_subagent_setup.barrier_agent_id
        release_file_path = barrier_subagent_setup.barrier_release_file_path
        azents_engine_worker_container = barrier_subagent_setup.engine_worker_container
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
            baseline_count=barrier_subagent_setup.barrier_log_baseline,
            expected_count=2,
        )
        wait_event = _wait_for_tool_result_outcome(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_MAILBOX_WAIT_CALL_ID,
            outcome="activity",
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

    def test_bounded_list_contract_and_historical_reuse(
        self,
        azents_public_server_url: str,
        shared_subagent_setup: _SharedSubagentSetup,
    ) -> None:
        """Bound inactive history while preserving canonical child reuse."""
        workspace = shared_subagent_setup.workspace
        agent_id = shared_subagent_setup.standard_agent_id
        root_session_id = _create_root_session(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
        )
        child_names = (
            "bounded_oldest",
            "bounded_middle",
            "bounded_newest",
        )

        for message, child_name in zip(
            _BOUNDED_SPAWN_MESSAGES,
            child_names,
            strict=True,
        ):
            _run_message(
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=root_session_id,
                message=message,
            )
            _wait_for_child_node(
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=root_session_id,
                name=child_name,
                expected_status="completed",
                expected_unread=True,
            )
            _wait_for_session_run_state(
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=root_session_id,
                expected="idle",
            )

        initial_tree = _subagent_tree(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
        )
        initial_nodes = _tree_nodes(initial_tree)
        oldest = _find_node(initial_nodes, "bounded_oldest")
        assert oldest is not None
        for child_name in child_names:
            assert _find_node(initial_nodes, child_name) is not None

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_BOUNDED_LIST_MESSAGE,
        )
        first_list = _wait_for_listed_agents(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_BOUNDED_LIST_CALL_ID,
        )
        assert [agent.model_dump() for agent in first_list] == [
            {"agent_name": "/root", "agent_status": "running"},
            {
                "agent_name": "/root/bounded_middle",
                "agent_status": "completed",
            },
            {
                "agent_name": "/root/bounded_newest",
                "agent_status": "completed",
            },
        ]
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_BOUNDED_LIST_RESPONSE,
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
            message=_BOUNDED_FOLLOWUP_MESSAGE,
        )
        _wait_for_tool_result_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_BOUNDED_FOLLOWUP_CALL_ID,
            expected="assigned",
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=oldest.agent_session_id,
            expected=_BOUNDED_FOLLOWUP_TASK,
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=oldest.agent_session_id,
            expected=_BOUNDED_FOLLOWUP_RESPONSE,
        )
        _, reused = _wait_for_child_node(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            name="bounded_oldest",
            expected_status="completed",
            expected_unread=True,
        )
        assert reused.agent_session_id == oldest.agent_session_id

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_BOUNDED_RELIST_MESSAGE,
        )
        second_list = _wait_for_listed_agents(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_BOUNDED_RELIST_CALL_ID,
        )
        assert len(second_list) == 3
        assert second_list[0].model_dump() == {
            "agent_name": "/root",
            "agent_status": "running",
        }
        assert any(agent.agent_name == "/root/bounded_oldest" for agent in second_list)
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_BOUNDED_RELIST_RESPONSE,
        )
        reused_results = [
            payload
            for payload in _agent_message_payloads(
                public_url=azents_public_server_url,
                token=workspace.token,
                session_id=root_session_id,
            )
            if payload.message_kind == "agent_result"
            and payload.source_path == "/root/bounded_oldest"
            and payload.content == _BOUNDED_FOLLOWUP_RESPONSE
        ]
        assert len(reused_results) == 1
        final_nodes = _tree_nodes(
            _subagent_tree(
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=root_session_id,
            )
        )
        for child_name in child_names:
            assert _find_node(final_nodes, child_name) is not None

    def test_active_overflow_remains_visible_and_blocks_new_activation(
        self,
        azents_public_server_url: str,
        barrier_subagent_setup: _SharedSubagentSetup,
    ) -> None:
        """Keep active children visible after a capacity reduction."""
        public_api_client = barrier_subagent_setup.public_api_client
        workspace = barrier_subagent_setup.workspace
        agent_id = barrier_subagent_setup.barrier_agent_id
        release_file_path = barrier_subagent_setup.barrier_release_file_path
        azents_engine_worker_container = barrier_subagent_setup.engine_worker_container
        root_session_id = _create_root_session(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
        )
        overflow_names = ("overflow_one", "overflow_two", "overflow_three")

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_OVERFLOW_SPAWN_MESSAGE,
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_OVERFLOW_SPAWN_RESPONSE,
        )
        for child_name in overflow_names:
            _wait_for_child_node(
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=root_session_id,
                name=child_name,
                expected_status="running",
                expected_unread=False,
            )
        _wait_for_release_barriers(
            azents_engine_worker_container,
            release_file_path,
            baseline_count=barrier_subagent_setup.barrier_log_baseline,
            expected_count=3,
        )
        _wait_for_session_run_state(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            expected="idle",
        )

        updated = AgentV1Api(public_api_client).agent_v1_update_agent(
            handle=workspace.handle,
            agent_id=agent_id,
            agent_update_request=AgentUpdateRequest(
                subagent_settings=SubagentSettings(
                    max_subagents=1,
                    max_depth=1,
                )
            ),
            _headers=_headers(workspace.token),
        )
        assert updated.subagent_settings.max_subagents == 1

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_OVERFLOW_LIST_MESSAGE,
        )
        active_list = _wait_for_listed_agents(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_OVERFLOW_LIST_CALL_ID,
        )
        assert [agent.model_dump() for agent in active_list] == [
            {"agent_name": "/root", "agent_status": "running"},
            {"agent_name": "/root/overflow_one", "agent_status": "running"},
            {"agent_name": "/root/overflow_three", "agent_status": "running"},
            {"agent_name": "/root/overflow_two", "agent_status": "running"},
        ]
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_OVERFLOW_LIST_RESPONSE,
        )

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_OVERFLOW_REJECT_MESSAGE,
        )
        _wait_for_tool_result_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_OVERFLOW_REJECT_CALL_ID,
            expected="max_subagents 1 is already reached",
        )
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_OVERFLOW_REJECT_RESPONSE,
        )
        overflow_tree = _tree_nodes(
            _subagent_tree(
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=root_session_id,
            )
        )
        assert _find_node(overflow_tree, "overflow_four") is None

        _set_release_file(
            azents_engine_worker_container,
            release_file_path,
            present=True,
        )
        for child_name in overflow_names:
            _wait_for_child_node(
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=root_session_id,
                name=child_name,
                expected_status="completed",
                expected_unread=True,
            )

        _run_message(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_OVERFLOW_CONTRACTED_LIST_MESSAGE,
        )
        contracted = _wait_for_listed_agents(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            call_id=_OVERFLOW_CONTRACTED_LIST_CALL_ID,
        )
        assert len(contracted) == 2
        assert contracted[0].model_dump() == {
            "agent_name": "/root",
            "agent_status": "running",
        }
        contracted_child_name = contracted[1].agent_name
        assert contracted_child_name in {
            "/root/overflow_one",
            "/root/overflow_two",
            "/root/overflow_three",
        }
        assert contracted[1].agent_status == "completed"
        _wait_for_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=root_session_id,
            expected=_OVERFLOW_CONTRACTED_LIST_RESPONSE,
        )
        final_tree = _tree_nodes(
            _subagent_tree(
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=root_session_id,
            )
        )
        for child_name in overflow_names:
            assert _find_node(final_tree, child_name) is not None
