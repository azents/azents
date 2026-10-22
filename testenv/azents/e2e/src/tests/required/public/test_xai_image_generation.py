"""xAI client-executed image generation product-path E2E coverage."""

import hashlib
import json
import time
from collections.abc import Callable
from typing import Annotated, Literal, NamedTuple

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_response import AgentResponse
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.chat_event_response import ChatEventResponse
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.llm_provider_integration_update_request import (
    LLMProviderIntegrationUpdateRequest,
)
from azentspublicclient.models.model_catalog_entry_list_response import (
    ModelCatalogEntryListResponse,
)
from azentspublicclient.models.model_catalog_entry_response import (
    ModelCatalogEntryResponse,
)
from azentspublicclient.models.secrets import Secrets
from pydantic import BaseModel, Field, JsonValue, StrictInt, StrictStr, TypeAdapter

from support.consts import REPOSITORY_ROOT
from support.exchange_download import download_fixture_exchange_file
from support.oauth_connections import connect_xai_oauth
from support.observations import (
    ExtensionObservation,
    ProxyToolObservation,
    ToolResultObservation,
    decode_history_page,
)
from support.utils import authenticate_user, unique, wait_until
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
    list_history,
)


class _XaiAgentFixture(NamedTuple):
    """Field-named result for ``_setup_xai_agent``."""

    access_token: str
    agent_id: str
    session_id: str


class _ImageGenerationJournals(NamedTuple):
    """Field-named result for ``_run_success_scenario``."""

    imagine: list[dict[str, object]]
    oauth: list[dict[str, object]]


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


class _FunctionDeclaration(ExtensionObservation):
    name: StrictStr | None = None


class _ToolDeclaration(ProxyToolObservation):
    function: _FunctionDeclaration | None = None


class _ModelRequestObservation(ExtensionObservation):
    tools: list[_ToolDeclaration] = Field(default_factory=list)


class _TextPart(ExtensionObservation):
    type: Literal["text"]
    text: StrictStr


class _FilePart(ExtensionObservation):
    type: Literal["file"]
    model_file_id: StrictStr
    kind: StrictStr | None = None


class _AttachmentPart(ExtensionObservation):
    type: Literal["attachment"]
    attachment_id: StrictStr
    media_type: StrictStr
    size: StrictInt
    availability: Literal["available", "expired", "unavailable"]


type _ImageOutput = Annotated[
    _TextPart | _FilePart | _AttachmentPart, Field(discriminator="type")
]


class _ImageToolResult(ExtensionObservation):
    name: StrictStr | None = None
    status: StrictStr | None = None
    output: list[_ImageOutput]


class _AssistantPayload(ExtensionObservation):
    content: JsonValue = None


_MODEL_REQUESTS = TypeAdapter(list[_ModelRequestObservation])


def _headers(token: str) -> dict[str, str]:
    """Build bearer headers."""
    return {"Authorization": f"Bearer {token}"}


def _response_model[T: BaseModel](response: requests.Response, *, model: type[T]) -> T:
    """Validate the generated operation contract at the HTTP ingress."""
    response.raise_for_status()
    return model.model_validate(response.json())


def _journal(proxy_url: str, path: str) -> list[dict[str, object]]:
    """Return one sanitized deterministic proxy journal."""
    response = requests.get(f"{proxy_url}{path}", timeout=10)
    response.raise_for_status()
    return _JSON_OBJECT_LIST.validate_python(response.json())


def _clear_journals(proxy_url: str) -> None:
    """Clear deterministic model, Imagine, and OAuth journals."""
    for path in (_MODEL_JOURNAL_PATH, _IMAGINE_JOURNAL_PATH, _OAUTH_JOURNAL_PATH):
        requests.delete(f"{proxy_url}{path}", timeout=10).raise_for_status()


def _wait_for_catalog_attempt_completion(
    *,
    server_url: str,
    token: str,
    handle: str,
    integration_id: str,
) -> None:
    """Wait until the automatic OAuth catalog attempt reaches a terminal state."""
    entries_url = (
        f"{server_url}/llm-provider-integration/v1/workspaces/{handle}/"
        f"llm-provider-integrations/{integration_id}/catalog-entries"
    )

    def sync_completed() -> bool:
        response = requests.get(entries_url, headers=_headers(token), timeout=10)
        if response.status_code == 404:
            return False
        latest_sync = _response_model(
            response, model=ModelCatalogEntryListResponse
        ).latest_sync
        if latest_sync is None:
            return False
        return latest_sync.status in {"failed", "succeeded"}

    wait_until(
        sync_completed,
        timeout=10,
        interval=0.2,
        message="Initial xAI OAuth catalog sync did not complete",
    )


