"""Runtime hook product-facing E2E test."""

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
from azentspublicclient.configuration import Configuration
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_model_selection_input import (
    AgentModelSelectionInput,
)
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.agent_toolkit_attach_request import (
    AgentToolkitAttachRequest,
)
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.chat_write_response import ChatWriteResponse
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from pydantic import BaseModel, ConfigDict, JsonValue, StrictStr, TypeAdapter
from testcontainers.core.container import DockerContainer

from support.runtime_profiles import (
    create_workspace_runtime_profile,
    start_and_wait_for_agent_runtime,
)
from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    single_candidate_model_options,
    unique,
)

_RUNTIME_PROVIDER_ID = "system-docker"
_VISIBLE_PROMPT = "RUNTIME_HOOK_QA_VISIBLE_PROMPT_3754"
_HIDDEN_PROMPT = "RUNTIME_HOOK_QA_HIDDEN_PROMPT_3754"
_DENY_MESSAGE = "Runtime hook QA denied this tool call."
_REPLACEMENT_OUTPUT = "Runtime hook QA replaced the tool output."
_SENSITIVE_MARKER = "RUNTIME_HOOK_QA_SECRET_SHOULD_NOT_APPEAR"
_HTTP_OBJECT = TypeAdapter(dict[str, object])


class _HookWireObservation(BaseModel):
    """Validate consumed fields while retaining provider-owned wire extensions."""

    model_config = ConfigDict(extra="allow", frozen=True)


class _HookFunctionObservation(_HookWireObservation):
    name: StrictStr | None = None


class _HookToolObservation(_HookWireObservation):
    name: StrictStr | None = None
    function: _HookFunctionObservation | None = None


class _HookRequestObservation(_HookWireObservation):
    """Support both Responses and Chat fields, with explicit optional absence."""

    instructions: StrictStr | None = None
    messages: list[JsonValue] | None = None
    input: JsonValue = None
    tools: list[_HookToolObservation] | None = None


class _HookJournalEntry(_HookWireObservation):
    body: _HookRequestObservation | None = None


@dataclass(frozen=True)
class _HookJournalObservation:
    """Immutable matching fields plus an opaque independently retained snapshot."""

    message_texts: tuple[str, ...]
    tool_names: tuple[str, ...]
    wire_json: str


_HOOK_JOURNAL = TypeAdapter(list[_HookJournalEntry])


def _api_host(public_api_client: azentspublicclient.ApiClient) -> str:
    """Generated client t API host stringt t."""
    configuration = vars(public_api_client).get("configuration")
    if not isinstance(configuration, Configuration):
        raise AssertionError("public API client omitted configuration")
    host = configuration.host
    if not isinstance(host, str):
        raise AssertionError("public API client configuration omitted host")
    return host


def _decode_content_texts(value: JsonValue) -> tuple[str, ...]:
    """Compile the fixture's existing content selector at the JSON boundary."""
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(text for item in value for text in _decode_content_texts(item))
    if not isinstance(value, dict):
        return ()

    texts: list[str] = []
    for key in ("content", "input", "output", "text"):
        child = value.get(key)
        if isinstance(child, str):
            texts.append(child)
        elif isinstance(child, list):
            texts.extend(_decode_content_texts(child))
    return tuple(texts)


def _decode_hook_journal(value: object) -> list[_HookJournalObservation]:
    """Decode matching fields once; malformed consumed shapes are not readiness."""
    observations: list[_HookJournalObservation] = []
    for entry in _HOOK_JOURNAL.validate_python(value):
        texts: list[str] = []
        names: list[str] = []
        body = entry.body
        if body is not None:
            if body.instructions is not None:
                texts.append(body.instructions)
            for message in body.messages or ():
                texts.extend(_decode_content_texts(message))
            if isinstance(body.input, str | list):
                texts.extend(_decode_content_texts(body.input))
            for tool in body.tools or ():
                if tool.name is not None:
                    names.append(tool.name)
                elif tool.function is not None and tool.function.name is not None:
                    names.append(tool.function.name)
        observations.append(
            _HookJournalObservation(
                message_texts=tuple(texts),
                tool_names=tuple(names),
                wire_json=json.dumps(
                    entry.model_dump(mode="json", exclude_unset=True),
                    ensure_ascii=False,
                ),
            )
        )
    return observations


def _decode_hook_session(value: object) -> AgentSessionResponse:
    """Use the generated Session wire contract without erasing extensions."""
    session = AgentSessionResponse.from_dict(_HTTP_OBJECT.validate_python(value))
    if session is None:
        raise AssertionError("Expected a non-null Session response.")
    return session


