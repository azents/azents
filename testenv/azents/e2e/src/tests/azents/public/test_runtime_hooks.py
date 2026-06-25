"""Runtime hook product-facing E2E test."""

import json
import time
from typing import Any, cast

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
from pydantic import TypeAdapter
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
_VISIBLE_PROMPT = "RUNTIME_HOOK_QA_VISIBLE_PROMPT_3754"
_HIDDEN_PROMPT = "RUNTIME_HOOK_QA_HIDDEN_PROMPT_3754"
_DENY_MESSAGE = "Runtime hook QA denied this tool call."
_REPLACEMENT_OUTPUT = "Runtime hook QA replaced the tool output."
_SENSITIVE_MARKER = "RUNTIME_HOOK_QA_SECRET_SHOULD_NOT_APPEAR"
_OBJECT_DICT_ADAPTER: TypeAdapter[dict[object, object]] = TypeAdapter(
    dict[object, object]
)
_OBJECT_LIST_ADAPTER: TypeAdapter[list[object]] = TypeAdapter(list[object])


def _api_host(public_api_client: azentspublicclient.ApiClient) -> str:
    """Generated client t API host stringt t."""
    configuration = cast(Any, public_api_client).configuration
    return str(configuration.host)


def _message_texts(item: dict[str, object]) -> list[str]:
    """AIMock journal item t request message stringt t t."""
    body = _object_dict(item.get("body"))
    if body is None:
        return []

    texts: list[str] = []
    instructions = body.get("instructions")
    if isinstance(instructions, str):
        texts.append(instructions)

    message_items = _object_list(body.get("messages"))
    if message_items is not None:
        for message in message_items:
            texts.extend(_content_texts(message))

    request_input = body.get("input")
    if isinstance(request_input, str):
        texts.append(request_input)
    else:
        input_items = _object_list(request_input)
        if input_items is None:
            return texts
        for input_item in input_items:
            texts.extend(_content_texts(input_item))
    return texts


def _object_dict(value: object) -> dict[object, object] | None:
    """external JSON object t typed dict t verifyt."""
    if not isinstance(value, dict):
        return None
    return _OBJECT_DICT_ADAPTER.validate_python(value)


def _object_list(value: object) -> list[object] | None:
    """external JSON array t typed list t verifyt."""
    if not isinstance(value, list):
        return None
    return _OBJECT_LIST_ADAPTER.validate_python(value)


def _content_texts(value: object) -> list[str]:
    """Responses/Chat content shape t model t text t t."""
    if isinstance(value, str):
        return [value]
    values = _object_list(value)
    if values is not None:
        texts: list[str] = []
        for item in values:
            texts.extend(_content_texts(item))
        return texts
    value_dict = _object_dict(value)
    if value_dict is None:
        return []

    texts: list[str] = []
    for key in ("content", "input", "output", "text"):
        child = value_dict.get(key)
        if isinstance(child, str):
            texts.append(child)
        else:
            child_items = _object_list(child)
            if child_items is None:
                continue
            texts.extend(_content_texts(child_items))
    return texts


def _shorten(text: str, *, max_chars: int = 4000) -> str:
    """Assertion messaget t stringt t."""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _log_debug(text: str) -> str:
    """t container t t t tail t t."""
    markers = ("ERROR", "Traceback", "Exception", "Connection", "Internal error")
    interesting = [
        line for line in text.splitlines() if any(marker in line for marker in markers)
    ]
    if interesting:
        return _shorten("\n".join([*interesting[-80:], "--- tail ---", text[-2000:]]))
    return _shorten(text)


def _all_journal_text(mock_openai_url: str) -> str:
    """AIMock journal t t message text t t stringt t."""
    payload = requests.get(f"{mock_openai_url}/v1/_requests", timeout=10).json()
    items = cast("list[object]", payload)
    return "\n".join(
        text
        for item in items
        if isinstance(item, dict)
        for text in _message_texts(cast("dict[str, object]", item))
    )


