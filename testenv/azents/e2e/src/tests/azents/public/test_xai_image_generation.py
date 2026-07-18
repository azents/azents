"""xAI client-executed image generation product-path E2E coverage."""

import datetime
import hashlib
import json
import time
from collections.abc import Callable
from typing import cast

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.llm_provider_integration_create_request_config import (
    LLMProviderIntegrationCreateRequestConfig,
)
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.xai_o_auth_config import XaiOAuthConfig
from azentspublicclient.models.xai_o_auth_secrets import XaiOAuthSecrets
from pydantic import TypeAdapter

from support.consts import REPOSITORY_ROOT
from support.utils import authenticate_user, unique, wait_until
from tests.azents.public.test_agent_execution_persistence import (
    auth_headers,
    history_events,
    json_object_list_payload,
    json_object_payload,
    list_history,
)

_API_KEY_MESSAGE = "xAI API-key image generation"
_OAUTH_MESSAGE = "xAI OAuth image generation"
_OAUTH_REFRESH_MESSAGE = "xAI OAuth image generation after 401"
_OAUTH_REJECTED_MESSAGE = "xAI OAuth image generation repeated 401"
_DISABLED_MESSAGE = "xAI image generation disabled"
_API_KEY_COMPLETED = "XAI_API_KEY_IMAGE_GENERATION_COMPLETED"
_OAUTH_COMPLETED = "XAI_OAUTH_IMAGE_GENERATION_COMPLETED"
_OAUTH_REFRESH_COMPLETED = "XAI_OAUTH_REFRESH_IMAGE_GENERATION_COMPLETED"
_OAUTH_REJECTED_COMPLETED = "XAI_OAUTH_REJECTED_IMAGE_GENERATION_COMPLETED"
_DISABLED_COMPLETED = "XAI_IMAGE_GENERATION_DISABLED_COMPLETED"
_MODEL_JOURNAL_PATH = "/v1/_image_generation_requests"
_IMAGINE_JOURNAL_PATH = "/v1/_xai_imagine_requests"
_OAUTH_JOURNAL_PATH = "/v1/_xai_oauth_requests"
_IMAGE_PATH = (
    REPOSITORY_ROOT
    / "testenv/azents/e2e/src/support/fixtures/provider-image-generation.png"
)
_IMAGE_BYTES = _IMAGE_PATH.read_bytes()
_IMAGE_SHA256 = hashlib.sha256(_IMAGE_BYTES).hexdigest()
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


def _headers(token: str) -> dict[str, str]:
    """Build bearer headers."""
    return {"Authorization": f"Bearer {token}"}


def _response_object(response: requests.Response) -> dict[str, object]:
    """Validate one HTTP JSON response."""
    response.raise_for_status()
    return json_object_payload(response.json(), label="HTTP response")


def _journal(proxy_url: str, path: str) -> list[dict[str, object]]:
    """Return one sanitized deterministic proxy journal."""
    response = requests.get(f"{proxy_url}{path}", timeout=10)
    response.raise_for_status()
    return _JSON_OBJECT_LIST.validate_python(response.json())


def _clear_journals(proxy_url: str) -> None:
    """Clear deterministic model, Imagine, and OAuth journals."""
    for path in (_MODEL_JOURNAL_PATH, _IMAGINE_JOURNAL_PATH, _OAUTH_JOURNAL_PATH):
        requests.delete(f"{proxy_url}{path}", timeout=10).raise_for_status()


