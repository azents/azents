"""AGENTS.md read appendix E2E test."""

import time
from typing import Any, NamedTuple, cast

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
from testcontainers.core.container import DockerContainer

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
_MARKER = "ROOT_AGENTS_E2E_MARKER_3542"
_PREPARE_MESSAGE = "Prepare AGENTS appendix files"
_PREPARE_CALL_ID = "call_agents_md_appendix_prepare"
_READ_MESSAGE = "Read governed file"
_READ_CALL_ID = "call_agents_md_appendix_read"


class AgentsMdExerciseResult(NamedTuple):
    """AGENTS.md appendix exercise result."""

    requests_count: int
    system_marker_requests: list[int]
    tool_result_marker_requests: list[int]
    instruction_snippets: list[str]
    tool_result_snippets: list[str]
    request_summaries: list[str]
    agent_shell_enabled: bool | None


def _api_host(public_api_client: azentspublicclient.ApiClient) -> str:
    """Generated client t API host stringt t."""
    configuration = cast(Any, public_api_client).configuration
    return str(configuration.host)


def _system_message_texts(item: dict[str, object]) -> list[str]:
    """AIMock journal item t instruction/system stringt t."""
    body = item.get("body")
    if not isinstance(body, dict):
        return []
    body_dict = cast("dict[str, object]", body)
    texts: list[str] = []
    instructions = body_dict.get("instructions")
    if isinstance(instructions, str):
        texts.append(instructions)
    messages = body_dict.get("messages")
    if not isinstance(messages, list):
        return texts
    message_items = cast("list[object]", messages)
    for message in message_items:
        if not isinstance(message, dict):
            continue
        message_dict = cast("dict[str, object]", message)
        if message_dict.get("role") != "system":
            continue
        content = message_dict.get("content")
        if isinstance(content, str):
            texts.append(content)
    return texts


def _tool_result_texts(item: dict[str, object]) -> list[str]:
    """AIMock journal item t tool result strings."""
    body = item.get("body")
    if not isinstance(body, dict):
        return []
    body_dict = cast("dict[str, object]", body)
    messages = body_dict.get("messages")
    if not isinstance(messages, list):
        return []
    texts: list[str] = []
    for message in cast("list[object]", messages):
        if not isinstance(message, dict):
            continue
        message_dict = cast("dict[str, object]", message)
        if message_dict.get("role") != "tool":
            continue
        content = message_dict.get("content")
        if isinstance(content, str):
            texts.append(content)
    return texts


def _request_summary(item: dict[str, object]) -> str:
    """AIMock journal item t t request shape t assertion messaget summaryt."""
    body = item.get("body")
    if not isinstance(body, dict):
        return "body=<missing>"
    body_dict = cast("dict[str, object]", body)
    user_messages: list[str] = []
    tool_names: list[str] = []
    tool_results: list[str] = []
    messages = body_dict.get("messages")
    if isinstance(messages, list):
        for message in cast("list[object]", messages):
            if not isinstance(message, dict):
                continue
            message_dict = cast("dict[str, object]", message)
            role = message_dict.get("role")
            content = message_dict.get("content")
            if role == "user" and isinstance(content, str):
                user_messages.append(content[:120])
            if role == "tool":
                tool_call_id = message_dict.get("tool_call_id")
                if isinstance(tool_call_id, str):
                    tool_names.append(f"tool_result:{tool_call_id}")
                if isinstance(content, str):
                    tool_results.append(content[:1200])
    tools = body_dict.get("tools")
    if isinstance(tools, list):
        for tool in cast("list[object]", tools):
            if not isinstance(tool, dict):
                continue
            tool_dict = cast("dict[str, object]", tool)
            function = tool_dict.get("function")
            if isinstance(function, dict):
                name = cast("dict[str, object]", function).get("name")
                if isinstance(name, str):
                    tool_names.append(name)
    system_texts = _system_message_texts(item)
    instruction_prefixes = [text[:80].replace("\n", "\\n") for text in system_texts]
    instruction_flags = [
        {
            "len": len(text),
            "has_marker": _MARKER in text,
            "has_runtime_files": "## Runtime Files" in text,
            "has_root_block": "## Session Workspace Instructions" in text,
        }
        for text in system_texts
    ]
    return (
        f"users={user_messages} tools={tool_names[:20]} "
        f"tool_results={tool_results[:5]} "
        f"instructions={instruction_prefixes} instruction_flags={instruction_flags}"
    )


