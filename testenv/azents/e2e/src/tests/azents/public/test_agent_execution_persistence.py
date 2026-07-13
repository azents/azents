"""Agent execution durable persistence E2E test."""

import json
import time
from dataclasses import dataclass

import azentsadminclient
import azentspublicclient
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
from websockets.sync.client import connect as ws_connect
from websockets.sync.connection import Connection

from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
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
        "history_event_appended",
        "input_actions_updated",
        "live_event_removed",
        "live_event_upserted",
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
_RETRY_ONCE = "Failed run retry once then succeed"
_RETRY_ONCE_RESPONSE = "Failed run retry recovered after one attempt."
_RETRY_MANUAL = "Failed run retry exhaust then manual recover"
_RETRY_MANUAL_RESPONSE = "Manual failed-run retry recovered successfully."
_RETRY_STALE = "Failed run retry stale conflict"
_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


@dataclass(frozen=True)
class _Workspace:
    """Agent execution E2E resource t."""

    token: str
    handle: str
    model_selection: AgentModelSelectionInput


@dataclass(frozen=True)
class _RunResult:
    """REST write run result."""

    session_id: str


def _headers(token: str) -> dict[str, str]:
    """Bearer auth header t t."""
    return {"Authorization": f"Bearer {token}"}


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
    payload = _json_object(response)
    session_id = payload.get("id")
    if not isinstance(session_id, str):
        raise AssertionError(f"Team primary response did not include id: {payload!r}")
    return session_id


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


def _receive_ws_action(ws: Connection, *, timeout: float) -> dict[str, object]:
    """Receive and validate one canonical public Chat WebSocket action."""
    raw = ws.recv(timeout=timeout)
    action = _json_object_payload(json.loads(raw), label="Chat WebSocket action")
    action_type = action.get("type")
    assert isinstance(action_type, str), action
    assert action_type in _CANONICAL_WS_ACTION_TYPES, action
    assert "kind" not in action, action
    return action


def _wait_for_ws_action(
    ws: Connection,
    *,
    action_type: str,
    timeout: float = 10,
) -> dict[str, object]:
    """Wait for a canonical WebSocket action of the requested type."""
    deadline = time.monotonic() + timeout
    observed: list[object] = []
    while time.monotonic() < deadline:
        try:
            action = _receive_ws_action(ws, timeout=1)
        except TimeoutError:
            continue
        observed.append(action.get("type"))
        if action.get("type") == action_type:
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
) -> list[dict[str, object]]:
    """Collect canonical durable append actions through one completed turn."""
    deadline = time.monotonic() + timeout
    events: list[dict[str, object]] = []
    event_ids: set[str] = set()
    while time.monotonic() < deadline:
        try:
            action = _receive_ws_action(ws, timeout=5)
        except TimeoutError:
            continue
        if "session_id" in action:
            assert action.get("session_id") == session_id, action
        else:
            assert action.get("type") in {
                "subagent_tree_changed",
                "todo_state_changed",
            }, action
        if action.get("type") != "history_event_appended":
            continue
        event = _json_object_payload(
            action.get("event"),
            label="history_event_appended event",
        )
        assert event.get("session_id") == session_id, event
        event_id = event.get("id")
        if not isinstance(event_id, str):
            raise AssertionError(f"History event did not include id: {event!r}")
        assert event_id not in event_ids, event
        event_ids.add(event_id)
        events.append(event)

        kinds = [item.get("kind") for item in events]
        contents: list[str] = []
        reasoning: list[str] = []
        for item in events:
            payload = _json_object_payload(
                item.get("payload"),
                label="history event payload",
            )
            content = payload.get("content")
            if isinstance(content, str):
                contents.append(content)
            summary = payload.get("summary")
            if isinstance(summary, str):
                reasoning.append(summary)
        terminal = (
            event.get("kind") == "run_marker"
            and _json_object_payload(
                event.get("payload"),
                label="run marker payload",
            ).get("status")
            == "completed"
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
        "Completed canonical WebSocket turn was not observed: "
        f"{user_message!r}, {events!r}"
    )


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
    with_toolkit: bool = False,
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
            model_selection=workspace.model_selection,
            lightweight_model_selection=workspace.model_selection,
            type=AgentType.PUBLIC,
            shell_enabled=True,
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
        session_payload = _json_object(session_response)
        session_id_value = session_payload.get("id")
        if not isinstance(session_id_value, str):
            raise AssertionError(
                f"Team primary response did not include id: {session_payload!r}"
            )
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
            },
        },
        timeout=10,
    )
    response.raise_for_status()
    payload = _json_object(response)
    observed_session_id = payload.get("session_id")
    if not isinstance(observed_session_id, str):
        raise AssertionError(
            f"REST write response did not include session_id: {payload!r}"
        )
    return _RunResult(session_id=observed_session_id)


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
) -> dict[str, object]:
    """REST history event page t fetcht."""
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return _json_object(response)