def _setup_xai_agent(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
    provider: LLMProvider,
    enabled: bool,
    access_token: str,
    refresh_token: str | None,
) -> tuple[str, str, str]:
    """Create one xAI integration, Agent, and primary session via public APIs."""
    uniq = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"xai-image-generation-{uniq}@example.com",
    )
    handle = f"xai-image-generation-{uniq}"
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"xAI Image Generation QA {uniq}",
            workspace_handle=handle,
            owner_name=f"Owner {uniq}",
        ),
        _headers=_headers(token),
    )
    if provider == LLMProvider.XAI:
        secrets = Secrets(ApiKeySecrets(api_key=access_token))
        config = None
    else:
        if refresh_token is None:
            raise ValueError("xAI OAuth refresh token is required")
        secrets = Secrets(
            XaiOAuthSecrets(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(hours=2),
            )
        )
        config = LLMProviderIntegrationCreateRequestConfig(
            XaiOAuthConfig(
                connection_method="device",
                status="connected",
                connected_at=datetime.datetime.now(datetime.UTC),
            )
        )
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=provider,
            name="__testenv_model_listing:deterministic-model-settings",
            secrets=secrets,
            config=config,
        ),
        _headers=_headers(token),
    )
    entries_url = (
        f"{server_url}/llm-provider-integration/v1/workspaces/{handle}/"
        f"llm-provider-integrations/{integration.id}/catalog-entries"
    )

    def populated_entries() -> list[dict[str, object]] | None:
        response = requests.get(entries_url, headers=_headers(token), timeout=10)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        entries = json_object_list_payload(
            _response_object(response).get("entries"),
            label="xAI catalog entries",
        )
        identifiers = {entry.get("provider_model_identifier") for entry in entries}
        if {"grok-4", "grok-4-fast"}.issubset(identifiers):
            return entries
        return None

    entries = wait_until(
        populated_entries,
        timeout=10,
        interval=0.2,
        message="Deterministic xAI catalog entries did not become readable",
    )
    assert entries is not None
    by_identifier = {
        cast(str, entry["provider_model_identifier"]): entry for entry in entries
    }

    def selection(identifier: str) -> dict[str, str]:
        return {
            "llm_provider_integration_id": integration.id,
            "model_identifier": cast(
                str,
                by_identifier[identifier]["provider_model_identifier"],
            ),
        }

    image_builtin_tools: list[dict[str, str]] = (
        [{"name": "image_generation"}] if enabled else []
    )
    no_builtin_tools: list[dict[str, str]] = []
    created = _response_object(
        requests.post(
            f"{server_url}/agent/v1/workspaces/{handle}/agents",
            headers={**_headers(token), "Content-Type": "application/json"},
            json={
                "name": "xAI Image Generation QA Agent",
                "type": "public",
                "selectable_model_options": [
                    {
                        "label": "Quality",
                        "model_selection": selection("grok-4"),
                        "settings": {
                            "context_window_tokens": 96_000,
                            "max_output_tokens": 12_000,
                            "builtin_tools": image_builtin_tools,
                            "subagent_enabled": False,
                            "subagent_guidance": "Use the selected image capability.",
                        },
                    },
                    {
                        "label": "Fast",
                        "model_selection": selection("grok-4-fast"),
                        "settings": {
                            "context_window_tokens": 32_000,
                            "max_output_tokens": 4_000,
                            "builtin_tools": no_builtin_tools,
                            "subagent_enabled": False,
                            "subagent_guidance": "Use for lightweight follow-up.",
                        },
                    },
                ],
                "main_model_label": "Quality",
                "lightweight_model_label": "Fast",
            },
            timeout=10,
        )
    )
    agent_id = created.get("id")
    if not isinstance(agent_id, str):
        raise AssertionError(f"Agent response did not include id: {created!r}")
    session = _response_object(
        requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/team-primary-session",
            headers=_headers(token),
            timeout=10,
        )
    )
    session_id = session.get("id")
    if not isinstance(session_id, str):
        raise AssertionError(f"Session response did not include id: {session!r}")
    return token, agent_id, session_id


def _submit(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    message: str,
) -> None:
    """Submit one Quality-profile turn through the public API."""
    response = requests.post(
        f"{server_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"xai-image-generation-{unique()}",
            "message": message,
            "inference_profile": {
                "model_target_label": "Quality",
                "reasoning_effort": None,
            },
        },
        timeout=10,
    )
    response.raise_for_status()