def _decode_hook_write(value: object) -> ChatWriteResponse:
    """Decode the accepted write and native nested snapshot at HTTP ingress."""
    write = ChatWriteResponse.from_dict(_HTTP_OBJECT.validate_python(value))
    if write is None:
        raise AssertionError("Expected a non-null Chat write response.")
    return write


def _message_texts(item: _HookJournalObservation) -> list[str]:
    """Return the already-decoded provider content correlation projection."""
    return list(item.message_texts)


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


def _journal_items(mock_openai_url: str) -> list[_HookJournalObservation]:
    """Return typed AIMock request journal items."""
    response = requests.get(f"{mock_openai_url}/v1/_requests", timeout=10)
    response.raise_for_status()
    return _decode_hook_journal(response.json())


def _request_tool_names(item: _HookJournalObservation) -> list[str]:
    """Extract declared client function names from one AIMock request."""
    return list(item.tool_names)


def _tool_request_snapshots(
    mock_openai_url: str,
    user_message: str,
) -> list[list[str]]:
    """Return declared tool names for requests containing one user message."""
    snapshots: list[list[str]] = []
    for item in _journal_items(mock_openai_url):
        if user_message not in _message_texts(item):
            continue
        names = _request_tool_names(item)
        if names:
            snapshots.append(names)
    return snapshots


def _wait_for_tool_request_snapshots(
    mock_openai_url: str,
    user_message: str,
    *,
    minimum_count: int,
    required_tool: str,
    timeout: float = 120,
) -> list[list[str]]:
    """Wait for request snapshots proving one tool declaration transition."""
    deadline = time.monotonic() + timeout
    snapshots: list[list[str]] = []
    while time.monotonic() < deadline:
        snapshots = _tool_request_snapshots(mock_openai_url, user_message)
        if len(snapshots) >= minimum_count and any(
            required_tool in names for names in snapshots
        ):
            return snapshots
        time.sleep(0.5)
    raise TimeoutError(
        "AIMock journal did not include required tool request snapshots: "
        f"message={user_message!r}, required_tool={required_tool!r}, "
        f"snapshots={snapshots!r}, journal={_journal_debug(mock_openai_url)}"
    )