def _setup_xai_agent(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
    proxy_url: str,
    provider: LLMProvider,
    enabled: bool,
    access_token: str,
    refresh_token: str | None,
) -> _XaiAgentFixture:
    """Create a Runtime-free xAI Agent for the provider/storage-only journey."""
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
    integration_name = "__testenv_model_listing:deterministic-model-settings"
    if provider == LLMProvider.XAI:
        integration = LLMProviderIntegrationV1Api(
            public_api_client
        ).llm_provider_integration_v1_create_integration(
            handle=handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=provider,
                name=integration_name,
                secrets=Secrets(ApiKeySecrets(api_key=access_token)),
                config=None,
            ),
            _headers=_headers(token),
        )
        integration_id = integration.id
    else:
        if refresh_token is None:
            raise ValueError("xAI OAuth refresh token is required")
        integration_id = connect_xai_oauth(
            public_api_client=public_api_client,
            proxy_url=proxy_url,
            handle=handle,
            token=token,
            scenario=f"test-xai-image-{uniq}",
            access_token=access_token,
            refresh_token=refresh_token,
            name=integration_name,
            enabled=False,
        )
        _wait_for_catalog_attempt_completion(
            server_url=server_url,
            token=token,
            handle=handle,
            integration_id=integration_id,
        )
        LLMProviderIntegrationV1Api(
            public_api_client
        ).llm_provider_integration_v1_update_integration(
            integration_id=integration_id,
            handle=handle,
            llm_provider_integration_update_request=LLMProviderIntegrationUpdateRequest(
                enabled=True
            ),
            _headers=_headers(token),
        )
    entries_url = (
        f"{server_url}/llm-provider-integration/v1/workspaces/{handle}/"
        f"llm-provider-integrations/{integration_id}/catalog-entries"
    )
    quality_identifier = "grok-4"
    fast_identifier = "grok-4-fast"

    def populated_entries() -> list[ModelCatalogEntryResponse] | None:
        response = requests.get(entries_url, headers=_headers(token), timeout=10)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        entries = _response_model(response, model=ModelCatalogEntryListResponse).entries
        identifiers = {entry.provider_model_identifier for entry in entries}
        if {quality_identifier, fast_identifier}.issubset(identifiers):
            return entries
        return None

    entries = wait_until(
        populated_entries,
        timeout=10,
        interval=0.2,
        message="Deterministic xAI catalog entries did not become readable",
    )
    assert entries is not None
    by_identifier = {entry.provider_model_identifier: entry for entry in entries}

    def selection(identifier: str) -> dict[str, str]:
        model_identifier = by_identifier[identifier].provider_model_identifier
        if not isinstance(model_identifier, str):
            raise AssertionError("xAI catalog entry is missing its model identifier.")
        return {
            "llm_provider_integration_id": integration_id,
            "model_identifier": model_identifier,
        }

    image_builtin_tools: list[dict[str, str]] = (
        [{"name": "image_generation"}] if enabled else []
    )
    no_builtin_tools: list[dict[str, str]] = []
    created = _response_model(
        requests.post(
            f"{server_url}/agent/v1/workspaces/{handle}/agents",
            headers={**_headers(token), "Content-Type": "application/json"},
            json={
                "name": "xAI Image Generation QA Agent",
                "type": "public",
                "selectable_model_options": [
                    {
                        "label": "Quality",
                        "candidates": [
                            {
                                "model_selection": selection(quality_identifier),
                                "settings": {
                                    "context_window_tokens": 96_000,
                                    "max_output_tokens": 12_000,
                                    "builtin_tools": image_builtin_tools,
                                },
                            }
                        ],
                        "subagent_enabled": False,
                        "subagent_guidance": "Use the selected image capability.",
                    },
                    {
                        "label": "Fast",
                        "candidates": [
                            {
                                "model_selection": selection(fast_identifier),
                                "settings": {
                                    "context_window_tokens": 32_000,
                                    "max_output_tokens": 4_000,
                                    "builtin_tools": no_builtin_tools,
                                },
                            }
                        ],
                        "subagent_enabled": False,
                        "subagent_guidance": "Use for lightweight follow-up.",
                    },
                ],
                "main_model_label": "Quality",
                "lightweight_model_label": "Fast",
                "runtime_profile_id": None,
            },
            timeout=10,
        ),
        model=AgentResponse,
    )
    assert created.runtime_capability.value == "none"
    agent_id = created.id
    session = _response_model(
        requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/team-primary-session",
            headers=_headers(token),
            timeout=10,
        ),
        model=AgentSessionResponse,
    )
    session_id = session.id
    return _XaiAgentFixture(
        access_token=token,
        agent_id=agent_id,
        session_id=session_id,
    )


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
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    response.raise_for_status()


def _assistant_content(event: ChatEventResponse) -> str | None:
    """Return plain assistant content from one history event."""
    if event.kind != "assistant_message":
        return None
    payload = _AssistantPayload.model_validate(event.payload)
    content = payload.content
    return content if isinstance(content, str) else None