def _assistant_content(event: dict[str, object]) -> str | None:
    """Return plain assistant content from one history event."""
    if event.get("kind") != "assistant_message":
        return None
    payload = json_object_payload(event.get("payload"), label="assistant payload")
    content = payload.get("content")
    return content if isinstance(content, str) else None


def _wait_for_history(
    *,
    server_url: str,
    token: str,
    session_id: str,
    predicate: Callable[[dict[str, object]], bool],
    timeout: float = 120,
) -> dict[str, object]:
    """Poll history until the supplied event predicate succeeds."""
    deadline = time.monotonic() + timeout
    latest: dict[str, object] | None = None
    while time.monotonic() < deadline:
        latest = list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        for event in history_events(latest):
            if predicate(event):
                return event
        time.sleep(0.2)
    raise TimeoutError(
        f"expected xAI image-generation history was not observed: {latest!r}"
    )


def _wait_for_idle(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    timeout: float = 120,
) -> None:
    """Wait for the submitted turn to leave the running state."""
    deadline = time.monotonic() + timeout
    last_state: object = None
    while time.monotonic() < deadline:
        response = requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}",
            headers=auth_headers(token),
            timeout=10,
        )
        response.raise_for_status()
        payload = json_object_payload(response.json(), label="session response")
        last_state = payload.get("run_state")
        if last_state == "idle":
            return
        time.sleep(0.2)
    raise TimeoutError(
        f"xAI image-generation session did not become idle: {last_state!r}"
    )


def _client_result(events: list[dict[str, object]]) -> dict[str, object] | None:
    """Return the image-generation client tool result."""
    for event in events:
        if event.get("kind") != "client_tool_result":
            continue
        payload = json_object_payload(event.get("payload"), label="client result")
        if payload.get("name") == "image_generation":
            return event
    return None


def _tool_name(tool: dict[str, object]) -> str | None:
    """Return a tool name from Responses or Chat Completions syntax."""
    name = tool.get("name")
    if isinstance(name, str):
        return name
    function = tool.get("function")
    if isinstance(function, dict):
        nested_name = cast(dict[str, object], function).get("name")
        return nested_name if isinstance(nested_name, str) else None
    return None


def _assert_image_tool_exposure(*, proxy_url: str, expected: bool) -> None:
    """Verify xAI model requests advertise the client image tool as configured."""
    requests_ = _journal(proxy_url, _MODEL_JOURNAL_PATH)
    assert requests_, "No captured xAI model request was observed"
    tool_names: set[str | None] = set()
    for index, request in enumerate(requests_):
        tools = json_object_list_payload(
            request.get("tools", []),
            label=f"xAI model request {index} tools",
        )
        tool_names.update(_tool_name(tool) for tool in tools)
    assert ("image_generation" in tool_names) is expected, tool_names


def _assert_success_result(
    *,
    server_url: str,
    token: str,
    history: dict[str, object],
    scenario_secrets: tuple[str, ...],
) -> None:
    """Verify the durable Exchange and ModelFile-backed client result."""
    serialized = json.dumps(history, ensure_ascii=False, sort_keys=True)
    for secret in (
        "test-xai-oauth-refreshed",
        *scenario_secrets,
    ):
        assert secret not in serialized
    result = _client_result(history_events(history))
    assert result is not None, serialized
    payload = json_object_payload(result.get("payload"), label="client result payload")
    assert payload.get("status") == "completed"
    output = json_object_list_payload(
        payload.get("output"),
        label="client result output",
    )
    attachments = json_object_list_payload(
        payload.get("attachments"),
        label="client result attachments",
    )
    assert len(output) == 1
    assert output[0].get("kind") == "image"
    assert isinstance(output[0].get("model_file_id"), str)
    assert len(attachments) == 1
    attachment = attachments[0]
    assert attachment.get("availability") == "available"
    assert attachment.get("media_type") == "image/png"
    assert attachment.get("size") == len(_IMAGE_BYTES)
    attachment_id = attachment.get("attachment_id")
    assert isinstance(attachment_id, str)
    download = requests.get(
        f"{server_url}/chat/v1/exchange-files/{attachment_id}/download",
        headers=auth_headers(token),
        timeout=10,
    )
    download.raise_for_status()
    assert hashlib.sha256(download.content).hexdigest() == _IMAGE_SHA256
    assert download.content == _IMAGE_BYTES


