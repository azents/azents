"""File/resource lifecycle product E2E test."""

import json
import time
from typing import Any, cast

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
_PREPARE_MESSAGE = "Prepare file resource lifecycle attachment"
_PREPARE_RETRY_MESSAGE_1 = "Retry prepare file resource lifecycle attachment 1"
_PREPARE_RETRY_MESSAGE_2 = "Retry prepare file resource lifecycle attachment 2"
_PREPARE_RETRY_MESSAGE_3 = "Retry prepare file resource lifecycle attachment 3"
_PRESENT_MESSAGE = "Present file resource lifecycle attachment"
_PRESENT_RETRY_MESSAGE_1 = "Retry present file resource lifecycle attachment 1"
_PRESENT_RETRY_MESSAGE_2 = "Retry present file resource lifecycle attachment 2"
_PRESENT_RETRY_MESSAGE_3 = "Retry present file resource lifecycle attachment 3"
_PREPARED_RESPONSE = "File resource lifecycle source file was prepared."
_PRESENTED_RESPONSE = "File resource lifecycle attachment metadata was observed."
_FILE_NAME = "lifecycle-report.txt"
_FILE_PREVIEW_MARKER = "FILE_RESOURCE_LIFECYCLE_E2E_PREVIEW_MARKER"
_PREPARE_ATTEMPTS = (
    (_PREPARE_MESSAGE, "call_file_resource_lifecycle_write"),
    (_PREPARE_RETRY_MESSAGE_1, "call_file_resource_lifecycle_write_retry_1"),
    (_PREPARE_RETRY_MESSAGE_2, "call_file_resource_lifecycle_write_retry_2"),
    (_PREPARE_RETRY_MESSAGE_3, "call_file_resource_lifecycle_write_retry_3"),
)
_PRESENT_ATTEMPTS = (
    (_PRESENT_MESSAGE, "call_file_resource_lifecycle_present"),
    (_PRESENT_RETRY_MESSAGE_1, "call_file_resource_lifecycle_present_retry_1"),
    (_PRESENT_RETRY_MESSAGE_2, "call_file_resource_lifecycle_present_retry_2"),
    (_PRESENT_RETRY_MESSAGE_3, "call_file_resource_lifecycle_present_retry_3"),
)
_TRANSIENT_RUNTIME_ERRORS = (
    "Runtime Provider is disconnected",
    "Runtime is temporarily unavailable",
    "Runtime Provider is disconnected. Please try again",
    "Runtime is still starting",
)
_OBJECT_DICT_ADAPTER: TypeAdapter[dict[object, object]] = TypeAdapter(
    dict[object, object]
)


def _has_exchange_file_location_uri(text: str) -> bool:
    """Opaque Exchange file-location URIt t t checkt."""
    return "exchange://" in text and "exchange://files/" not in text


def _headers(token: str) -> dict[str, str]:
    """Bearer auth header t t."""
    return {"Authorization": f"Bearer {token}"}


def _object_dict(value: object) -> dict[object, object] | None:
    """external JSON object t typed dict t verifyt."""
    if not isinstance(value, dict):
        return None
    return _OBJECT_DICT_ADAPTER.validate_python(value)


def _api_host(public_api_client: azentspublicclient.ApiClient) -> str:
    """Generated client t API host stringt t."""
    configuration = cast(Any, public_api_client).configuration
    return str(configuration.host)


def _run_new_session_until_complete(
    *,
    public_api_client: azentspublicclient.ApiClient,
    public_url: str,
    access_token: str,
    agent_id: str,
) -> str:
    """t sessiont init turn t REST write boundary t t session_id t returnt."""
    del public_api_client
    session_response = requests.get(
        f"{public_url}/chat/v1/agents/{agent_id}/team-primary-session",
        headers=_headers(access_token),
        timeout=10,
    )
    session_response.raise_for_status()
    raw_session_payload: object = session_response.json()
    if not isinstance(raw_session_payload, dict):
        raise AssertionError(
            f"Team primary response is not an object: {raw_session_payload!r}"
        )
    session_payload = cast("dict[str, object]", raw_session_payload)
    session_id = session_payload.get("id")
    if not isinstance(session_id, str):
        raise AssertionError(
            f"Team primary response did not include id: {session_payload!r}"
        )
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/messages",
        headers={**_headers(access_token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"file-lifecycle-init-{unique()}",
            "message": "init",
        },
        timeout=10,
    )
    response.raise_for_status()
    return session_id