def _all_journal_text(mock_openai_url: str) -> str:
    """AIMock journal t t message text t t stringt t."""
    return "\n".join(
        text
        for item in _journal_items(mock_openai_url)
        for text in _message_texts(item)
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
        session_id_value = _decode_hook_session(session_response.json()).id
    else:
        session_id_value = session_id
    path = f"/chat/v1/sessions/{session_id_value}/inputs"
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
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
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
    return _decode_hook_write(response.json()).session_id


def _wait_for_session_idle(
    *,
    public_url: str,
    access_token: str,
    agent_id: str,
    session_id: str,
    timeout: float = 120,
) -> None:
    """Wait until the authoritative session projection becomes idle."""
    deadline = time.monotonic() + timeout
    last_state: object = None
    while time.monotonic() < deadline:
        response = requests.get(
            f"{public_url}/chat/v1/agents/{agent_id}/sessions/{session_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        response.raise_for_status()
        last_state = _decode_hook_session(response.json()).run_state
        if last_state == "idle":
            return
        time.sleep(0.5)
    raise TimeoutError(f"Tool Search session did not become idle: {last_state!r}")


class _RuntimeHookWorkspace:
    """runtime hook QA t t product resource t."""

    def __init__(
        self,
        token: str,
        handle: str,
        model_selection: AgentModelSelectionInput,
        runtime_profile_id: str,
    ) -> None:
        self.token = token
        self.handle = handle
        self.model_selection = model_selection
        self.runtime_profile_id = runtime_profile_id


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
    runtime_profile_id = create_workspace_runtime_profile(
        public_api_client,
        token=token,
        workspace_handle=handle,
        provider_id=_RUNTIME_PROVIDER_ID,
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
        runtime_profile_id=runtime_profile_id,
    )


def _create_agent_with_runtime_hook_toolkit(
    public_api_client: azentspublicclient.ApiClient,
    workspace: _RuntimeHookWorkspace,
    *,
    toolkit_slug: str,
    mode: str,
    visible_prompt: str | None = None,
    hidden_prompt: str | None = None,
    tool_search_enabled: bool = False,
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
    start_and_wait_for_agent_runtime(
        public_api_client,
        token=workspace.token,
        workspace_handle=workspace.handle,
        agent_id=agent.id,
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
        )
        observe_message = "Create AGENTS.md"
        _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            access_token=workspace.token,
            agent_id=observe_agent_id,
            message=observe_message,
        )
        observe_probe_name = "rtqa_observe__runtime_hook_qa_probe"
        observe_snapshots = _wait_for_tool_request_snapshots(
            mock_openai_url,
            observe_message,
            minimum_count=1,
            required_tool=observe_probe_name,
        )
        if "tool_search" in observe_snapshots[0]:
            raise AssertionError(
                "Default-disabled Agent unexpectedly exposed tool_search: "
                f"{observe_snapshots!r}"
            )

        deny_agent_id = _create_agent_with_runtime_hook_toolkit(
            public_api_client,
            workspace,
            toolkit_slug="rtqa_deny",
            mode="deny",
            tool_search_enabled=True,
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
            tool_search_enabled=True,
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
            '"runtime_hook_qa_lifecycle": "on_session_start"',
            '"runtime_hook_qa_lifecycle": "on_run_start"',
            '"runtime_hook_qa_lifecycle": "on_turn_start"',
            '"runtime_hook_qa_lifecycle": "on_before_tool_call"',
            '"runtime_hook_qa_lifecycle": "on_after_tool_call"',
            '"runtime_hook_qa_lifecycle": "on_turn_end"',
            '"runtime_hook_qa_lifecycle": "on_run_end"',
        ]:
            _wait_for_container_log(azents_engine_worker_container, marker)

        worker_logs = _container_logs(azents_engine_worker_container)
        if _SENSITIVE_MARKER in worker_logs:
            raise AssertionError(
                "Sensitive runtime hook marker leaked into worker logs: "
                f"{_shorten(worker_logs)}"
            )

    def test_tool_search_persists_deferred_probe_across_runs(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_public_server_container: DockerContainer,
        azents_engine_worker_container: DockerContainer,
        mock_openai_url: str,
    ) -> None:
        """Verify deferred search activation and session persistence end to end."""
        requests.delete(
            f"{mock_openai_url}/v1/_requests",
            timeout=10,
        ).raise_for_status()
        workspace = _setup_workspace(public_api_client, admin_api_client)
        agent_id = _create_agent_with_runtime_hook_toolkit(
            public_api_client,
            workspace,
            toolkit_slug="rtqa_tool_search",
            mode="observe",
            tool_search_enabled=True,
        )
        probe_name = "rtqa_tool_search__runtime_hook_qa_probe"
        first_message = "Tool Search deferred probe first run"
        session_id = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            access_token=workspace.token,
            agent_id=agent_id,
            message=first_message,
            debug_public_container=azents_public_server_container,
            debug_worker_container=azents_engine_worker_container,
            debug_mock_openai_url=mock_openai_url,
        )

        first_snapshots = _wait_for_tool_request_snapshots(
            mock_openai_url,
            first_message,
            minimum_count=2,
            required_tool=probe_name,
        )
        _wait_for_session_idle(
            public_url=azents_public_server_url,
            access_token=workspace.token,
            agent_id=agent_id,
            session_id=session_id,
        )

        if "tool_search" not in first_snapshots[0]:
            raise AssertionError(
                f"First request did not expose tool_search: {first_snapshots!r}"
            )
        if probe_name in first_snapshots[0]:
            raise AssertionError(
                f"Deferred probe leaked into first request: {first_snapshots!r}"
            )
        if not any(probe_name in names for names in first_snapshots[1:]):
            raise AssertionError(
                f"Deferred probe was not activated after search: {first_snapshots!r}"
            )

        persisted_message = "Tool Search deferred probe persisted run"
        observed_session_id = _run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            access_token=workspace.token,
            agent_id=agent_id,
            session_id=session_id,
            message=persisted_message,
            debug_public_container=azents_public_server_container,
            debug_worker_container=azents_engine_worker_container,
            debug_mock_openai_url=mock_openai_url,
        )
        if observed_session_id != session_id:
            raise AssertionError(
                "Persisted Tool Search run changed AgentSession identity: "
                f"expected={session_id!r}, observed={observed_session_id!r}"
            )
        persisted_snapshots = _wait_for_tool_request_snapshots(
            mock_openai_url,
            persisted_message,
            minimum_count=1,
            required_tool=probe_name,
        )
        _wait_for_session_idle(
            public_url=azents_public_server_url,
            access_token=workspace.token,
            agent_id=agent_id,
            session_id=session_id,
        )

        if probe_name not in persisted_snapshots[0]:
            raise AssertionError(
                "Persisted deferred probe was absent from the next Run's first "
                f"request: {persisted_snapshots!r}"
            )