def _history_page(
    *,
    server_url: str,
    token: str,
    session_id: str,
    limit: int,
    before: str | None,
    after: str | None,
) -> dict[str, object]:
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
    return _json_object(response)


def _list_live(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> dict[str, object]:
    """Fetch the REST live projection."""
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/live",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return _json_object(response)


def _history_events(payload: dict[str, object]) -> list[dict[str, object]]:
    """Validate and return raw REST history events."""
    return _json_object_list_payload(payload.get("items"), label="REST history events")


def _system_error_events(payload: dict[str, object]) -> list[dict[str, object]]:
    """Return raw REST history system_error events."""
    return [
        event
        for event in _history_events(payload)
        if event.get("kind") == "system_error"
    ]


def _failed_run_error_events(payload: dict[str, object]) -> list[dict[str, object]]:
    """Return raw REST history failed-run system_error events."""
    failed_events: list[dict[str, object]] = []
    for event in _system_error_events(payload):
        event_payload = _json_object_payload(
            event.get("payload"),
            label="system_error payload",
        )
        failure_payload = event_payload.get("failure")
        if failure_payload is None:
            continue
        failure = _json_object_payload(
            failure_payload,
            label="system_error failure",
        )
        if failure.get("kind") == "failed_run":
            failed_events.append(event)
    return failed_events


def _retry_failed_run(
    *,
    public_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    failed_event_id: str,
) -> dict[str, object]:
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
    return _json_object(response)


def _wait_for_live_retry(
    *,
    server_url: str,
    token: str,
    session_id: str,
    failed_attempt_count: int,
    timeout: float = 20,
) -> dict[str, object]:
    """Wait until /live exposes a failed-run retry state."""
    deadline = time.monotonic() + timeout
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        payload = _list_live(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        last_payload = payload
        run_payload = payload.get("run")
        if run_payload is not None:
            run = _json_object_payload(run_payload, label="live run")
            retry_payload = run.get("retry")
            if retry_payload is not None:
                retry = _json_object_payload(retry_payload, label="live run retry")
                observed_attempt_count = retry.get("failed_attempt_count")
                if (
                    isinstance(observed_attempt_count, int)
                    and observed_attempt_count >= failed_attempt_count
                ):
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
) -> dict[str, object]:
    """Wait until terminal failed-run system_error appears in history."""
    deadline = time.monotonic() + timeout
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        payload = _list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        last_payload = payload
        failed_events = _failed_run_error_events(payload)
        if failed_events:
            event_payload = _json_object_payload(
                failed_events[-1].get("payload"),
                label="failed-run payload",
            )
            failure = _json_object_payload(
                event_payload.get("failure"),
                label="failed-run failure",
            )
            attempts = _json_object_list_payload(
                failure.get("attempts"),
                label="failed-run attempts",
            )
            if len(attempts) == expected_attempts:
                return payload
        time.sleep(0.5)
    raise TimeoutError(f"failed-run error was not observed: {last_payload!r}")


def _message_item_from_event(event: dict[str, object]) -> dict[str, object]:
    """History event t t assertion t t message-like dict t t."""
    payload = _json_object_payload(event.get("payload"), label="history event payload")
    kind = event.get("kind")
    item: dict[str, object] = {
        "id": event.get("id"),
        "external_id": event.get("external_id"),
        "role": kind,
    }
    match kind:
        case "user_message":
            item["role"] = "user"
            item["content"] = payload.get("content")
        case "assistant_message":
            item["role"] = "assistant"
            item["content"] = payload.get("content")
        case "client_tool_call":
            item["role"] = "assistant"
            item["tool_calls"] = [
                {
                    "id": payload.get("call_id"),
                    "name": payload.get("name"),
                    "arguments": payload.get("arguments"),
                }
            ]
        case "client_tool_result":
            item["role"] = "tool"
            item["tool_call_id"] = payload.get("call_id")
            item["content"] = payload.get("output")
        case "turn_marker":
            item["role"] = "turn_complete"
            item["usage"] = payload.get("usage")
        case "run_marker":
            item["role"] = "run_complete"
            item["status"] = payload.get("status")
        case "compaction_marker" | "compaction_summary":
            item["role"] = kind
        case _:
            item["role"] = kind
    return item


def _message_items(payload: dict[str, object]) -> list[dict[str, object]]:
    """REST history item listt verifyt returnt."""
    events = _json_object_list_payload(payload.get("items"), label="REST history items")
    return [_message_item_from_event(event) for event in events]


def _message_contents(payload: dict[str, object]) -> list[str]:
    """REST history content listt returnt."""
    contents: list[str] = []
    for item in _message_items(payload):
        content = item.get("content")
        if isinstance(content, str):
            contents.append(content)
    return contents


def _message_roles(payload: dict[str, object]) -> list[str]:
    """REST history role listt returnt."""
    roles: list[str] = []
    for item in _message_items(payload):
        role = item.get("role")
        if isinstance(role, str):
            roles.append(role)
    return roles


def _message_id_for_content(payload: dict[str, object], content: str) -> str:
    """REST history t content t t message id t returnt."""
    for item in _message_items(payload):
        if item.get("content") != content:
            continue
        message_id = item.get("id")
        if isinstance(message_id, str):
            return message_id
    raise AssertionError(f"message not found for content: {content!r}")


def _tool_call_names(payload: dict[str, object]) -> list[str]:
    """REST history tool call name listt returnt."""
    names: list[str] = []
    for item in _message_items(payload):
        if item.get("tool_calls") is None:
            continue
        raw_tool_calls: object = item["tool_calls"]
        for tool_call in _json_object_list_payload(
            raw_tool_calls,
            label="REST tool calls",
        ):
            name = tool_call.get("name")
            if isinstance(name, str):
                names.append(name)
    return names


def _tool_result_call_ids(payload: dict[str, object]) -> list[str]:
    """REST history tool result call_id listt returnt."""
    call_ids: list[str] = []
    for item in _message_items(payload):
        tool_call_id = item.get("tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            call_ids.append(tool_call_id)
    return call_ids


def _run_complete_ids(payload: dict[str, object]) -> list[str]:
    """REST history run_complete message id listt returnt."""
    ids: list[str] = []
    for item in _message_items(payload):
        if item.get("role") != "run_complete":
            continue
        message_id = item.get("id")
        if isinstance(message_id, str):
            ids.append(message_id)
    return ids


def _turn_usage_items(payload: dict[str, object]) -> list[dict[str, object]]:
    """REST history turn_complete usage listt returnt."""
    usages: list[dict[str, object]] = []
    for item in _message_items(payload):
        if item.get("role") != "turn_complete":
            continue
        usage = item.get("usage")
        if usage is not None:
            usages.append(_json_object_payload(usage, label="turn_complete usage"))
    return usages


def _wait_for_rest_contents(
    *,
    server_url: str,
    token: str,
    session_id: str,
    expected: list[str],
    timeout: float = 90,
) -> dict[str, object]:
    """REST history t expected content t t t t t."""
    deadline = time.monotonic() + timeout
    last_payload: dict[str, object] | None = None
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


class TestAgentExecutionPersistence:
    """agent execution resultt REST reload t durable t t verifyt."""

    def test_single_turn_assistant_response_survives_rest_reload(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """t t user/assistant/run boundary t REST history t t."""
        del azents_engine_worker_container
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(public_api_client, workspace)

        result = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_HELLO,
        )
        payload = _wait_for_rest_contents(
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
        assert isinstance(turn_usages[-1].get("total_tokens"), int)
        assert isinstance(turn_usages[-1].get("prompt_tokens"), int)
        assert isinstance(turn_usages[-1].get("completion_tokens"), int)
        assert isinstance(turn_usages[-1].get("raw"), dict)

    def test_canonical_ws_history_pagination_and_intent_converge(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Converge canonical WS delivery with paginated durable history."""
        del azents_engine_worker_container
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(public_api_client, workspace)
        session_id = _team_primary_session_id(
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
            assert subscribed.get("session_id") == session_id
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
            assert health_ack.get("request_id") == "timeline-reliability"

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
        }
        ws_events = [*first_ws_events, *second_ws_events]
        ws_event_ids: list[str] = []
        for event in ws_events:
            event_id = event.get("id")
            if not isinstance(event_id, str):
                raise AssertionError(f"WebSocket event did not include id: {event!r}")
            ws_event_ids.append(event_id)
        assert len(ws_event_ids) == len(set(ws_event_ids))
        ws_user_profiles: list[object] = []
        for event in ws_events:
            if event.get("kind") != "user_message":
                continue
            payload = _json_object_payload(
                event.get("payload"),
                label="WebSocket user message payload",
            )
            if payload.get("content") in {_TIMELINE_FIRST, _TIMELINE_SECOND}:
                ws_user_profiles.append(payload.get("requested_inference_profile"))
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
            payload = _json_object_payload(
                event.get("payload"),
                label="REST history event payload",
            )
            if event.get("kind") == "reasoning":
                reasoning_summaries.append(payload.get("summary"))
            if event.get("kind") == "user_message" and payload.get("content") in {
                _TIMELINE_FIRST,
                _TIMELINE_SECOND,
            }:
                rest_user_profiles.append(payload.get("requested_inference_profile"))
        assert reasoning_summaries.count(_TIMELINE_FIRST_REASONING) == 1
        assert reasoning_summaries.count(_TIMELINE_SECOND_REASONING) == 1
        assert rest_user_profiles == [expected_profile, expected_profile]

        full_ids: list[str] = []
        for event in full_events:
            event_id = event.get("id")
            if not isinstance(event_id, str):
                raise AssertionError(
                    f"REST history event did not include id: {event!r}"
                )
            full_ids.append(event_id)
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
        assert latest_page.get("has_more") is True
        assert latest_page.get("has_newer") is False
        assert latest_page.get("next_cursor") == latest_items[0].get("id")
        assert latest_page.get("previous_cursor") == latest_items[-1].get("id")

        collected_ids: set[str] = set()
        page = latest_page
        oldest_page = latest_page
        while True:
            page_items = _history_events(page)
            page_ids: set[str] = set()
            for item in page_items:
                event_id = item.get("id")
                if not isinstance(event_id, str):
                    raise AssertionError(
                        f"History page event did not include id: {item!r}"
                    )
                page_ids.add(event_id)
            assert page_ids
            assert collected_ids.isdisjoint(page_ids)
            collected_ids.update(page_ids)
            oldest_page = page
            if page.get("has_more") is False:
                break
            cursor = page.get("next_cursor")
            if not isinstance(cursor, str):
                raise AssertionError(f"History page did not include cursor: {page!r}")
            page = _history_page(
                server_url=azents_public_server_url,
                token=workspace.token,
                session_id=session_id,
                limit=2,
                before=cursor,
                after=None,
            )
            assert page.get("has_newer") is True

        assert collected_ids == set(full_ids)
        forward_cursor = oldest_page.get("previous_cursor")
        if not isinstance(forward_cursor, str):
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
        assert forward_page.get("has_more") is True
        assert forward_page.get("has_newer") is True

    def test_failed_run_retry_live_state_recovers_before_terminal_error(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Failed-run retry exposes live state before terminal recovery."""
        del azents_engine_worker_container
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(public_api_client, workspace)

        result = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_RETRY_ONCE,
        )
        live_payload = _wait_for_live_retry(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            failed_attempt_count=1,
        )
        run = _json_object_payload(live_payload.get("run"), label="live run")
        retry = _json_object_payload(run.get("retry"), label="live run retry")
        attempts = _json_object_list_payload(
            retry.get("attempts"),
            label="live retry attempts",
        )
        assert retry.get("status") == "waiting"
        assert retry.get("failed_attempt_count") == 1
        assert retry.get("max_retries") == 3
        latest_error = attempts[-1].get("user_message")
        assert isinstance(latest_error, str)
        assert "Deterministic retry attempt 1 failed." in latest_error

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

    def test_failed_run_manual_retry_soft_reverts_terminal_error(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Manual failed-run retry soft-reverts terminal error and restarts."""
        del azents_engine_worker_container
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(public_api_client, workspace)

        result = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_RETRY_MANUAL,
        )
        failed_payload = _wait_for_failed_run_error(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected_attempts=3,
        )
        failed_event = _failed_run_error_events(failed_payload)[-1]
        failed_event_id = failed_event.get("id")
        assert isinstance(failed_event_id, str)

        retry_response = _retry_failed_run(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=result.session_id,
            failed_event_id=failed_event_id,
        )
        accepted = _json_object_payload(
            retry_response.get("accepted"),
            label="retry accepted",
        )
        assert accepted.get("type") == "failed_run_retry"
        assert retry_response.get("history_reload_required") is True

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
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Manual failed-run retry rejects stale failed cards."""
        del azents_engine_worker_container
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(public_api_client, workspace)

        result = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_RETRY_STALE,
        )
        failed_payload = _wait_for_failed_run_error(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected_attempts=3,
        )
        failed_event = _failed_run_error_events(failed_payload)[-1]
        failed_event_id = failed_event.get("id")
        assert isinstance(failed_event_id, str)

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
            f"{azents_public_server_url}/chat/v1/sessions/"
            f"{result.session_id}/retry-failed-run",
            headers={**_headers(workspace.token), "Content-Type": "application/json"},
            json={
                "agent_id": agent_id,
                "failed_event_id": failed_event_id,
                "client_request_id": f"agent-execution-stale-retry-{unique()}",
            },
            timeout=10,
        )
        assert response.status_code == 409

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
        payload = _wait_for_rest_contents(
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
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """manual compact t UI history t next turn persistence t t."""
        del azents_engine_worker_container
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(public_api_client, workspace)

        first = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_COMPACT_SEED,
        )
        _wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=first.session_id,
            expected=[_COMPACT_SEED, _COMPACT_SEED_RESPONSE],
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
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """user message edit t t turn t t t run t durable t t."""
        del azents_engine_worker_container
        workspace = _setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = _create_agent(public_api_client, workspace)

        first = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_HELLO,
        )
        _wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=first.session_id,
            expected=[_HELLO, _HELLO_RESPONSE],
        )
        _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_SECOND,
            session_id=first.session_id,
        )
        before_edit = _wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=first.session_id,
            expected=[_HELLO, _HELLO_RESPONSE, _SECOND, _SECOND_RESPONSE],
        )
        second_message_id = _message_id_for_content(before_edit, _SECOND)

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
