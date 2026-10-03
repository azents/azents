"""Agent execution durable persistence E2E test."""

import json
import os
import select
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.chat_v1_api import ChatV1Api
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
from azentspublicclient.models.agent_toolkit_config_create_request import (
    AgentToolkitConfigCreateRequest,
)
from azentspublicclient.models.agent_toolkit_config_update_request import (
    AgentToolkitConfigUpdateRequest,
)
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.chat_event_page_response import ChatEventPageResponse
from azentspublicclient.models.chat_event_response import ChatEventResponse
from azentspublicclient.models.chat_write_response import ChatWriteResponse
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.live_event_list_response import LiveEventListResponse
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from azentspublicclient.models.toolkit_config_update_request import (
    ToolkitConfigUpdateRequest,
)
from pydantic import TypeAdapter, ValidationError
from testcontainers.core.container import DockerContainer
from websockets.sync.client import connect as ws_connect
from websockets.sync.connection import Connection

from support.observations import (
    ChatActionObservation,
    DockerNetworkObservation,
    FailedRunObservation,
    InputMessageObservation,
    RunMarkerObservation,
    SystemErrorObservation,
    ToolCallObservation,
    ToolkitSourceObservation,
    ToolResultObservation,
    TurnMarkerObservation,
    UsageObservation,
    decode_chat_write,
    decode_history_page,
    decode_runtime_hook,
    decode_session,
)
from support.runtime_profiles import (
    create_workspace_runtime_profile,
    start_and_wait_for_agent_runtime,
)
from support.system_bootstrap import SystemBootstrapEvidence
from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    single_candidate_model_options,
    unique,
)

_HELLO = "Event durable hello"
_HELLO_RESPONSE = "Event durable hello response."
_SECOND = "Event durable second turn"
_SECOND_RESPONSE = "Event durable second response."
_TIMELINE_FIRST = "Timeline reliability first turn"
_TIMELINE_FIRST_REASONING = "Timeline reliability first reasoning."
_TIMELINE_FIRST_RESPONSE = "Timeline reliability first response."
_TIMELINE_SECOND = "Timeline reliability second turn"
_TIMELINE_SECOND_REASONING = "Timeline reliability second reasoning."
_TIMELINE_SECOND_RESPONSE = "Timeline reliability second response."
_CANONICAL_WS_ACTION_TYPES = frozenset(
    {
        "action_execution_removed",
        "action_execution_updated",
        "mailbox_item_removed",
        "mailbox_item_upserted",
        "history_event_appended",
        "input_actions_updated",
        "live_event_removed",
        "live_event_upserted",
        "live_projection_reset",
        "live_run_cleared",
        "live_run_updated",
        "subagent_tree_changed",
        "subscribed",
        "subscription_health_check_ack",
        "todo_state_changed",
    }
)
_COMPACT_SEED = "Event durable compact seed"
_COMPACT_SEED_RESPONSE = "Event durable compact seed response."
_AFTER_COMPACT = "Event durable after compact"
_AFTER_COMPACT_RESPONSE = "Event durable after compact response."
_TOOL_PROMPT = "Start chat input buffer long tool"
_TOOL_RESPONSE = "Chat input buffer long tool completed."
_TOOL_NAME = "bufferqa__runtime_hook_qa_probe"
_TOOL_CALL_ID = "call_chat_input_buffer_delay"
_DUPLICATE_MCP_BASE_SLUG = "dupmcp"
_TESTENV_ROOT = Path(__file__).parents[5]
_MOCK_MCP_SCRIPT = _TESTENV_ROOT / "fixtures" / "mock_mcp_server.py"
_RETRY_ONCE = "Failed run retry once then succeed"
_RETRY_ONCE_RESPONSE = "Failed run retry recovered after one attempt."
_RETRY_ACROSS_TURNS = "Failed run retry resets across model turns"
_RETRY_ACROSS_TURNS_CALL_ID = "call_failed_run_retry_turn_boundary"
_RETRY_MANUAL = "Failed run retry exhaust then manual recover"
_RETRY_MANUAL_RESPONSE = "Manual failed-run retry recovered successfully."
_RETRY_STALE = "Failed run retry stale conflict"
_SANITIZED_PROVIDER_RETRY_MESSAGE = (
    "Model provider error: Deterministic provider failure. "
    "api_key=[REDACTED] Bearer [REDACTED] request rejected."
)
_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


@dataclass(frozen=True)
class _Workspace:
    """Agent execution E2E resource t."""

    token: str
    email: str
    handle: str
    model_selection: AgentModelSelectionInput
    runtime_profile_id: str


@dataclass(frozen=True)
class _ExecutionAgentSetup:
    """Shared immutable workspace and Agent runtime."""

    workspace: _Workspace
    agent_id: str


@dataclass(frozen=True)
class _RunResult:
    """REST write run result."""

    session_id: str


def _headers(token: str) -> dict[str, str]:
    """Bearer auth header t t."""
    return {"Authorization": f"Bearer {token}"}


@dataclass(frozen=True)
class _MockMcpInstance:
    """A subprocess URL and its optional first-call control channels."""

    url: str
    reached_fd: int | None
    release_fd: int | None

    def wait_until_reached(self, timeout: float = 15) -> None:
        """Observe the held call without depending on its wall-clock duration."""
        if self.reached_fd is None:
            raise AssertionError("This MCP fixture does not have a call barrier.")
        readable, _, _ = select.select([self.reached_fd], [], [], timeout)
        if not readable:
            raise TimeoutError("MCP instance call did not reach its barrier.")
        if os.read(self.reached_fd, 1) != b"R":
            raise AssertionError("MCP instance reached channel was closed.")

    def release(self) -> None:
        """Release a held call before its process/control channels are cleaned up."""
        if self.release_fd is not None:
            os.write(self.release_fd, b"R")