def _wait_for_history(
    *,
    server_url: str,
    token: str,
    session_id: str,
    predicate: Callable[[ChatEventResponse], bool],
    timeout: float = 120,
) -> ChatEventResponse:
    """Poll history until the supplied event predicate succeeds."""
    deadline = time.monotonic() + timeout
    latest: dict[str, object] | None = None
    while time.monotonic() < deadline:
        latest = list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        for event in decode_history_page(latest).items:
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
        payload = AgentSessionResponse.model_validate(response.json())
        last_state = payload.run_state
        if last_state == "idle":
            return
        time.sleep(0.2)
    raise TimeoutError(
        f"xAI image-generation session did not become idle: {last_state!r}"
    )


def _client_result(history: dict[str, object]) -> _ImageToolResult | None:
    """Validate interpreted client-result fields after the history envelope."""
    for event in decode_history_page(history).items:
        if event.kind != "client_tool_result":
            continue
        identity = ToolResultObservation.model_validate(event.payload)
        if identity.name == "image_generation":
            return _ImageToolResult.model_validate(event.payload)
    return None


def _tool_name(tool: _ToolDeclaration) -> str | None:
    """Project native flat or nested function declaration identity."""
    return (
        tool.name
        if tool.name is not None
        else (tool.function.name if tool.function is not None else None)
    )


def _assert_image_tool_exposure(*, proxy_url: str, expected: bool) -> None:
    """Verify xAI model requests advertise the client image tool as configured."""
    response = requests.get(f"{proxy_url}{_MODEL_JOURNAL_PATH}", timeout=10)
    response.raise_for_status()
    requests_ = _MODEL_REQUESTS.validate_python(response.json())
    assert requests_, "No captured xAI model request was observed"
    tool_names: set[str | None] = set()
    for request in requests_:
        tool_names.update(_tool_name(tool) for tool in request.tools)
    assert ("image_generation" in tool_names) is expected, tool_names


def _assert_success_result(
    *,
    server_url: str,
    storage_endpoint_url: str,
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
    result = _client_result(history)
    assert result is not None, serialized
    payload = result
    assert payload.status == "completed"
    output = payload.output
    assert len(output) == 2
    assert isinstance(output[0], _FilePart)
    assert output[0].kind == "image"
    assert isinstance(output[0].model_file_id, str)
    attachment = output[1]
    assert isinstance(attachment, _AttachmentPart)
    assert attachment.type == "attachment"
    assert attachment.availability == "available"
    assert attachment.media_type == "image/png"
    assert attachment.size == len(_IMAGE_BYTES)
    attachment_id = attachment.attachment_id
    assert isinstance(attachment_id, str)
    download = download_fixture_exchange_file(
        server_url=server_url,
        access_token=token,
        attachment_id=attachment_id,
        storage_endpoint_url=storage_endpoint_url,
    )
    assert hashlib.sha256(download).hexdigest() == _IMAGE_SHA256
    assert download == _IMAGE_BYTES


def _run_success_scenario(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
    storage_endpoint_url: str,
    proxy_url: str,
    provider: LLMProvider,
    access_token: str,
    refresh_token: str | None,
    message: str,
    completed_message: str,
) -> _ImageGenerationJournals:
    """Run one successful xAI image-generation scenario."""
    _clear_journals(proxy_url)
    token, agent_id, session_id = _setup_xai_agent(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=server_url,
        proxy_url=proxy_url,
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
        storage_endpoint_url=storage_endpoint_url,
        token=token,
        history=history,
        scenario_secrets=scenario_secrets,
    )
    _assert_image_tool_exposure(proxy_url=proxy_url, expected=True)
    return _ImageGenerationJournals(
        imagine=_journal(proxy_url, _IMAGINE_JOURNAL_PATH),
        oauth=_journal(proxy_url, _OAUTH_JOURNAL_PATH),
    )


class TestXaiImageGeneration:
    """Validate client Imagine execution, refresh, storage, and tool exposure."""

    def test_api_key_materializes_client_image_result(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_browser_s3_endpoint_url: str,
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
            storage_endpoint_url=azents_browser_s3_endpoint_url,
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
        azents_browser_s3_endpoint_url: str,
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
            storage_endpoint_url=azents_browser_s3_endpoint_url,
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
        azents_browser_s3_endpoint_url: str,
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
            storage_endpoint_url=azents_browser_s3_endpoint_url,
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
            proxy_url=openai_proxy_url,
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
        result = _client_result(history)
        assert result is not None
        payload = result
        assert payload.status == "failed"
        assert [
            part.model_dump(mode="json", exclude_unset=True) for part in payload.output
        ] == [
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
            proxy_url=openai_proxy_url,
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
        assert _client_result(history) is None
        assert _journal(openai_proxy_url, _IMAGINE_JOURNAL_PATH) == []
        _assert_image_tool_exposure(proxy_url=openai_proxy_url, expected=False)
