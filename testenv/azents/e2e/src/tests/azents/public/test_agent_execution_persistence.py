"""Agent execution durable persistence E2E test."""

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

from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
)

_HELLO = "Event durable hello"
_HELLO_RESPONSE = "Event durable hello response."
_SECOND = "Event durable second turn"
_SECOND_RESPONSE = "Event durable second response."
_COMPACT_SEED = "Event durable compact seed"
_COMPACT_SEED_RESPONSE = "Event durable compact seed response."
_AFTER_COMPACT = "Event durable after compact"
_AFTER_COMPACT_RESPONSE = "Event durable after compact response."
_TOOL_PROMPT = "Start chat input buffer long tool"
_TOOL_RESPONSE = "Chat input buffer long tool completed."
_TOOL_NAME = "bufferqa__runtime_hook_qa_probe"
_TOOL_CALL_ID = "call_chat_input_buffer_delay"
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
        path = "/chat/v1/sessions/new/messages"
    else:
        path = f"/chat/v1/sessions/{session_id}/messages"
    response = requests.post(
        f"{public_url}{path}",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"agent-execution-message-{unique()}",
            "message": message,
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
        f"{public_url}/chat/v1/sessions/{session_id}/commands",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"agent-execution-command-{unique()}",
            "command": command,
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