def _history_events(
    *,
    public_url: str,
    access_token: str,
    session_id: str,
) -> list[dict[str, object]]:
    """REST history event listt fetcht."""
    response = requests.get(
        f"{public_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    response.raise_for_status()
    raw_body: object = response.json()
    if not isinstance(raw_body, dict):
        raise AssertionError(f"history response is not an object: {raw_body!r}")
    body = cast("dict[str, object]", raw_body)
    items = body.get("items")
    if not isinstance(items, list):
        raise AssertionError(f"history items is not a list: {body!r}")
    return [
        cast("dict[str, object]", item)
        for item in cast("list[object]", items)
        if isinstance(item, dict)
    ]


def _event_content(event: dict[str, object]) -> str:
    """event payload content text t returnt."""
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return ""
    content = cast("dict[str, object]", payload).get("content")
    if isinstance(content, str):
        return content
    return ""


def _event_payload(event: dict[str, object]) -> dict[str, object]:
    """Return event payload object."""
    payload = event.get("payload")
    if isinstance(payload, dict):
        return cast("dict[str, object]", payload)
    return {}


def _run_marker_completed(event: dict[str, object]) -> bool:
    """run_marker completed t returnt."""
    if event.get("kind") != "run_marker":
        return False
    return _event_payload(event).get("status") == "completed"


def _tool_result_output_text(
    *,
    public_url: str,
    access_token: str,
    session_id: str,
    call_id: str,
) -> str | None:
    """Return persisted client tool result text for a call id."""
    for event in _history_events(
        public_url=public_url,
        access_token=access_token,
        session_id=session_id,
    ):
        if event.get("kind") != "client_tool_result":
            continue
        payload = _event_payload(event)
        if payload.get("call_id") != call_id:
            continue
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
        return str(output)
    return None


def _wait_for_turn_complete(
    *,
    public_url: str,
    access_token: str,
    session_id: str,
    message: str,
    timeout: float = 120,
) -> None:
    """REST write t t turn t durable run_marker t completet t."""
    deadline = time.monotonic() + timeout
    last_events: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        events = _history_events(
            public_url=public_url,
            access_token=access_token,
            session_id=session_id,
        )
        last_events = events
        message_index: int | None = None
        for index, event in enumerate(events):
            if event.get("kind") != "user_message":
                continue
            if _event_content(event) == message:
                message_index = index
        if message_index is not None:
            for event in events[message_index + 1 :]:
                if _run_marker_completed(event):
                    return
        time.sleep(0.5)
    raise TimeoutError(f"turn did not complete: {message}, events={last_events!r}")


def _start_session(
    *,
    public_api_client: azentspublicclient.ApiClient,
    public_url: str,
    access_token: str,
    agent_id: str,
) -> str:
    """Resolve the agent team primary session id."""
    del public_api_client
    session_response = requests.get(
        f"{public_url}/chat/v1/agents/{agent_id}/team-primary-session",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    session_response.raise_for_status()
    session_payload = session_response.json()
    session_id = session_payload.get("id")
    if not isinstance(session_id, str):
        raise AssertionError(
            f"Team primary response did not include id: {session_payload!r}"
        )
    return session_id


def _run_message(
    *,
    public_api_client: azentspublicclient.ApiClient,
    public_url: str,
    access_token: str,
    agent_id: str,
    session_id: str,
    message: str,
) -> None:
    """t session messaget REST write boundary t t."""
    del public_api_client
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/inputs",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={
            "agent_id": agent_id,
            "client_request_id": f"agents-md-appendix-{unique()}",
            "message": message,
        },
        timeout=10,
    )
    response.raise_for_status()
    _wait_for_turn_complete(
        public_url=public_url,
        access_token=access_token,
        session_id=session_id,
        message=message,
    )


def _wait_for_runtime_runner_ready(
    *,
    public_api_client: azentspublicclient.ApiClient,
    token: str,
    workspace_handle: str,
    agent_id: str,
) -> None:
    """Start and wait for a usable Runtime Runner."""
    api = AgentRuntimeV1Api(public_api_client)
    headers = {"Authorization": f"Bearer {token}"}
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