def _run_success_scenario(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
    proxy_url: str,
    provider: LLMProvider,
    access_token: str,
    refresh_token: str | None,
    message: str,
    completed_message: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Run one successful xAI image-generation scenario."""
    _clear_journals(proxy_url)
    token, agent_id, session_id = _setup_xai_agent(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=server_url,
        provider=provider,
        enabled=True,
        access_token=access_token,
        refresh_token=refresh_token,
    )
    _submit(
        server_url=server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
        message=message,
    )
    _wait_for_history(
        server_url=server_url,
        token=token,
        session_id=session_id,
        predicate=lambda event: _assistant_content(event) == completed_message,
    )
    _wait_for_idle(
        server_url=server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
    )
    history = list_history(server_url=server_url, token=token, session_id=session_id)
    scenario_secrets = (access_token,) + (
        (refresh_token,) if refresh_token is not None else ()
    )
    _assert_success_result(
        server_url=server_url,
        token=token,
        history=history,
        scenario_secrets=scenario_secrets,
    )
    _assert_image_tool_exposure(proxy_url=proxy_url, expected=True)
    return (
        _journal(proxy_url, _IMAGINE_JOURNAL_PATH),
        _journal(proxy_url, _OAUTH_JOURNAL_PATH),
    )


class TestXaiImageGeneration:
    """Validate client Imagine execution, refresh, storage, and tool exposure."""

    def test_api_key_materializes_client_image_result(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        openai_proxy_url: str,
    ) -> None:
        """xAI API-key execution creates one durable dual-resource result."""
        del azents_engine_worker_container
        imagine, oauth = _run_success_scenario(
            public_api_client=public_api_client,
            admin_api_client=admin_api_client,
            server_url=azents_public_server_url,
            proxy_url=openai_proxy_url,
            provider=LLMProvider.XAI,
            access_token="test-xai-api-key",
            refresh_token=None,
            message=_API_KEY_MESSAGE,
            completed_message=_API_KEY_COMPLETED,
        )
        assert imagine == [
            {
                "prompt": "A deterministic xAI API-key aurora",
                "credential": "api_key",
                "status": 200,
            }
        ]
        assert oauth == []

    def test_oauth_materializes_without_refresh(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        openai_proxy_url: str,
    ) -> None:
        """A valid xAI OAuth access token reaches Imagine without refresh."""
        del azents_engine_worker_container
        imagine, oauth = _run_success_scenario(
            public_api_client=public_api_client,
            admin_api_client=admin_api_client,
            server_url=azents_public_server_url,
            proxy_url=openai_proxy_url,
            provider=LLMProvider.XAI_OAUTH,
            access_token="test-xai-oauth-token",
            refresh_token="test-xai-refresh-unused",
            message=_OAUTH_MESSAGE,
            completed_message=_OAUTH_COMPLETED,
        )
        assert imagine == [
            {
                "prompt": "A deterministic xAI OAuth aurora",
                "credential": "oauth",
                "status": 200,
            }
        ]
        assert oauth == []

    def test_oauth_refreshes_once_after_imagine_401(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        openai_proxy_url: str,
    ) -> None:
        """The first Imagine 401 refreshes the selected OAuth integration once."""
        del azents_engine_worker_container
        imagine, oauth = _run_success_scenario(
            public_api_client=public_api_client,
            admin_api_client=admin_api_client,
            server_url=azents_public_server_url,
            proxy_url=openai_proxy_url,
            provider=LLMProvider.XAI_OAUTH,
            access_token="test-xai-oauth-refresh-initial",
            refresh_token="test-xai-refresh-success",
            message=_OAUTH_REFRESH_MESSAGE,
            completed_message=_OAUTH_REFRESH_COMPLETED,
        )
        assert imagine == [
            {
                "prompt": "A deterministic xAI OAuth refresh aurora",
                "credential": "oauth_initial",
                "status": 401,
            },
            {
                "prompt": "A deterministic xAI OAuth refresh aurora",
                "credential": "oauth_refreshed",
                "status": 200,
            },
        ]
        assert oauth == [{"refresh_case": "success"}]

    def test_oauth_repeated_401_returns_sanitized_failure(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        openai_proxy_url: str,
    ) -> None:
        """A second Imagine 401 fails once with reconnect guidance and no files."""
        del azents_engine_worker_container
        _clear_journals(openai_proxy_url)
        token, agent_id, session_id = _setup_xai_agent(
            public_api_client=public_api_client,
            admin_api_client=admin_api_client,
            server_url=azents_public_server_url,
            provider=LLMProvider.XAI_OAUTH,
            enabled=True,
            access_token="test-xai-oauth-rejected-initial",
            refresh_token="test-xai-refresh-rejected",
        )
        _submit(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_OAUTH_REJECTED_MESSAGE,
        )
        _wait_for_history(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            predicate=lambda event: (
                _assistant_content(event) == _OAUTH_REJECTED_COMPLETED
            ),
        )
        _wait_for_idle(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        history = list_history(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
        )
        serialized = json.dumps(history, ensure_ascii=False, sort_keys=True)
        assert "xAI OAuth reconnect is required for image generation." in serialized
        assert "test-xai-oauth-rejected-initial" not in serialized
        assert "test-xai-oauth-rejected-refreshed" not in serialized
        assert "test-xai-refresh-rejected" not in serialized
        result = _client_result(history_events(history))
        assert result is not None
        payload = json_object_payload(
            result.get("payload"),
            label="failed client result",
        )
        assert payload.get("status") == "failed"
        assert payload.get("attachments") == []
        assert payload.get("output") == [
            {
                "type": "text",
                "text": "xAI OAuth reconnect is required for image generation.",
            }
        ]
        assert _journal(openai_proxy_url, _IMAGINE_JOURNAL_PATH) == [
            {
                "prompt": "A deterministic rejected xAI OAuth aurora",
                "credential": "oauth_rejected_initial",
                "status": 401,
            },
            {
                "prompt": "A deterministic rejected xAI OAuth aurora",
                "credential": "oauth_rejected_refreshed",
                "status": 401,
            },
        ]
        assert _journal(openai_proxy_url, _OAUTH_JOURNAL_PATH) == [
            {"refresh_case": "rejected"}
        ]

    def test_disabled_flag_omits_client_tool_and_imagine_request(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        openai_proxy_url: str,
    ) -> None:
        """An xAI option without the flag exposes no client image tool."""
        del azents_engine_worker_container
        _clear_journals(openai_proxy_url)
        token, agent_id, session_id = _setup_xai_agent(
            public_api_client=public_api_client,
            admin_api_client=admin_api_client,
            server_url=azents_public_server_url,
            provider=LLMProvider.XAI,
            enabled=False,
            access_token="test-xai-api-key",
            refresh_token=None,
        )
        _submit(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_DISABLED_MESSAGE,
        )
        _wait_for_history(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            predicate=lambda event: _assistant_content(event) == _DISABLED_COMPLETED,
        )
        _wait_for_idle(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        history = list_history(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
        )
        assert _client_result(history_events(history)) is None
        assert _journal(openai_proxy_url, _IMAGINE_JOURNAL_PATH) == []
        _assert_image_tool_exposure(proxy_url=openai_proxy_url, expected=False)