def _journal_debug(mock_openai_url: str) -> str:
    """AIMock journal payload t assertion messaget t."""
    payload = requests.get(f"{mock_openai_url}/v1/_requests", timeout=10).json()
    return _shorten(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _wait_for_journal_text(
    mock_openai_url: str,
    required_markers: tuple[str, ...],
    *,
    timeout: float = 120,
) -> str:
    """AIMock journal t required marker t t t t t."""
    deadline = time.monotonic() + timeout
    journal_text = ""
    while time.monotonic() < deadline:
        journal_text = _all_journal_text(mock_openai_url)
        if all(marker in journal_text for marker in required_markers):
            return journal_text
        time.sleep(0.5)
    raise TimeoutError(
        "AIMock journal did not include runtime hook markers: "
        f"{required_markers}, journal={_shorten(journal_text)}"
    )


def _container_logs(container: DockerContainer) -> str:
    """container stdout/stderr t stringt t."""
    stdout, stderr = container.get_logs()
    return stdout.decode(errors="replace") + stderr.decode(errors="replace")


def _wait_for_container_log(container: DockerContainer, marker: str) -> None:
    """container t marker t t t pendingt."""
    deadline = time.monotonic() + 180
    last_logs = ""
    while time.monotonic() < deadline:
        last_logs = _container_logs(container)
        if marker in last_logs:
            return
        time.sleep(1)
    raise AssertionError(f"log marker not observed: {marker}\n{last_logs[-4000:]}")


def _run_message(
    *,
    public_api_client: azentspublicclient.ApiClient,
    public_url: str,
    access_token: str,
    agent_id: str,
    message: str,
    session_id: str | None = None,
    debug_public_container: DockerContainer | None = None,
    debug_worker_container: DockerContainer | None = None,
    debug_mock_openai_url: str | None = None,
) -> str:
    """REST write boundary t t turn t runt session_id t returnt."""
    del public_api_client
    if session_id is None:
        session_response = requests.get(
            f"{public_url}/chat/v1/agents/{agent_id}/team-primary-session",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        session_response.raise_for_status()
        session_payload = session_response.json()
        session_id_value = session_payload.get("id")
        if not isinstance(session_id_value, str):
            raise AssertionError(
                f"Team primary response did not include id: {session_payload!r}"
            )
    else:
        session_id_value = session_id
    path = f"/chat/v1/sessions/{session_id_value}/messages"
    response = requests.post(
        f"{public_url}{path}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={
            "agent_id": agent_id,
            "client_request_id": f"runtime-hooks-message-{unique()}",
            "message": message,
        },
        timeout=10,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        public_logs = (
            _log_debug(_container_logs(debug_public_container))
            if debug_public_container is not None
            else "<public logs unavailable>"
        )
        worker_logs = (
            _log_debug(_container_logs(debug_worker_container))
            if debug_worker_container is not None
            else "<worker logs unavailable>"
        )
        journal = (
            _journal_debug(debug_mock_openai_url)
            if debug_mock_openai_url is not None
            else "<AIMock journal unavailable>"
        )
        raise AssertionError(
            f"REST write failed during runtime hook message: {message}\n"
            f"response={response.text!r}\npublic_logs={public_logs}\n"
            f"worker_logs={worker_logs}\njournal={journal}"
        ) from exc
    raw_payload: object = response.json()
    if not isinstance(raw_payload, dict):
        raise AssertionError(f"REST write response is not an object: {raw_payload!r}")
    payload = cast("dict[str, object]", raw_payload)
    observed_session_id = payload.get("session_id")
    if not isinstance(observed_session_id, str):
        raise AssertionError(
            f"REST write response did not include session_id: {payload!r}"
        )
    return observed_session_id


class _RuntimeHookWorkspace:
    """runtime hook QA t t product resource t."""

    def __init__(
        self,
        token: str,
        handle: str,
        model_selection: AgentModelSelectionInput,
    ) -> None:
        self.token = token
        self.handle = handle
        self.model_selection = model_selection


def _setup_workspace(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> _RuntimeHookWorkspace:
    """workspacet model selection t t API t t."""
    uniq = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"runtime-hooks-{uniq}@example.com",
    )
    headers = {"Authorization": f"Bearer {token}"}
    handle = f"runtime-hooks-{uniq}"

    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Runtime Hooks QA {uniq}",
            workspace_handle=handle,
            owner_name=f"Owner {uniq}",
        ),
        _headers=headers,
    )
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-runtime-hooks-qa")),
        ),
        _headers=headers,
    )
    return _RuntimeHookWorkspace(
        token=token,
        handle=handle,
        model_selection=model_selection_from_first_candidate(
            _api_host(public_api_client),
            token,
            handle,
            integration.id,
        ),
    )