def _create_shell_enabled_chat_session_with_agent(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
) -> tuple[str, str, str, str]:
    """shell_enabled agent t chat session t createt."""
    uniq = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"file-lifecycle-{uniq}@example.com",
    )

    workspace_handle = f"file-lifecycle-{uniq}"
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"File Lifecycle {uniq}",
            workspace_handle=workspace_handle,
            owner_name=f"Owner {uniq}",
        ),
        _headers=_headers(token),
    )

    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=workspace_handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-test-key")),
        ),
        _headers=_headers(token),
    )
    model_selection = model_selection_from_first_candidate(
        _api_host(public_api_client),
        token,
        workspace_handle,
        integration.id,
    )

    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace_handle,
        agent_create_request=AgentCreateRequest(
            name=f"File Lifecycle Agent {uniq}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
            runtime_provider_id=_RUNTIME_PROVIDER_ID,
            shell_enabled=True,
        ),
        _headers=_headers(token),
    )
    session_id = _run_new_session_until_complete(
        public_api_client=public_api_client,
        public_url=server_url,
        access_token=token,
        agent_id=agent.id,
    )
    return token, session_id, agent.id, workspace_handle


def _wait_for_runtime_runner_ready(
    public_api_client: azentspublicclient.ApiClient,
    *,
    token: str,
    workspace_handle: str,
    agent_id: str,
) -> None:
    """Runtime API t runner use t statet t."""
    api = AgentRuntimeV1Api(public_api_client)
    headers = _headers(token)
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


def _run_message(
    *,
    public_api_client: azentspublicclient.ApiClient,
    public_url: str,
    access_token: str,
    session_id: str,
    agent_id: str,
    message: str,
) -> None:
    """t session t message t REST write boundary t t."""
    del public_api_client
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/messages",
        headers={**_headers(access_token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"file-lifecycle-message-{unique()}",
            "message": message,
        },
        timeout=10,
    )
    response.raise_for_status()


def _list_messages(
    server_url: str,
    token: str,
    session_id: str,
) -> dict[str, object]:
    """REST history t fetcht."""
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError(f"REST history response is not an object: {payload!r}")
    return cast("dict[str, object]", payload)


def _content_text(content: object) -> str:
    """event content string t part arrayt text bodyt returnt."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for part in cast("list[object]", content):
        if not isinstance(part, dict):
            continue
        part_dict = cast("dict[str, object]", part)
        if part_dict.get("type") in {"input_text", "output_text", "text"}:
            text = part_dict.get("text")
            if isinstance(text, str):
                texts.append(text)
    return "\n".join(texts)


def _message_item_from_event(event: dict[str, object]) -> dict[str, object]:
    """History event t t assertion t t message-like dict t t."""
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    payload_dict = cast("dict[str, object]", payload)
    kind = event.get("kind")
    item: dict[str, object] = {"id": event.get("id"), "role": kind}
    match kind:
        case "user_message":
            item["role"] = "user"
            item["content"] = _content_text(payload_dict.get("content"))
            item["attachments"] = payload_dict.get("attachments")
        case "assistant_message":
            item["role"] = "assistant"
            item["content"] = _content_text(payload_dict.get("content"))
        case "client_tool_call":
            item["role"] = "assistant"
            item["tool_calls"] = [
                {
                    "id": payload_dict.get("call_id"),
                    "name": payload_dict.get("name"),
                }
            ]
        case "client_tool_result":
            item["role"] = "tool"
            item["tool_call_id"] = payload_dict.get("call_id")
            item["content"] = payload_dict.get("output")
            item["attachments"] = payload_dict.get("attachments")
            item["metadata"] = {"status": payload_dict.get("status")}
        case _:
            item["role"] = kind
    return item


def _message_items(payload: dict[str, object]) -> list[dict[str, object]]:
    """REST history item listt verifyt returnt."""
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise AssertionError(f"REST history items is not a list: {payload!r}")
    items = cast("list[object]", raw_items)
    return [
        _message_item_from_event(cast("dict[str, object]", item))
        for item in items
        if isinstance(item, dict)
    ]


def _wait_for_rest_message(
    server_url: str,
    token: str,
    session_id: str,
    content: str,
    *,
    timeout: float = 90,
) -> dict[str, object]:
    """REST history t t content t t t t."""
    deadline = time.monotonic() + timeout
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        payload = _list_messages(server_url, token, session_id)
        last_payload = payload
        for item in _message_items(payload):
            if item.get("content") == content:
                return item
        time.sleep(0.5)
    raise TimeoutError(f"REST message was not observed: {content}, {last_payload!r}")


def _transient_runtime_error_seen(
    server_url: str,
    token: str,
    session_id: str,
    tool_call_id: str,
) -> str | None:
    """REST history t current tool call t transient failure t t checkt."""
    payload = _list_messages(server_url, token, session_id)
    for item in _message_items(payload):
        if item.get("role") != "tool" or item.get("tool_call_id") != tool_call_id:
            continue
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            continue
        metadata_dict = cast("dict[str, object]", metadata)
        if metadata_dict.get("status") != "failed":
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        if any(error in content for error in _TRANSIENT_RUNTIME_ERRORS):
            return content
    return None


def _tool_call_succeeded(
    server_url: str,
    token: str,
    session_id: str,
    tool_call_id: str,
    *,
    required_content: str | None = None,
    timeout: float = 30,
) -> bool:
    """current tool call t successt REST history t checkt."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = _list_messages(server_url, token, session_id)
        for item in _message_items(payload):
            if item.get("role") != "tool" or item.get("tool_call_id") != tool_call_id:
                continue
            metadata = _object_dict(item.get("metadata"))
            if metadata is None:
                return False
            status = metadata.get("status")
            if status != "completed":
                return False
            if required_content is None:
                return True
            content = item.get("content")
            return isinstance(content, str) and required_content in content
        time.sleep(0.5)
    return False