def _exercise_agents_md_loader(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    public_url: str,
    mock_openai_url: str,
) -> AgentsMdExerciseResult:
    """AGENTS.md read appendix t mock journal marker t returnt."""
    requests.delete(
        f"{mock_openai_url}/v1/_requests",
        timeout=10,
    ).raise_for_status()
    unique_id = unique()
    access_token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"agents-md-{unique_id}@example.com",
    )

    workspace_api = WorkspaceV1Api(public_api_client)
    workspace_handle = f"agents-{unique_id}"
    workspace_api.workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"AGENTS QA {unique_id}",
            workspace_handle=workspace_handle,
            owner_name=f"Owner {unique_id}",
        ),
        _headers={"Authorization": f"Bearer {access_token}"},
    )

    integration_api = LLMProviderIntegrationV1Api(public_api_client)
    integration = integration_api.llm_provider_integration_v1_create_integration(
        handle=workspace_handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-test-dummy")),
        ),
        _headers={"Authorization": f"Bearer {access_token}"},
    )
    model_selection = model_selection_from_first_candidate(
        _api_host(public_api_client),
        access_token,
        workspace_handle,
        integration.id,
    )

    agent_api = AgentV1Api(public_api_client)
    agent = agent_api.agent_v1_create_agent(
        handle=workspace_handle,
        agent_create_request=AgentCreateRequest(
            name=f"AGENTS QA Agent {unique_id}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
            runtime_provider_id=_RUNTIME_PROVIDER_ID,
            shell_enabled=True,
        ),
        _headers={"Authorization": f"Bearer {access_token}"},
    )

    session_id = _start_session(
        public_api_client=public_api_client,
        public_url=public_url,
        access_token=access_token,
        agent_id=agent.id,
    )
    _wait_for_runtime_runner_ready(
        public_api_client=public_api_client,
        token=access_token,
        workspace_handle=workspace_handle,
        agent_id=agent.id,
    )
    _run_message(
        public_api_client=public_api_client,
        public_url=public_url,
        access_token=access_token,
        agent_id=agent.id,
        session_id=session_id,
        message=_PREPARE_MESSAGE,
    )
    prepare_output = _tool_result_output_text(
        public_url=public_url,
        access_token=access_token,
        session_id=session_id,
        call_id=_PREPARE_CALL_ID,
    )
    if prepare_output is None or "exit_code: 0" not in prepare_output:
        raise AssertionError(f"AGENTS.md prepare tool failed: {prepare_output!r}")

    _run_message(
        public_api_client=public_api_client,
        public_url=public_url,
        access_token=access_token,
        agent_id=agent.id,
        session_id=session_id,
        message=_READ_MESSAGE,
    )
    read_output = _tool_result_output_text(
        public_url=public_url,
        access_token=access_token,
        session_id=session_id,
        call_id=_READ_CALL_ID,
    )
    if read_output is None:
        raise AssertionError("AGENTS.md governed read did not persist a tool result")
    if _MARKER not in read_output or "<system-reminder>" not in read_output:
        raise AssertionError(
            f"AGENTS.md appendix missing from read result: {read_output!r}"
        )

    payload = requests.get(f"{mock_openai_url}/v1/_requests", timeout=10).json()
    requests_count = len(payload)
    system_marker_requests = [
        index
        for index, item in enumerate(payload, start=1)
        if any(_MARKER in text for text in _system_message_texts(item))
    ]
    tool_result_marker_requests = [
        index
        for index, item in enumerate(payload, start=1)
        if isinstance(item, dict)
        and any(
            _MARKER in text
            for text in _tool_result_texts(cast("dict[str, object]", item))
        )
    ]
    instruction_snippets = [
        text[:500]
        for item in payload
        if isinstance(item, dict)
        for text in _system_message_texts(cast("dict[str, object]", item))
    ]
    tool_result_snippets = [
        text[:1200]
        for item in payload
        if isinstance(item, dict)
        for text in _tool_result_texts(cast("dict[str, object]", item))
    ]
    return AgentsMdExerciseResult(
        requests_count=requests_count,
        system_marker_requests=system_marker_requests,
        tool_result_marker_requests=tool_result_marker_requests,
        instruction_snippets=instruction_snippets,
        tool_result_snippets=tool_result_snippets,
        request_summaries=[
            _request_summary(cast("dict[str, object]", item))
            for item in payload
            if isinstance(item, dict)
        ],
        agent_shell_enabled=agent.shell_enabled,
    )


class TestAgentsMdLoader:
    """AGENTS.md appendix E2E."""

    def test_root_agents_md_is_appended_to_relevant_read_result(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: DockerContainer,
        mock_openai_url: str,
    ) -> None:
        """root AGENTS.md is read-result appendix, not live prompt state."""
        del azents_engine_worker_container

        result = _exercise_agents_md_loader(
            public_api_client=public_api_client,
            admin_api_client=admin_api_client,
            public_url=azents_public_server_url,
            mock_openai_url=mock_openai_url,
        )

        assert result.requests_count >= 3
        assert not result.system_marker_requests, result
        assert result.tool_result_marker_requests, result