def _create_agent_with_runtime_hook_toolkit(
    public_api_client: azentspublicclient.ApiClient,
    workspace: _RuntimeHookWorkspace,
    *,
    toolkit_slug: str,
    mode: str,
    visible_prompt: str | None = None,
    hidden_prompt: str | None = None,
    shell_enabled: bool = False,
) -> str:
    """runtime_hook_qa toolkit t t API t createt agent t t."""
    headers = {"Authorization": f"Bearer {workspace.token}"}
    toolkit_api = ToolkitV1Api(public_api_client)
    toolkit = toolkit_api.toolkit_v1_create_toolkit_config(
        handle=workspace.handle,
        toolkit_config_create_request=ToolkitConfigCreateRequest(
            toolkit_type="runtime_hook_qa",
            slug=toolkit_slug,
            name=f"Runtime Hook QA {toolkit_slug}",
            config={
                "mode": mode,
                "visible_prompt": visible_prompt,
                "hidden_prompt": hidden_prompt,
                "deny_message": _DENY_MESSAGE,
                "replacement_output": _REPLACEMENT_OUTPUT,
                "sensitive_marker": _SENSITIVE_MARKER,
            },
            enabled=True,
        ),
        _headers=headers,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name=f"Runtime Hook QA Agent {toolkit_slug}",
            model_selection=workspace.model_selection,
            lightweight_model_selection=workspace.model_selection,
            type=AgentType.PUBLIC,
            runtime_provider_id=_RUNTIME_PROVIDER_ID,
            shell_enabled=shell_enabled,
        ),
        _headers=headers,
    )
    toolkit_api.toolkit_v1_attach_toolkit_to_agent(
        handle=workspace.handle,
        agent_id=agent.id,
        agent_toolkit_attach_request=AgentToolkitAttachRequest(toolkit_id=toolkit.id),
        _headers=headers,
    )
    return agent.id


class TestRuntimeHooks:
    """runtime hook lifecycle t t patht verifyt."""

    def test_runtime_hooks_execute_through_public_chat_path(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_public_server_container: DockerContainer,
        azents_engine_worker_container: DockerContainer,
        mock_openai_url: str,
    ) -> None:
        """turn/tool hook t user patht runt."""
        requests.delete(
            f"{mock_openai_url}/v1/_requests",
            timeout=10,
        ).raise_for_status()
        workspace = _setup_workspace(public_api_client, admin_api_client)

        observe_agent_id = _create_agent_with_runtime_hook_toolkit(
            public_api_client,
            workspace,
            toolkit_slug="rtqa_observe",
            mode="observe",
            visible_prompt=_VISIBLE_PROMPT,
            hidden_prompt=_HIDDEN_PROMPT,
            shell_enabled=True,
        )
        _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            access_token=workspace.token,
            agent_id=observe_agent_id,
            message="Create AGENTS.md",
        )

        deny_agent_id = _create_agent_with_runtime_hook_toolkit(
            public_api_client,
            workspace,
            toolkit_slug="rtqa_deny",
            mode="deny",
        )
        _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            access_token=workspace.token,
            agent_id=deny_agent_id,
            message="Run deny hook QA",
        )

        replace_agent_id = _create_agent_with_runtime_hook_toolkit(
            public_api_client,
            workspace,
            toolkit_slug="rtqa_replace",
            mode="replace",
        )
        _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            access_token=workspace.token,
            agent_id=replace_agent_id,
            message="Run replace hook QA",
            debug_public_container=azents_public_server_container,
            debug_worker_container=azents_engine_worker_container,
            debug_mock_openai_url=mock_openai_url,
        )

        journal_text = _wait_for_journal_text(
            mock_openai_url,
            (
                _VISIBLE_PROMPT,
                _HIDDEN_PROMPT,
                _DENY_MESSAGE,
                _REPLACEMENT_OUTPUT,
            ),
        )
        if _SENSITIVE_MARKER in journal_text:
            raise AssertionError(
                "Sensitive runtime hook marker leaked into model-visible request text: "
                f"{_shorten(journal_text)}"
            )

        for marker in [
            "Runtime hook QA lifecycle event: on_session_start",
            "Runtime hook QA lifecycle event: on_run_start",
            "Runtime hook QA lifecycle event: on_turn_start",
            "Runtime hook QA lifecycle event: on_before_tool_call",
            "Runtime hook QA lifecycle event: on_after_tool_call",
            "Runtime hook QA lifecycle event: on_turn_end",
            "Runtime hook QA lifecycle event: on_run_end",
        ]:
            _wait_for_container_log(azents_engine_worker_container, marker)

        worker_logs = _container_logs(azents_engine_worker_container)
        if _SENSITIVE_MARKER in worker_logs:
            raise AssertionError(
                "Sensitive runtime hook marker leaked into worker logs: "
                f"{_shorten(worker_logs)}"
            )