def _wait_for_tool_result(
    server_url: str,
    token: str,
    session_id: str,
    tool_call_id: str,
    *,
    timeout: float = 30,
) -> dict[str, object] | None:
    """current tool call result t REST history t t."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = _list_messages(server_url, token, session_id)
        for item in _message_items(payload):
            if item.get("role") == "tool" and item.get("tool_call_id") == tool_call_id:
                return item
        time.sleep(0.5)
    return None


def _tool_result_has_present_file_attachment(item: dict[str, object]) -> bool:
    """present_file result t attachment metadata t t checkt."""
    encoded = json.dumps(item, ensure_ascii=False, sort_keys=True)
    return (
        _FILE_NAME in encoded
        and _has_exchange_file_location_uri(encoded)
        and _FILE_PREVIEW_MARKER in encoded
    )


def _tool_history_debug(
    server_url: str,
    token: str,
    session_id: str,
) -> list[dict[str, object]]:
    """Assertion messaget tool history summaryt t."""
    payload = _list_messages(server_url, token, session_id)
    rows: list[dict[str, object]] = []
    for item in _message_items(payload):
        if item.get("role") != "tool":
            continue
        rows.append(
            {
                "tool_call_id": item.get("tool_call_id"),
                "content": item.get("content"),
                "attachments": item.get("attachments"),
                "metadata": item.get("metadata"),
            }
        )
    return rows


def _mock_openai_journal_payload(mock_openai_url: str) -> list[dict[str, Any]]:
    """AIMock journal JSON payload t returnt."""
    payload = requests.get(f"{mock_openai_url}/v1/_requests", timeout=10).json()
    if not isinstance(payload, list):
        raise AssertionError(f"AIMock journal is not a list: {payload!r}")
    items = cast("list[object]", payload)
    return [cast("dict[str, Any]", item) for item in items if isinstance(item, dict)]


def _reset_mock_openai(mock_openai_url: str) -> None:
    """AIMock request journal t initializet."""
    requests.delete(f"{mock_openai_url}/v1/_requests", timeout=10).raise_for_status()


def _journal_text(mock_openai_url: str) -> str:
    """AIMock journal t assertion t stringt t."""
    return json.dumps(
        _mock_openai_journal_payload(mock_openai_url),
        ensure_ascii=False,
        sort_keys=True,
    )


def _wait_for_attachment_metadata_journal(
    mock_openai_url: str,
    *,
    timeout: float = 180,
) -> str:
    """present_file attachment metadata t model request t t t pendingt."""
    deadline = time.monotonic() + timeout
    last_journal = ""
    while time.monotonic() < deadline:
        last_journal = _journal_text(mock_openai_url)
        if (
            f"Attachment: {_FILE_NAME}" in last_journal
            and _has_exchange_file_location_uri(last_journal)
            and _FILE_PREVIEW_MARKER in last_journal
        ):
            return last_journal
        time.sleep(0.5)
    raise TimeoutError(
        "AIMock journal did not include present_file attachment metadata: "
        f"{last_journal}"
    )


class TestFileResourceLifecycle:
    """File/resource lifecycle product E2E."""

    def test_present_file_attachment_reaches_model_as_metadata(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: DockerContainer,
        mock_openai_url: str,
    ) -> None:
        """present_file result attachment t metadata t modelt t."""
        del azents_engine_worker_container
        _reset_mock_openai(mock_openai_url)
        (
            token,
            session_id,
            agent_id,
            workspace_handle,
        ) = _create_shell_enabled_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        _wait_for_runtime_runner_ready(
            public_api_client,
            token=token,
            workspace_handle=workspace_handle,
            agent_id=agent_id,
        )

        last_transient_error: str | None = None
        for attempt, (message, tool_call_id) in enumerate(_PREPARE_ATTEMPTS, start=1):
            _run_message(
                public_api_client=public_api_client,
                public_url=azents_public_server_url,
                access_token=token,
                session_id=session_id,
                agent_id=agent_id,
                message=message,
            )
            transient_error = _transient_runtime_error_seen(
                azents_public_server_url,
                token,
                session_id,
                tool_call_id,
            )
            if transient_error is not None:
                last_transient_error = transient_error
                time.sleep(float(attempt * 5))
                continue
            if not _tool_call_succeeded(
                azents_public_server_url,
                token,
                session_id,
                tool_call_id,
                required_content="exit_code: 0",
            ):
                history = _tool_history_debug(
                    azents_public_server_url,
                    token,
                    session_id,
                )
                raise AssertionError(
                    "write tool result was not persisted: "
                    f"{tool_call_id}, history={history}"
                )
            _wait_for_rest_message(
                azents_public_server_url,
                token,
                session_id,
                _PREPARED_RESPONSE,
            )
            break
        else:
            raise AssertionError(
                "runtime did not become ready for file lifecycle prepare step: "
                f"{last_transient_error}"
            )

        journal = ""
        last_present_debug: object | None = None
        for attempt, (message, tool_call_id) in enumerate(_PRESENT_ATTEMPTS, start=1):
            _run_message(
                public_api_client=public_api_client,
                public_url=azents_public_server_url,
                access_token=token,
                session_id=session_id,
                agent_id=agent_id,
                message=message,
            )
            transient_error = _transient_runtime_error_seen(
                azents_public_server_url,
                token,
                session_id,
                tool_call_id,
            )
            if transient_error is not None:
                last_transient_error = transient_error
                time.sleep(float(attempt * 5))
                continue
            if not _tool_call_succeeded(
                azents_public_server_url,
                token,
                session_id,
                tool_call_id,
            ):
                history = _tool_history_debug(
                    azents_public_server_url,
                    token,
                    session_id,
                )
                raise AssertionError(
                    "present_file tool result was not persisted: "
                    f"{tool_call_id}, history={history}"
                )
            _wait_for_rest_message(
                azents_public_server_url,
                token,
                session_id,
                _PRESENTED_RESPONSE,
            )
            present_result = _wait_for_tool_result(
                azents_public_server_url,
                token,
                session_id,
                tool_call_id,
            )
            if present_result is None:
                last_present_debug = _tool_history_debug(
                    azents_public_server_url,
                    token,
                    session_id,
                )
                time.sleep(float(attempt * 2))
                continue
            if not _tool_result_has_present_file_attachment(present_result):
                last_present_debug = {
                    "tool_result": present_result,
                    "tool_history": _tool_history_debug(
                        azents_public_server_url,
                        token,
                        session_id,
                    ),
                }
                time.sleep(float(attempt * 2))
                continue
            try:
                journal = _wait_for_attachment_metadata_journal(
                    mock_openai_url,
                    timeout=60,
                )
            except TimeoutError as exc:
                last_present_debug = {
                    "error": str(exc)[-4000:],
                    "tool_result": present_result,
                    "tool_history": _tool_history_debug(
                        azents_public_server_url,
                        token,
                        session_id,
                    ),
                }
                time.sleep(float(attempt * 2))
                continue
            break
        else:
            raise AssertionError(
                "present_file attachment metadata did not reach the model request: "
                f"transient_error={last_transient_error}, debug={last_present_debug}"
            )

        assert f"Attachment: {_FILE_NAME}" in journal
        assert _has_exchange_file_location_uri(journal)
        # present_file t preview metadata t t t t. t rich file
        # bytes/data part t model requestt t t t.
        assert "file_data" not in journal
        assert "input_file" not in journal
        assert "input_image" not in journal
        assert "\\u0000" not in journal
        assert _FILE_PREVIEW_MARKER in journal