@contextmanager
def _mock_mcp_instance(
    identity: str,
    *,
    docker_gateway: str,
    hold_first_instance: bool,
) -> Generator[_MockMcpInstance, None, None]:
    """Run one distinguishable MCP subprocess with explicit one-shot ordering."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {
        **os.environ,
        "MOCK_MCP_HOST": "0.0.0.0",
        "MOCK_MCP_PORT": str(port),
        "MOCK_MCP_INSTANCE": identity,
    }
    with ExitStack() as controls:
        reached_fd: int | None = None
        release_fd: int | None = None
        child_fds: tuple[int, ...] = ()
        if hold_first_instance:
            reached_fd, reached_writer = os.pipe()
            release_reader, release_fd = os.pipe()
            for descriptor in (reached_fd, reached_writer, release_reader, release_fd):
                controls.callback(os.close, descriptor)
            environment["MOCK_MCP_INSTANCE_REACHED_FD"] = str(reached_writer)
            environment["MOCK_MCP_INSTANCE_RELEASE_FD"] = str(release_reader)
            child_fds = (reached_writer, release_reader)
        process = subprocess.Popen(
            [sys.executable, str(_MOCK_MCP_SCRIPT)],
            cwd=_TESTENV_ROOT,
            env=environment,
            pass_fds=child_fds,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        instance = _MockMcpInstance(
            url=f"http://{docker_gateway}:{port}/mcp",
            reached_fd=reached_fd,
            release_fd=release_fd,
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise TimeoutError(f"Mock MCP instance {identity!r} did not start.")
            yield instance
        finally:
            instance.release()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _docker_gateway(container: DockerContainer) -> str:
    """Return the host gateway reachable from one E2E container network."""
    wrapped = container.get_wrapped_container()
    wrapped.reload()
    networks = wrapped.attrs["NetworkSettings"]["Networks"]
    for network in networks.values():
        observation = DockerNetworkObservation.model_validate(network)
        if observation.gateway:
            return observation.gateway
    raise AssertionError("E2E container network did not expose a Docker gateway.")


def _json_object_payload(payload: object, *, label: str) -> dict[str, object]:
    """JSON object payload t verifyt returnt."""
    try:
        return _JSON_OBJECT.validate_python(payload)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object: {payload!r}") from exc


def _json_object_list_payload(
    payload: object,
    *,
    label: str,
) -> list[dict[str, object]]:
    """JSON object list payload t verifyt returnt."""
    try:
        return _JSON_OBJECT_LIST.validate_python(payload)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object list: {payload!r}") from exc


def _json_object(response: requests.Response) -> dict[str, object]:
    """HTTP JSON responset object dict t verifyt returnt."""
    return _json_object_payload(response.json(), label="HTTP JSON response")


def _ws_url(http_url: str) -> str:
    """Convert an HTTP server URL to its WebSocket equivalent."""
    if http_url.startswith("http://"):
        return "ws://" + http_url.removeprefix("http://")
    if http_url.startswith("https://"):
        return "wss://" + http_url.removeprefix("https://")
    return http_url


def _team_primary_session_id(
    *,
    server_url: str,
    token: str,
    agent_id: str,
) -> str:
    """Return the team-primary session ID for an Agent."""
    response = requests.get(
        f"{server_url}/chat/v1/agents/{agent_id}/team-primary-session",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return decode_session(response.json()).id


def _create_execution_session(
    *,
    server_url: str,
    token: str,
    agent_id: str,
) -> str:
    """Create one independent non-primary Session for a persistence test."""
    response = requests.post(
        f"{server_url}/chat/v1/agents/{agent_id}/sessions",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"existing_project_paths": [], "setup_actions": []},
        timeout=10,
    )
    response.raise_for_status()
    return decode_session(response.json()).id


def _connect_chat(
    *,
    public_api_client: azentspublicclient.ApiClient,
    server_url: str,
    token: str,
    session_id: str,
) -> Connection:
    """Connect to an existing Chat session through the public WebSocket."""
    ticket = (
        ChatV1Api(public_api_client)
        .chat_v1_issue_ws_ticket(_headers=_headers(token))
        .ticket
    )
    return ws_connect(
        f"{_ws_url(server_url)}/chat/v1/sessions/{session_id}?ticket={ticket}"
    )


def _receive_ws_action(ws: Connection, *, timeout: float) -> ChatActionObservation:
    """Receive and validate one canonical public Chat WebSocket action."""
    raw = ws.recv(timeout=timeout)
    action = ChatActionObservation.model_validate_json(raw)
    assert action.type in _CANONICAL_WS_ACTION_TYPES, action
    assert "kind" not in (action.model_extra or {}), action
    return action


def _wait_for_ws_action(
    ws: Connection,
    *,
    action_type: str,
    mailbox_item_id: str | None = None,
    timeout: float = 10,
) -> ChatActionObservation:
    """Wait for a canonical WebSocket action of the requested type."""
    deadline = time.monotonic() + timeout
    observed: list[object] = []
    while time.monotonic() < deadline:
        try:
            action = _receive_ws_action(ws, timeout=1)
        except TimeoutError:
            continue
        observed.append(action.type)
        if action.type != action_type:
            continue
        if mailbox_item_id is not None:
            if action.mailbox_item_id != mailbox_item_id:
                continue
        return action
    raise TimeoutError(f"WebSocket action was not observed: {action_type}, {observed}")


def _wait_for_ws_turn(
    ws: Connection,
    *,
    session_id: str,
    user_message: str,
    reasoning_summary: str,
    assistant_message: str,
    timeout: float = 120,
) -> list[ChatEventResponse]:
    """Collect canonical durable append actions through one completed turn."""
    deadline = time.monotonic() + timeout
    events: list[ChatEventResponse] = []
    event_ids: set[str] = set()
    while time.monotonic() < deadline:
        try:
            action = _receive_ws_action(ws, timeout=5)
        except TimeoutError:
            continue
        if "session_id" in action.model_fields_set:
            assert action.session_id == session_id, action
        else:
            assert action.type in {
                "subagent_tree_changed",
                "todo_state_changed",
            }, action
        if action.type != "history_event_appended":
            continue
        event = action.event
        assert event is not None, action
        assert event.session_id == session_id, event
        event_id = event.id
        assert event_id not in event_ids, event
        event_ids.add(event_id)
        events.append(event)

        kinds = [item.kind for item in events]
        contents: list[str] = []
        reasoning: list[str] = []
        for item in events:
            if item.kind not in {"user_message", "assistant_message", "reasoning"}:
                continue
            payload = InputMessageObservation.model_validate(item.payload)
            content = payload.content
            if isinstance(content, str):
                contents.append(content)
            summary = payload.summary
            if isinstance(summary, str):
                reasoning.append(summary)
        terminal = (
            event.kind == "run_marker"
            and RunMarkerObservation.model_validate(event.payload).status == "completed"
        )
        if (
            terminal
            and user_message in contents
            and assistant_message in contents
            and reasoning_summary in reasoning
            and "user_message" in kinds
            and "assistant_message" in kinds
            and "reasoning" in kinds
        ):
            return events
    raise TimeoutError(
        f"Completed canonical WebSocket turn was not observed: "
        f"{user_message!r}, {events!r}"
    )


def _setup_workspace(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
) -> _Workspace:
    """workspacet model selection t t API t t."""
    uniq = unique()
    token, _, email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"agent-execution-{uniq}@example.com",
    )
    handle = f"agent-execution-{uniq}"

    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Agent Execution QA {uniq}",
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
            secrets=Secrets(ApiKeySecrets(api_key="sk-agent-execution-qa")),
        ),
        _headers=_headers(token),
    )
    return _Workspace(
        token=token,
        email=email,
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
    with_toolkit: bool = False,
    tool_search_enabled: bool = False,
) -> str:
    """testt agent t t API t createt."""
    headers = _headers(workspace.token)
    toolkit_id: str | None = None
    if with_toolkit:
        toolkit = ToolkitV1Api(public_api_client).toolkit_v1_create_toolkit_config(
            handle=workspace.handle,
            toolkit_config_create_request=ToolkitConfigCreateRequest(
                toolkit_type="runtime_hook_qa",
                slug="bufferqa",
                name="Agent Execution Durable QA Toolkit",
                config={"mode": "observe"},
                enabled=True,
            ),
            _headers=headers,
        )
        toolkit_id = toolkit.id

    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name="Agent Execution Durable QA Agent",
            selectable_model_options=single_candidate_model_options(
                workspace.model_selection
            ),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
            runtime_profile_id=workspace.runtime_profile_id,
            tool_search_enabled=tool_search_enabled,
        ),
        _headers=headers,
    )
    if toolkit_id is not None:
        ToolkitV1Api(public_api_client).toolkit_v1_attach_toolkit_to_agent(
            handle=workspace.handle,
            agent_id=agent.id,
            agent_toolkit_attach_request=AgentToolkitAttachRequest(
                toolkit_id=toolkit_id,
            ),
            _headers=headers,
        )
    start_and_wait_for_agent_runtime(
        public_api_client,
        token=workspace.token,
        workspace_handle=workspace.handle,
        agent_id=agent.id,
    )
    return agent.id


def _run_message(
    *,
    public_api_client: azentspublicclient.ApiClient,
    public_url: str,
    token: str,
    agent_id: str,
    message: str,
    session_id: str | None = None,
) -> _RunResult:
    """REST write boundary t t user message turn t runt."""
    del public_api_client
    if session_id is None:
        session_response = requests.get(
            f"{public_url}/chat/v1/agents/{agent_id}/team-primary-session",
            headers=_headers(token),
            timeout=10,
        )
        session_response.raise_for_status()
        session_id_value = decode_session(session_response.json()).id
    else:
        session_id_value = session_id
    path = f"/chat/v1/sessions/{session_id_value}/inputs"
    response = requests.post(
        f"{public_url}{path}",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"agent-execution-message-{unique()}",
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
    return _RunResult(session_id=decode_chat_write(response.json()).session_id)


def _run_command(
    *,
    public_api_client: azentspublicclient.ApiClient,
    public_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    command: str,
) -> None:
    """REST write boundary t command t runt history t t."""
    del public_api_client
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"agent-execution-command-{unique()}",
            "message": "",
            "action": {"type": "command", "name": command},
            "inference_profile": None,
        },
        timeout=10,
    )
    response.raise_for_status()
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        payload = _list_history(
            server_url=public_url,
            token=token,
            session_id=session_id,
        )
        if {"compaction_marker", "compaction_summary"} <= set(_message_roles(payload)):
            return
        time.sleep(0.5)
    raise TimeoutError(f"command did not complete: {command}")


def _edit_user_message(
    *,
    public_api_client: azentspublicclient.ApiClient,
    public_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    message_id: str,
    message: str,
) -> None:
    """REST write boundary t user message edit t t."""
    del public_api_client
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/edit-message",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"agent-execution-edit-{unique()}",
            "message_id": message_id,
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


def _list_history(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> ChatEventPageResponse:
    """REST history event page t fetcht."""
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return decode_history_page(response.json())


def _history_page(
    *,
    server_url: str,
    token: str,
    session_id: str,
    limit: int,
    before: str | None,
    after: str | None,
) -> ChatEventPageResponse:
    """Fetch one raw durable history page with explicit cursor direction."""
    params: dict[str, int | str] = {"limit": limit}
    if before is not None:
        params["before"] = before
    if after is not None:
        params["after"] = after
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/history",
        headers=_headers(token),
        params=params,
        timeout=10,
    )
    response.raise_for_status()
    return decode_history_page(response.json())


def _list_live(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> LiveEventListResponse:
    """Fetch the REST live projection."""
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/live",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    live = LiveEventListResponse.from_dict(response.json())
    if live is None:
        raise ValueError("Expected a REST live projection object.")
    return live


def _wait_for_session_idle(
    *,
    server_url: str,
    token: str,
    session_id: str,
    timeout: float,
) -> None:
    """Wait until the authoritative live projection reports an idle Session."""
    deadline = time.monotonic() + timeout
    last_payload: LiveEventListResponse | None = None
    while time.monotonic() < deadline:
        last_payload = _list_live(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        if last_payload.session_run_state == "idle":
            return
        time.sleep(0.5)
    raise TimeoutError(f"Session did not become idle: {last_payload!r}")


def _history_events(
    payload: ChatEventPageResponse | dict[str, object],
) -> list[ChatEventResponse]:
    """Return typed events, validating legacy callers at their boundary."""
    page = (
        payload
        if isinstance(payload, ChatEventPageResponse)
        else decode_history_page(payload)
    )
    return page.items


def _system_error_events(
    payload: ChatEventPageResponse | dict[str, object],
) -> list[ChatEventResponse]:
    """Return durable system-error observations."""
    return [event for event in _history_events(payload) if event.kind == "system_error"]


def _failed_run_error_events(
    payload: ChatEventPageResponse | dict[str, object],
) -> list[ChatEventResponse]:
    """Return terminal failed-run errors from typed failure controls."""
    failed_events: list[ChatEventResponse] = []
    for event in _system_error_events(payload):
        failure = SystemErrorObservation.model_validate(event.payload).failure
        if failure is not None and failure.kind == "failed_run":
            failed_events.append(event)
    return failed_events


def _retry_failed_run(
    *,
    public_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    failed_event_id: str,
) -> ChatWriteResponse:
    """Post a manual failed-run retry and return the response."""
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/retry-failed-run",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "failed_event_id": failed_event_id,
            "client_request_id": f"agent-execution-failed-retry-{unique()}",
        },
        timeout=10,
    )
    response.raise_for_status()
    return decode_chat_write(response.json())


def _wait_for_live_retry(
    *,
    server_url: str,
    token: str,
    session_id: str,
    failed_attempt_count: int,
    timeout: float = 20,
) -> LiveEventListResponse:
    """Wait until /live exposes a failed-run retry state."""
    deadline = time.monotonic() + timeout
    last_payload: LiveEventListResponse | None = None
    while time.monotonic() < deadline:
        payload = _list_live(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        last_payload = payload
        if payload.run is not None and payload.run.retry is not None:
            if payload.run.retry.failed_attempt_count >= failed_attempt_count:
                return payload
        time.sleep(0.1)
    raise TimeoutError(f"live retry was not observed: {last_payload!r}")


def _wait_for_failed_run_error(
    *,
    server_url: str,
    token: str,
    session_id: str,
    expected_attempts: int,
    timeout: float = 30,
) -> ChatEventPageResponse:
    """Wait until a terminal failed-run error is eligible for idle-only controls."""
    deadline = time.monotonic() + timeout
    last_payload: ChatEventPageResponse | None = None
    last_live_payload: LiveEventListResponse | None = None
    while time.monotonic() < deadline:
        payload = _list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        last_payload = payload
        failed_events = _failed_run_error_events(payload)
        if failed_events:
            failure = _failed_run(failed_events[-1])
            attempts = failure.attempts
            assert attempts is not None
            if len(attempts) == expected_attempts:
                live_payload = _list_live(
                    server_url=server_url,
                    token=token,
                    session_id=session_id,
                )
                last_live_payload = live_payload
                if live_payload.session_run_state == "idle":
                    return payload
        time.sleep(0.5)
    raise TimeoutError(
        "failed-run error was not eligible for idle-only controls: "
        f"history={last_payload!r}, live={last_live_payload!r}"
    )


def _failed_run(event: ChatEventResponse) -> FailedRunObservation:
    """Decode controls of an already-selected failed-run event."""
    failure = SystemErrorObservation.model_validate(event.payload).failure
    assert failure is not None and failure.kind == "failed_run"
    return failure


def _event_content(event: ChatEventResponse) -> object:
    """Interpret content only for message/result event families."""
    if event.kind in {"user_message", "assistant_message"}:
        return InputMessageObservation.model_validate(event.payload).content
    if event.kind == "client_tool_result":
        return ToolResultObservation.model_validate(event.payload).output
    return None


def _message_contents(payload: ChatEventPageResponse | dict[str, object]) -> list[str]:
    """Return durable message and tool-result text content."""
    contents: list[str] = []
    for event in _history_events(payload):
        content = _event_content(event)
        if isinstance(content, str):
            contents.append(content)
    return contents


def _message_roles(payload: ChatEventPageResponse | dict[str, object]) -> list[str]:
    """Project historical compatibility role labels from declared event kinds."""
    roles = {
        "user_message": "user",
        "assistant_message": "assistant",
        "client_tool_call": "assistant",
        "client_tool_result": "tool",
        "turn_marker": "turn_complete",
        "run_marker": "run_complete",
    }
    return [roles.get(event.kind, event.kind) for event in _history_events(payload)]


def _message_id_for_content(payload: ChatEventPageResponse, content: str) -> str:
    """REST history t content t t message id t returnt."""
    for event in _history_events(payload):
        if _event_content(event) == content:
            return event.id
    raise AssertionError(f"message not found for content: {content!r}")


def _tool_call_names(payload: ChatEventPageResponse) -> list[str]:
    """REST history tool call name listt returnt."""
    return [
        ToolCallObservation.model_validate(event.payload).name
        for event in _history_events(payload)
        if event.kind == "client_tool_call"
    ]


def _tool_result_call_ids(payload: ChatEventPageResponse) -> list[str]:
    """REST history tool result call_id listt returnt."""
    return [
        ToolResultObservation.model_validate(event.payload).call_id
        for event in _history_events(payload)
        if event.kind == "client_tool_result"
    ]


def _tool_result_content(payload: ChatEventPageResponse, call_id: str) -> object:
    """Return one durable client-tool result payload by call ID."""
    for event in _history_events(payload):
        if event.kind != "client_tool_result":
            continue
        result = ToolResultObservation.model_validate(event.payload)
        if result.call_id == call_id:
            return result.output
    raise AssertionError(f"tool result not found for call: {call_id!r}")


def _assert_toolkit_call_source(
    payload: ChatEventPageResponse,
    call_id: str,
    *,
    toolkit_config_id: str,
    toolkit_name: str,
    toolkit_slug: str,
    toolkit_namespace: str,
    source_identity: dict[str, str],
) -> None:
    """Require one durable call to retain its exact Toolkit source identity."""
    for event in _history_events(payload):
        if event.kind != "client_tool_call":
            continue
        call = ToolCallObservation.model_validate(event.payload)
        if call.call_id != call_id:
            continue
        source = call.toolkit_source
        assert source is not None
        _assert_toolkit_source(
            source,
            toolkit_config_id=toolkit_config_id,
            toolkit_name=toolkit_name,
            toolkit_slug=toolkit_slug,
            toolkit_namespace=toolkit_namespace,
            source_identity=source_identity,
        )
        return
    raise AssertionError(f"Toolkit source not found for call: {call_id!r}")


def _assert_toolkit_source(
    source: ToolkitSourceObservation,
    *,
    toolkit_config_id: str,
    toolkit_name: str,
    toolkit_slug: str,
    toolkit_namespace: str,
    source_identity: dict[str, str],
) -> None:
    """Require one public Toolkit source projection to match its catalog identity."""
    assert source.toolkit_config_id == toolkit_config_id
    assert source.toolkit_name == toolkit_name
    assert source.toolkit_slug == toolkit_slug
    assert source.toolkit_namespace == toolkit_namespace
    assert source.source_identity == source_identity


def _wait_for_live_toolkit_source(
    *,
    server_url: str,
    token: str,
    session_id: str,
    call_id: str,
    toolkit_config_id: str,
    toolkit_name: str,
    toolkit_slug: str,
    toolkit_namespace: str,
    source_identity: dict[str, str],
    timeout: float = 15,
) -> None:
    """Require user-visible live activity to retain the selected Toolkit source."""
    deadline = time.monotonic() + timeout
    latest: LiveEventListResponse | None = None
    while time.monotonic() < deadline:
        latest = _list_live(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        for event in latest.partial_history.items:
            if event.kind != "client_tool_call":
                continue
            call = ToolCallObservation.model_validate(event.payload)
            if call.call_id != call_id:
                continue
            source = call.toolkit_source
            assert source is not None
            _assert_toolkit_source(
                source,
                toolkit_config_id=toolkit_config_id,
                toolkit_name=toolkit_name,
                toolkit_slug=toolkit_slug,
                toolkit_namespace=toolkit_namespace,
                source_identity=source_identity,
            )
            return
        time.sleep(0.05)
    raise TimeoutError(
        f"Live Toolkit source was not observed for {call_id!r}: {latest!r}"
    )


def _wait_for_runtime_hook_source(
    container: DockerContainer,
    *,
    tool_name: str,
    toolkit_namespace: str,
    timeout: float = 15,
) -> None:
    """Require the runtime hook to observe the final selected tool namespace."""
    deadline = time.monotonic() + timeout
    latest = ""
    while time.monotonic() < deadline:
        stdout, stderr = container.get_logs()
        latest = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        for line in latest.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            observation = decode_runtime_hook(value)
            if observation is None:
                continue
            if (
                observation.runtime_hook_qa_lifecycle == "on_before_tool_call"
                and observation.tool_name == tool_name
                and observation.toolkit_slug == toolkit_namespace
            ):
                return
        time.sleep(0.1)
    raise TimeoutError(
        "Runtime hook did not observe Toolkit source: "
        f"tool={tool_name!r}, namespace={toolkit_namespace!r}, "
        f"logs={latest[-4000:]!r}"
    )


def _run_complete_ids(payload: ChatEventPageResponse) -> list[str]:
    """Return durable run boundary identities."""
    return [
        event.id for event in _history_events(payload) if event.kind == "run_marker"
    ]


def _turn_usage_items(payload: ChatEventPageResponse) -> list[UsageObservation]:
    """Return validated token evidence from durable turn boundaries."""
    usages: list[UsageObservation] = []
    for event in _history_events(payload):
        if event.kind != "turn_marker":
            continue
        usage = TurnMarkerObservation.model_validate(event.payload).usage
        if usage is not None:
            usages.append(usage)
    return usages


def _wait_for_rest_contents(
    *,
    server_url: str,
    token: str,
    session_id: str,
    expected: list[str],
    timeout: float = 90,
) -> ChatEventPageResponse:
    """REST history t expected content t t t t t."""
    deadline = time.monotonic() + timeout
    last_payload: ChatEventPageResponse | None = None
    while time.monotonic() < deadline:
        payload = _list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        last_payload = payload
        contents = _message_contents(payload)
        if all(item in contents for item in expected):
            return payload
        time.sleep(0.5)
    raise TimeoutError(f"REST contents were not observed: {expected}, {last_payload!r}")


def _wait_for_completed_rest_contents(
    *,
    server_url: str,
    token: str,
    session_id: str,
    expected: list[str],
    minimum_completed_runs: int = 1,
    timeout: float = 90,
) -> ChatEventPageResponse:
    """Wait for expected content and the required completed run boundaries."""
    deadline = time.monotonic() + timeout
    last_payload: ChatEventPageResponse | None = None
    while time.monotonic() < deadline:
        payload = _list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        last_payload = payload
        events = _history_events(payload)
        contents = _message_contents(payload)
        completed_run_count = sum(
            event.kind == "run_marker"
            and RunMarkerObservation.model_validate(event.payload).status == "completed"
            for event in events
        )
        if (
            all(item in contents for item in expected)
            and any(event.kind == "turn_marker" for event in events)
            and completed_run_count >= minimum_completed_runs
        ):
            return payload
        time.sleep(0.5)
    raise TimeoutError(
        f"Completed REST contents were not observed: {expected}, {last_payload!r}"
    )


# Shared public-path helpers used by focused execution reliability E2E modules.
# These JSON egress adapters preserve the existing helpers used by scenarios
# outside this module. All decisions in this module use decoded observations.
auth_headers = _headers
connect_chat = _connect_chat
create_agent = _create_agent
json_object = _json_object
json_object_list_payload = _json_object_list_payload
json_object_payload = _json_object_payload
message_contents = _message_contents
message_roles = _message_roles
run_message = _run_message
setup_workspace = _setup_workspace
team_primary_session_id = _team_primary_session_id


def list_history(*, server_url: str, token: str, session_id: str) -> dict[str, object]:
    """Serialize decoded history at the legacy scenario helper boundary."""
    return _list_history(
        server_url=server_url, token=token, session_id=session_id
    ).model_dump(mode="json", exclude_unset=True)


def list_live(*, server_url: str, token: str, session_id: str) -> dict[str, object]:
    """Serialize decoded live state at the legacy scenario helper boundary."""
    live = _list_live(server_url=server_url, token=token, session_id=session_id)
    return _JSON_OBJECT.dump_python(live.to_dict(), mode="json")


def history_events(payload: dict[str, object]) -> list[dict[str, object]]:
    """Serialize event observations for existing adjacent scenario consumers."""
    return [
        event.model_dump(mode="json", exclude_unset=True)
        for event in _history_events(payload)
    ]


def system_error_events(payload: dict[str, object]) -> list[dict[str, object]]:
    """Serialize selected error observations at the legacy helper boundary."""
    return [
        event.model_dump(mode="json", exclude_unset=True)
        for event in _system_error_events(payload)
    ]


def failed_run_error_events(payload: dict[str, object]) -> list[dict[str, object]]:
    """Serialize selected failure observations at the legacy helper boundary."""
    return [
        event.model_dump(mode="json", exclude_unset=True)
        for event in _failed_run_error_events(payload)
    ]


def wait_for_failed_run_error(
    *,
    server_url: str,
    token: str,
    session_id: str,
    expected_attempts: int,
    timeout: float = 30,
) -> dict[str, object]:
    """Preserve the JSON result of the shared terminal-error polling helper."""
    return _wait_for_failed_run_error(
        server_url=server_url,
        token=token,
        session_id=session_id,
        expected_attempts=expected_attempts,
        timeout=timeout,
    ).model_dump(mode="json", exclude_unset=True)


def wait_for_rest_contents(
    *,
    server_url: str,
    token: str,
    session_id: str,
    expected: list[str],
    timeout: float = 90,
) -> dict[str, object]:
    """Preserve the JSON result of the shared durable-content polling helper."""
    return _wait_for_rest_contents(
        server_url=server_url,
        token=token,
        session_id=session_id,
        expected=expected,
        timeout=timeout,
    ).model_dump(mode="json", exclude_unset=True)


def wait_for_ws_action(
    ws: Connection,
    *,
    action_type: str,
    mailbox_item_id: str | None = None,
    timeout: float = 10,
) -> dict[str, object]:
    """Serialize a canonical action for existing adjacent scenario consumers."""
    return _wait_for_ws_action(
        ws,
        action_type=action_type,
        mailbox_item_id=mailbox_item_id,
        timeout=timeout,
    ).model_dump(mode="json", exclude_unset=True)


@pytest.fixture(scope="class")
def execution_agent_setup(
    azents_public_server_url: str,
    azents_admin_server_url: str,
    system_bootstrap_evidence: SystemBootstrapEvidence,
    azents_engine_worker_container: object,
) -> _ExecutionAgentSetup:
    """Prepare one Agent/runtime shared by isolated persistence Sessions."""
    del azents_engine_worker_container
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
    return _ExecutionAgentSetup(
        workspace=workspace,
        agent_id=_create_agent(public_api_client, workspace),
    )


class TestAgentExecutionPersistence:
    """agent execution resultt REST reload t durable t t verifyt."""

    def test_single_turn_assistant_response_survives_rest_reload(
        self,
        public_api_client: azentspublicclient.ApiClient,
        azents_public_server_url: str,
        execution_agent_setup: _ExecutionAgentSetup,
    ) -> None:
        """t t user/assistant/run boundary t REST history t t."""
        workspace = execution_agent_setup.workspace
        agent_id = execution_agent_setup.agent_id

        result = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_HELLO,
        )
        payload = _wait_for_completed_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_HELLO, _HELLO_RESPONSE],
        )

        assert {"user", "assistant", "turn_complete", "run_complete"} <= set(
            _message_roles(payload)
        )
        assert _run_complete_ids(payload)
        turn_usages = _turn_usage_items(payload)
        assert turn_usages
        assert turn_usages[-1].total_tokens is not None
        assert turn_usages[-1].prompt_tokens is not None
        assert turn_usages[-1].completion_tokens is not None
        assert turn_usages[-1].raw is not None

    def test_canonical_ws_history_pagination_and_intent_converge(
        self,
        public_api_client: azentspublicclient.ApiClient,
        azents_public_server_url: str,
        execution_agent_setup: _ExecutionAgentSetup,
    ) -> None:
        """Converge canonical WS delivery with paginated durable history."""
        workspace = execution_agent_setup.workspace
        agent_id = execution_agent_setup.agent_id
        session_id = _create_execution_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
        )

        with _connect_chat(
            public_api_client=public_api_client,
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
        ) as ws:
            subscribed = _wait_for_ws_action(ws, action_type="subscribed")
            assert subscribed.session_id == session_id
            ws.send(
                json.dumps(
                    {
                        "type": "subscription_health_check",
                        "request_id": "timeline-reliability",
                    }
                )
            )
            health_ack = _wait_for_ws_action(
                ws,
                action_type="subscription_health_check_ack",
            )
            assert health_ack.request_id == "timeline-reliability"

            _run_message(
                public_api_client=public_api_client,
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=session_id,
                message=_TIMELINE_FIRST,
            )
            first_ws_events = _wait_for_ws_turn(
                ws,
                session_id=session_id,
                user_message=_TIMELINE_FIRST,
                reasoning_summary=_TIMELINE_FIRST_REASONING,
                assistant_message=_TIMELINE_FIRST_RESPONSE,
            )

            _run_message(
                public_api_client=public_api_client,
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=session_id,
                message=_TIMELINE_SECOND,
            )
            second_ws_events = _wait_for_ws_turn(
                ws,
                session_id=session_id,
                user_message=_TIMELINE_SECOND,
                reasoning_summary=_TIMELINE_SECOND_REASONING,
                assistant_message=_TIMELINE_SECOND_RESPONSE,
            )

        expected_profile = {
            "model_target_label": "default",
            "reasoning_effort": None,
            "enabled_execution_options": [],
        }
        ws_events = [*first_ws_events, *second_ws_events]
        ws_event_ids = [event.id for event in ws_events]
        assert len(ws_event_ids) == len(set(ws_event_ids))
        ws_user_profiles: list[object] = []
        for event in ws_events:
            if event.kind != "user_message":
                continue
            payload = InputMessageObservation.model_validate(event.payload)
            if payload.content in [_TIMELINE_FIRST, _TIMELINE_SECOND]:
                assert payload.requested_inference_profile is not None
                ws_user_profiles.append(
                    payload.requested_inference_profile.model_dump(exclude_unset=True)
                )
        assert ws_user_profiles == [expected_profile, expected_profile]

        full_history = _wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            expected=[
                _TIMELINE_FIRST,
                _TIMELINE_FIRST_RESPONSE,
                _TIMELINE_SECOND,
                _TIMELINE_SECOND_RESPONSE,
            ],
        )
        full_events = _history_events(full_history)
        reasoning_summaries: list[object] = []
        rest_user_profiles: list[object] = []
        for event in full_events:
            if event.kind not in {"reasoning", "user_message"}:
                continue
            payload = InputMessageObservation.model_validate(event.payload)
            if event.kind == "reasoning":
                reasoning_summaries.append(payload.summary)
            if event.kind == "user_message" and payload.content in [
                _TIMELINE_FIRST,
                _TIMELINE_SECOND,
            ]:
                assert payload.requested_inference_profile is not None
                rest_user_profiles.append(
                    payload.requested_inference_profile.model_dump(exclude_unset=True)
                )
        assert reasoning_summaries.count(_TIMELINE_FIRST_REASONING) == 1
        assert reasoning_summaries.count(_TIMELINE_SECOND_REASONING) == 1
        assert rest_user_profiles == [expected_profile, expected_profile]

        full_ids = [event.id for event in full_events]
        latest_page = _history_page(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            limit=2,
            before=None,
            after=None,
        )
        latest_items = _history_events(latest_page)
        assert len(latest_items) == 2
        assert latest_page.has_more is True
        assert latest_page.has_newer is False
        assert latest_page.next_cursor == latest_items[0].id
        assert latest_page.previous_cursor == latest_items[-1].id

        collected_ids: set[str] = set()
        page = latest_page
        oldest_page = latest_page
        while True:
            page_items = _history_events(page)
            page_ids = {item.id for item in page_items}
            assert page_ids
            assert collected_ids.isdisjoint(page_ids)
            collected_ids.update(page_ids)
            oldest_page = page
            if page.has_more is False:
                break
            cursor = page.next_cursor
            if cursor is None:
                raise AssertionError(f"History page did not include cursor: {page!r}")
            page = _history_page(
                server_url=azents_public_server_url,
                token=workspace.token,
                session_id=session_id,
                limit=2,
                before=cursor,
                after=None,
            )
            assert page.has_newer is True

        assert collected_ids == set(full_ids)
        forward_cursor = oldest_page.previous_cursor
        if forward_cursor is None:
            raise AssertionError(
                f"Oldest history page did not include cursor: {oldest_page!r}"
            )
        forward_page = _history_page(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            limit=2,
            before=None,
            after=forward_cursor,
        )
        assert _history_events(forward_page)
        assert forward_page.has_more is True
        assert forward_page.has_newer is True

    def test_ws_mailbox_upsert_and_remove_use_native_identity(
        self,
        public_api_client: azentspublicclient.ApiClient,
        azents_public_server_url: str,
        execution_agent_setup: _ExecutionAgentSetup,
    ) -> None:
        """Observe typed mailbox admission and removal around one promoted turn."""
        workspace = execution_agent_setup.workspace
        agent_id = execution_agent_setup.agent_id
        session_id = _create_execution_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
        )
        message = f"Native mailbox WebSocket identity {unique()}"

        with _connect_chat(
            public_api_client=public_api_client,
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
        ) as ws:
            subscribed = _wait_for_ws_action(ws, action_type="subscribed")
            assert subscribed.session_id == session_id

            response = requests.post(
                f"{azents_public_server_url}/chat/v1/sessions/{session_id}/inputs",
                headers={
                    **_headers(workspace.token),
                    "Content-Type": "application/json",
                },
                json={
                    "agent_id": agent_id,
                    "client_request_id": f"native-mailbox-{unique()}",
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
            write_payload = decode_chat_write(response.json())
            snapshot = write_payload.snapshot
            assert snapshot is not None

            upsert_action = _wait_for_ws_action(
                ws,
                action_type="mailbox_item_upserted",
                timeout=30,
            )
            mailbox_item = upsert_action.mailbox_item
            assert mailbox_item is not None
            assert upsert_action.session_id == session_id
            assert mailbox_item.session_id == session_id
            assert mailbox_item.kind == "user_message"
            items = mailbox_item.items
            assert len(items) == 1
            item = items[0]
            mailbox_item_id = mailbox_item.mailbox_item_id
            item_id = item.id
            item_key = item.item_key
            assert item_id == f"{mailbox_item_id}:{item_key}"
            presentation = item.presentation
            assert presentation.type == "user_message"
            assert presentation.content == message

            removal_action = _wait_for_ws_action(
                ws,
                action_type="mailbox_item_removed",
                mailbox_item_id=mailbox_item_id,
                timeout=120,
            )
            assert removal_action.model_dump(exclude_unset=True) == {
                "type": "mailbox_item_removed",
                "session_id": session_id,
                "mailbox_item_id": mailbox_item_id,
            }

        history = _wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
            expected=[message],
        )
        assert message in _message_contents(history)

    def test_failed_run_retry_live_state_recovers_before_terminal_error(
        self,
        public_api_client: azentspublicclient.ApiClient,
        azents_public_server_url: str,
        execution_agent_setup: _ExecutionAgentSetup,
    ) -> None:
        """Failed-run retry exposes live state before terminal recovery."""
        workspace = execution_agent_setup.workspace
        agent_id = execution_agent_setup.agent_id
        session_id = _create_execution_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
        )

        result = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=session_id,
            message=_RETRY_ONCE,
        )
        live_payload = _wait_for_live_retry(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            failed_attempt_count=1,
        )
        run = live_payload.run
        assert run is not None and run.retry is not None
        retry = run.retry
        attempts = retry.attempts
        assert retry.status == "waiting"
        assert retry.failed_attempt_count == 1
        assert retry.max_retries == 3
        latest_error = attempts[-1].user_message
        assert latest_error == _SANITIZED_PROVIDER_RETRY_MESSAGE
        assert "dummy-provider-secret-value" not in str(latest_error)
        assert "dummy-provider-token-value" not in str(latest_error)

        during_retry = _list_history(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
        )
        assert _failed_run_error_events(during_retry) == []

        final_payload = _wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_RETRY_ONCE, _RETRY_ONCE_RESPONSE],
        )
        assert _failed_run_error_events(final_payload) == []

    def test_failed_run_retry_budget_resets_after_model_turn(
        self,
        public_api_client: azentspublicclient.ApiClient,
        azents_public_server_url: str,
        execution_agent_setup: _ExecutionAgentSetup,
    ) -> None:
        """Each model turn receives a fresh failed-run retry budget."""
        workspace = execution_agent_setup.workspace
        agent_id = execution_agent_setup.agent_id
        session_id = _create_execution_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
        )

        result = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=session_id,
            message=_RETRY_ACROSS_TURNS,
        )
        failed_payload = _wait_for_failed_run_error(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected_attempts=4,
        )
        failed_event = _failed_run_error_events(failed_payload)[-1]
        failure = _failed_run(failed_event)
        attempts = failure.attempts
        assert attempts is not None

        attempt_messages = [attempt.user_message for attempt in attempts]
        assert failure.error_kind == "model_provider"
        assert failure.retryability == "unknown"
        assert failure.failure_code is None
        assert failure.failed_attempt_count == 4
        assert failure.max_retries == 3
        assert [attempt.attempt_number for attempt in attempts] == [1, 2, 3, 4]
        assert all(attempt.retryability == "unknown" for attempt in attempts)
        assert all(attempt.failure_code is None for attempt in attempts)
        assert attempt_messages == [
            f"Model provider error: Deterministic model turn 2 attempt {number} failed."
            for number in range(1, 5)
        ]
        assert _RETRY_ACROSS_TURNS_CALL_ID in _tool_result_call_ids(failed_payload)

    def test_failed_run_manual_retry_soft_reverts_terminal_error(
        self,
        public_api_client: azentspublicclient.ApiClient,
        azents_public_server_url: str,
        execution_agent_setup: _ExecutionAgentSetup,
    ) -> None:
        """Manual failed-run retry soft-reverts terminal error and restarts."""
        workspace = execution_agent_setup.workspace
        agent_id = execution_agent_setup.agent_id
        session_id = _create_execution_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
        )

        result = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=session_id,
            message=_RETRY_MANUAL,
        )
        failed_payload = _wait_for_failed_run_error(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected_attempts=4,
        )
        failed_event = _failed_run_error_events(failed_payload)[-1]
        failed_event_id = failed_event.id

        retry_response = _retry_failed_run(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=result.session_id,
            failed_event_id=failed_event_id,
        )
        assert retry_response.accepted.type == "failed_run_retry"
        assert retry_response.history_reload_required is True

        final_payload = _wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_RETRY_MANUAL, _RETRY_MANUAL_RESPONSE],
        )
        assert _failed_run_error_events(final_payload) == []

    def test_failed_run_manual_retry_rejects_stale_failed_card(
        self,
        public_api_client: azentspublicclient.ApiClient,
        azents_public_server_url: str,
        execution_agent_setup: _ExecutionAgentSetup,
    ) -> None:
        """Manual failed-run retry rejects stale failed cards."""
        workspace = execution_agent_setup.workspace
        agent_id = execution_agent_setup.agent_id
        session_id = _create_execution_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
        )

        result = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=session_id,
            message=_RETRY_STALE,
        )
        failed_payload = _wait_for_failed_run_error(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected_attempts=4,
        )
        failed_event = _failed_run_error_events(failed_payload)[-1]
        failed_event_id = failed_event.id

        _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_HELLO,
            session_id=result.session_id,
        )
        _wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_HELLO, _HELLO_RESPONSE],
        )

        response = requests.post(
            f"{azents_public_server_url}/chat/v1/sessions/{result.session_id}/retry-failed-run",
            headers={**_headers(workspace.token), "Content-Type": "application/json"},
            json={
                "agent_id": agent_id,
                "failed_event_id": failed_event_id,
                "client_request_id": f"agent-execution-stale-retry-{unique()}",
            },
            timeout=10,
        )
        assert response.status_code == 409

    def test_duplicate_mcp_namespaces_route_and_survive_lifecycle_changes(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: DockerContainer,
    ) -> None:
        """Route duplicate MCP tools through stable Agent namespaces."""
        docker_gateway = _docker_gateway(azents_engine_worker_container)
        with (
            _mock_mcp_instance(
                "shared",
                docker_gateway=docker_gateway,
                hold_first_instance=True,
            ) as shared_instance,
            _mock_mcp_instance(
                "owned",
                docker_gateway=docker_gateway,
                hold_first_instance=False,
            ) as owned_instance,
        ):
            shared_server_url = shared_instance.url
            owned_server_url = owned_instance.url
            shared_source_identity = {"server": shared_server_url.removesuffix("/mcp")}
            owned_source_identity = {"server": owned_server_url.removesuffix("/mcp")}
            workspace = _setup_workspace(
                public_api_client,
                admin_api_client,
                azents_public_server_url,
            )
            agent_id = _create_agent(
                public_api_client,
                workspace,
                tool_search_enabled=True,
            )
            headers = _headers(workspace.token)
            toolkit_api = ToolkitV1Api(public_api_client)
            shared = toolkit_api.toolkit_v1_create_toolkit_config(
                handle=workspace.handle,
                toolkit_config_create_request=ToolkitConfigCreateRequest(
                    toolkit_type="mcp",
                    slug=_DUPLICATE_MCP_BASE_SLUG,
                    name="Shared duplicate MCP",
                    config={
                        "server_url": shared_server_url,
                        "auth_type": "none",
                        "timeout": 30.0,
                    },
                    enabled=True,
                ),
                _headers=headers,
            )
            attachment = toolkit_api.toolkit_v1_attach_toolkit_to_agent(
                handle=workspace.handle,
                agent_id=agent_id,
                agent_toolkit_attach_request=AgentToolkitAttachRequest(
                    toolkit_id=shared.id,
                ),
                _headers=headers,
            )
            owned = toolkit_api.toolkit_v1_create_agent_toolkit_config(
                handle=workspace.handle,
                agent_id=agent_id,
                agent_toolkit_config_create_request=AgentToolkitConfigCreateRequest(
                    toolkit_type="mcp",
                    slug=_DUPLICATE_MCP_BASE_SLUG,
                    name="Owned duplicate MCP",
                    config={
                        "server_url": owned_server_url,
                        "auth_type": "none",
                        "timeout": 30.0,
                    },
                    enabled=True,
                ),
                _headers=headers,
            )
            hook = toolkit_api.toolkit_v1_create_toolkit_config(
                handle=workspace.handle,
                toolkit_config_create_request=ToolkitConfigCreateRequest(
                    toolkit_type="runtime_hook_qa",
                    slug="source_hook",
                    name="Duplicate MCP source hook",
                    config={"mode": "observe"},
                    enabled=True,
                ),
                _headers=headers,
            )
            toolkit_api.toolkit_v1_attach_toolkit_to_agent(
                handle=workspace.handle,
                agent_id=agent_id,
                agent_toolkit_attach_request=AgentToolkitAttachRequest(
                    toolkit_id=hook.id,
                ),
                _headers=headers,
            )

            first = _run_message(
                public_api_client=public_api_client,
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                message="Invoke duplicate MCP routes initial",
            )
            try:
                shared_instance.wait_until_reached()
                _wait_for_live_toolkit_source(
                    server_url=azents_public_server_url,
                    token=workspace.token,
                    session_id=first.session_id,
                    call_id="call_duplicate_mcp_initial_shared",
                    toolkit_config_id=shared.id,
                    toolkit_name="Shared duplicate MCP",
                    toolkit_slug="dupmcp",
                    toolkit_namespace="dupmcp",
                    source_identity=shared_source_identity,
                )
            finally:
                shared_instance.release()
            initial = _wait_for_completed_rest_contents(
                server_url=azents_public_server_url,
                token=workspace.token,
                session_id=first.session_id,
                expected=["Duplicate MCP initial routes completed."],
            )
            initial_search = str(
                _tool_result_content(initial, "call_duplicate_mcp_initial_search")
            )
            assert '"name": "dupmcp__instance"' in initial_search
            assert '"name": "dupmcp_2__instance"' in initial_search
            assert "shared" in str(
                _tool_result_content(initial, "call_duplicate_mcp_initial_shared")
            )
            assert "owned" in str(
                _tool_result_content(initial, "call_duplicate_mcp_initial_owned")
            )
            _assert_toolkit_call_source(
                initial,
                "call_duplicate_mcp_initial_shared",
                toolkit_config_id=shared.id,
                toolkit_name="Shared duplicate MCP",
                toolkit_slug="dupmcp",
                toolkit_namespace="dupmcp",
                source_identity=shared_source_identity,
            )
            _assert_toolkit_call_source(
                initial,
                "call_duplicate_mcp_initial_owned",
                toolkit_config_id=owned.id,
                toolkit_name="Owned duplicate MCP",
                toolkit_slug="dupmcp",
                toolkit_namespace="dupmcp_2",
                source_identity=owned_source_identity,
            )
            _wait_for_runtime_hook_source(
                azents_engine_worker_container,
                tool_name="dupmcp__instance",
                toolkit_namespace="dupmcp",
            )
            _wait_for_runtime_hook_source(
                azents_engine_worker_container,
                tool_name="dupmcp_2__instance",
                toolkit_namespace="dupmcp_2",
            )

            toolkit_api.toolkit_v1_update_agent_toolkit_config(
                handle=workspace.handle,
                agent_id=agent_id,
                toolkit_config_id=owned.id,
                agent_toolkit_config_update_request=AgentToolkitConfigUpdateRequest(
                    enabled=False
                ),
                _headers=headers,
            )
            toolkit_api.toolkit_v1_update_agent_toolkit_config(
                handle=workspace.handle,
                agent_id=agent_id,
                toolkit_config_id=owned.id,
                agent_toolkit_config_update_request=AgentToolkitConfigUpdateRequest(
                    enabled=True
                ),
                _headers=headers,
            )
            toolkit_api.toolkit_v1_detach_toolkit_from_agent(
                handle=workspace.handle,
                agent_id=agent_id,
                agent_toolkit_id=attachment.id,
                _headers=headers,
            )
            toolkit_api.toolkit_v1_attach_toolkit_to_agent(
                handle=workspace.handle,
                agent_id=agent_id,
                agent_toolkit_attach_request=AgentToolkitAttachRequest(
                    toolkit_id=shared.id,
                ),
                _headers=headers,
            )
            reused_session_id = _create_execution_session(
                server_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
            )
            reused_run = _run_message(
                public_api_client=public_api_client,
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=reused_session_id,
                message="Invoke duplicate MCP routes after lifecycle reuse",
            )
            reused = _wait_for_completed_rest_contents(
                server_url=azents_public_server_url,
                token=workspace.token,
                session_id=reused_run.session_id,
                expected=["Duplicate MCP lifecycle routes completed."],
            )
            assert "shared" in str(
                _tool_result_content(reused, "call_duplicate_mcp_reuse_shared")
            )
            assert "owned" in str(
                _tool_result_content(reused, "call_duplicate_mcp_reuse_owned")
            )
            _assert_toolkit_call_source(
                reused,
                "call_duplicate_mcp_reuse_shared",
                toolkit_config_id=shared.id,
                toolkit_name="Shared duplicate MCP",
                toolkit_slug="dupmcp",
                toolkit_namespace="dupmcp",
                source_identity=shared_source_identity,
            )
            _assert_toolkit_call_source(
                reused,
                "call_duplicate_mcp_reuse_owned",
                toolkit_config_id=owned.id,
                toolkit_name="Owned duplicate MCP",
                toolkit_slug="dupmcp",
                toolkit_namespace="dupmcp_2",
                source_identity=owned_source_identity,
            )

            toolkit_api.toolkit_v1_update_toolkit_config(
                handle=workspace.handle,
                toolkit_config_id=shared.id,
                toolkit_config_update_request=ToolkitConfigUpdateRequest(
                    slug="dupmcp_new"
                ),
                _headers=headers,
            )
            renamed_session_id = _create_execution_session(
                server_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
            )
            renamed_run = _run_message(
                public_api_client=public_api_client,
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=renamed_session_id,
                message="Invoke duplicate MCP routes after slug change",
            )
            renamed = _wait_for_completed_rest_contents(
                server_url=azents_public_server_url,
                token=workspace.token,
                session_id=renamed_run.session_id,
                expected=["Duplicate MCP renamed routes completed."],
            )
            assert "shared" in str(
                _tool_result_content(renamed, "call_duplicate_mcp_renamed_shared")
            )
            assert "owned" in str(
                _tool_result_content(renamed, "call_duplicate_mcp_renamed_owned")
            )
            _assert_toolkit_call_source(
                renamed,
                "call_duplicate_mcp_renamed_shared",
                toolkit_config_id=shared.id,
                toolkit_name="Shared duplicate MCP",
                toolkit_slug="dupmcp_new",
                toolkit_namespace="dupmcp_new",
                source_identity=shared_source_identity,
            )
            _assert_toolkit_call_source(
                renamed,
                "call_duplicate_mcp_renamed_owned",
                toolkit_config_id=owned.id,
                toolkit_name="Owned duplicate MCP",
                toolkit_slug="dupmcp",
                toolkit_namespace="dupmcp_2",
                source_identity=owned_source_identity,
            )

            toolkit_api.toolkit_v1_delete_toolkit_config(
                handle=workspace.handle,
                toolkit_config_id=shared.id,
                _headers=headers,
            )
            replacement = toolkit_api.toolkit_v1_create_toolkit_config(
                handle=workspace.handle,
                toolkit_config_create_request=ToolkitConfigCreateRequest(
                    toolkit_type="mcp",
                    slug="dupmcp_new",
                    name="Replacement duplicate MCP",
                    config={
                        "server_url": shared_server_url,
                        "auth_type": "none",
                        "timeout": 30.0,
                    },
                    enabled=True,
                ),
                _headers=headers,
            )
            toolkit_api.toolkit_v1_attach_toolkit_to_agent(
                handle=workspace.handle,
                agent_id=agent_id,
                agent_toolkit_attach_request=AgentToolkitAttachRequest(
                    toolkit_id=replacement.id,
                ),
                _headers=headers,
            )
            replacement_session_id = _create_execution_session(
                server_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
            )
            replacement_run = _run_message(
                public_api_client=public_api_client,
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=replacement_session_id,
                message="Invoke duplicate MCP routes after replacement",
            )
            replaced = _wait_for_completed_rest_contents(
                server_url=azents_public_server_url,
                token=workspace.token,
                session_id=replacement_run.session_id,
                expected=["Duplicate MCP replacement routes completed."],
            )
            assert "shared" in str(
                _tool_result_content(
                    replaced,
                    "call_duplicate_mcp_replacement_shared",
                )
            )
            assert "owned" in str(
                _tool_result_content(
                    replaced,
                    "call_duplicate_mcp_replacement_owned",
                )
            )
            _assert_toolkit_call_source(
                replaced,
                "call_duplicate_mcp_replacement_shared",
                toolkit_config_id=replacement.id,
                toolkit_name="Replacement duplicate MCP",
                toolkit_slug="dupmcp_new",
                toolkit_namespace="dupmcp_new_2",
                source_identity=shared_source_identity,
            )
            _assert_toolkit_call_source(
                replaced,
                "call_duplicate_mcp_replacement_owned",
                toolkit_config_id=owned.id,
                toolkit_name="Owned duplicate MCP",
                toolkit_slug="dupmcp",
                toolkit_namespace="dupmcp_2",
                source_identity=owned_source_identity,
            )

    def test_tool_call_result_and_followup_response_survive_rest_reload(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """tool call/result t t assistant responset REST history t t."""
        del azents_engine_worker_container
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(public_api_client, workspace, with_toolkit=True)

        result = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_TOOL_PROMPT,
        )
        payload = _wait_for_completed_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_TOOL_PROMPT, _TOOL_RESPONSE],
        )

        assert {"assistant", "tool"} <= set(_message_roles(payload))
        assert _TOOL_NAME in _tool_call_names(payload)
        assert _TOOL_CALL_ID in _tool_result_call_ids(payload)
        assert _run_complete_ids(payload)

    def test_manual_compaction_preserves_history_and_next_turn_persists(
        self,
        public_api_client: azentspublicclient.ApiClient,
        azents_public_server_url: str,
        execution_agent_setup: _ExecutionAgentSetup,
    ) -> None:
        """manual compact t UI history t next turn persistence t t."""
        workspace = execution_agent_setup.workspace
        agent_id = execution_agent_setup.agent_id
        session_id = _create_execution_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
        )

        first = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=session_id,
            message=_COMPACT_SEED,
        )
        _wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=first.session_id,
            expected=[_COMPACT_SEED, _COMPACT_SEED_RESPONSE],
        )
        _wait_for_session_idle(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=first.session_id,
            timeout=120,
        )
        _run_command(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=first.session_id,
            command="compact",
        )

        after_compact = _list_history(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=first.session_id,
        )
        assert {"compaction_marker", "compaction_summary"} <= set(
            _message_roles(after_compact)
        )
        assert _COMPACT_SEED in _message_contents(after_compact)
        assert _COMPACT_SEED_RESPONSE in _message_contents(after_compact)

        _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_AFTER_COMPACT,
            session_id=first.session_id,
        )
        final_payload = _wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=first.session_id,
            expected=[
                _COMPACT_SEED,
                _COMPACT_SEED_RESPONSE,
                _AFTER_COMPACT,
                _AFTER_COMPACT_RESPONSE,
            ],
        )
        assert _message_contents(final_payload).count(_AFTER_COMPACT_RESPONSE) == 1

    def test_edit_user_message_replaces_later_turn_in_rest_history(
        self,
        public_api_client: azentspublicclient.ApiClient,
        azents_public_server_url: str,
        execution_agent_setup: _ExecutionAgentSetup,
    ) -> None:
        """user message edit t t turn t t t run t durable t t."""
        workspace = execution_agent_setup.workspace
        agent_id = execution_agent_setup.agent_id
        session_id = _create_execution_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
        )

        first = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=session_id,
            message=_HELLO,
        )
        _wait_for_completed_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=first.session_id,
            expected=[_HELLO, _HELLO_RESPONSE],
            minimum_completed_runs=1,
        )
        _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_SECOND,
            session_id=first.session_id,
        )
        before_edit = _wait_for_completed_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=first.session_id,
            expected=[_HELLO, _HELLO_RESPONSE, _SECOND, _SECOND_RESPONSE],
            minimum_completed_runs=2,
        )
        second_message_id = _message_id_for_content(before_edit, _SECOND)

        _wait_for_session_idle(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=first.session_id,
            timeout=120,
        )
        _edit_user_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=first.session_id,
            message_id=second_message_id,
            message=_AFTER_COMPACT,
        )

        after_edit = _wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=first.session_id,
            expected=[_HELLO, _HELLO_RESPONSE, _AFTER_COMPACT, _AFTER_COMPACT_RESPONSE],
        )
        contents = _message_contents(after_edit)
        assert _HELLO in contents
        assert _HELLO_RESPONSE in contents
        assert _SECOND not in contents
        assert _SECOND_RESPONSE not in contents
        assert _AFTER_COMPACT in contents
        assert _AFTER_COMPACT_RESPONSE in contents
