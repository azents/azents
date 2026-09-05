"""Provider-visible model listing adapter tests."""

import datetime
from types import SimpleNamespace

import httpx
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, InvalidRegionError
from google.auth.exceptions import TransportError as GoogleTransportError
from pydantic import TypeAdapter, ValidationError

from azents.core.chatgpt_oauth import (
    CHATGPT_MODEL_CATALOG_CLIENT_VERSION,
    CHATGPT_OAUTH_BACKEND_BASE_URL,
)
from azents.core.credentials import (
    ApiKeySecrets,
    ChatGPTOAuthConfig,
    ChatGPTOAuthSecrets,
    KimiOAuthConfig,
    KimiOAuthSecrets,
    XaiOAuthConfig,
    XaiOAuthSecrets,
)
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelModality, ModelReasoningEffort
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationWithSecrets,
)
from azents.services.model_listing import providers


def _openrouter_integration() -> LLMProviderIntegrationWithSecrets:
    now = datetime.datetime.now(datetime.UTC)
    return LLMProviderIntegrationWithSecrets(
        id="openrouter-integration-id",
        workspace_id="workspace-id",
        provider=LLMProvider.OPENROUTER,
        name="OpenRouter",
        config=None,
        enabled=True,
        created_at=now,
        updated_at=now,
        secrets=ApiKeySecrets(api_key="openrouter-test-key"),
    )


def _chatgpt_integration() -> LLMProviderIntegrationWithSecrets:
    now = datetime.datetime.now(datetime.UTC)
    return LLMProviderIntegrationWithSecrets(
        id="integration-id",
        workspace_id="workspace-id",
        provider=LLMProvider.CHATGPT_OAUTH,
        name="ChatGPT Subscription",
        config=ChatGPTOAuthConfig(
            account_id="account-id",
            connection_method="device",
            status="connected",
        ),
        enabled=True,
        created_at=now,
        updated_at=now,
        secrets=ChatGPTOAuthSecrets(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=now + datetime.timedelta(hours=1),
        ),
    )


def _kimi_integration() -> LLMProviderIntegrationWithSecrets:
    """Build one connected Kimi integration for listing tests."""
    now = datetime.datetime.now(datetime.UTC)
    return LLMProviderIntegrationWithSecrets(
        id="kimi-integration-id",
        workspace_id="workspace-id",
        provider=LLMProvider.KIMI_OAUTH,
        name="Kimi subscription",
        config=KimiOAuthConfig(
            connection_method="device",
            status="connected",
            connected_at=now,
            last_refreshed_at=now,
            last_failed_at=None,
            last_failure_reason=None,
        ),
        enabled=True,
        created_at=now,
        updated_at=now,
        secrets=KimiOAuthSecrets(
            access_token="kimi-access-token",
            refresh_token="kimi-refresh-token",
            expires_at=now + datetime.timedelta(hours=1),
            device_id="kimi-device-id",
        ),
    )


def _xai_api_key_integration() -> LLMProviderIntegrationWithSecrets:
    """Build one xAI developer API integration."""
    now = datetime.datetime.now(datetime.UTC)
    return LLMProviderIntegrationWithSecrets(
        id="xai-integration-id",
        workspace_id="workspace-id",
        provider=LLMProvider.XAI,
        name="xAI API key",
        config=None,
        enabled=True,
        created_at=now,
        updated_at=now,
        secrets=ApiKeySecrets(api_key="xai-test-key"),
    )


def _xai_oauth_integration() -> LLMProviderIntegrationWithSecrets:
    """Build one connected xAI OAuth integration."""
    now = datetime.datetime.now(datetime.UTC)
    return LLMProviderIntegrationWithSecrets(
        id="xai-oauth-integration-id",
        workspace_id="workspace-id",
        provider=LLMProvider.XAI_OAUTH,
        name="xAI Grok OAuth",
        config=XaiOAuthConfig(
            account_id="xai-account-id",
            email="user@example.test",
            connection_method="device",
            status="connected",
            connected_at=now,
            last_refreshed_at=now,
        ),
        enabled=True,
        created_at=now,
        updated_at=now,
        secrets=XaiOAuthSecrets(
            access_token="xai-access-token",
            refresh_token="xai-refresh-token",
            expires_at=now + datetime.timedelta(hours=1),
        ),
    )


@pytest.mark.parametrize(
    ("code", "status_code", "blocked"),
    [
        ("AccessDeniedException", 403, True),
        ("UnrecognizedClientException", 401, True),
        ("ThrottlingException", 400, False),
        ("InternalServerException", 500, False),
    ],
)
def test_aws_failure_classification(
    code: str,
    status_code: int,
    blocked: bool,
) -> None:
    error = ClientError(
        {
            "Error": {"Code": code, "Message": "failure"},
            "ResponseMetadata": {
                "RequestId": "request-id",
                "HostId": "host-id",
                "HTTPStatusCode": status_code,
                "HTTPHeaders": {},
                "RetryAttempts": 0,
            },
        },
        "ListFoundationModels",
    )

    assert providers.automatic_retry_blocked_for_listing_error(error) is blocked


def test_aws_transport_and_configuration_failure_classification() -> None:
    transport_error = EndpointConnectionError(endpoint_url="https://bedrock.example")
    configuration_error = InvalidRegionError(region_name="invalid region")

    assert not providers.automatic_retry_blocked_for_listing_error(transport_error)
    assert providers.automatic_retry_blocked_for_listing_error(configuration_error)


@pytest.mark.parametrize(
    ("status_code", "blocked"),
    [(401, True), (403, True), (429, False), (500, False)],
)
def test_http_failure_classification(status_code: int, blocked: bool) -> None:
    request = httpx.Request("GET", "https://provider.example/models")
    response = httpx.Response(status_code, request=request)
    error = httpx.HTTPStatusError("failure", request=request, response=response)

    assert providers.automatic_retry_blocked_for_listing_error(error) is blocked


def test_google_auth_transport_failure_remains_retryable() -> None:
    error = GoogleTransportError("temporary token endpoint outage")

    assert not providers.automatic_retry_blocked_for_listing_error(error)


def test_invalid_provider_response_remains_retryable() -> None:
    with pytest.raises(ValidationError) as caught:
        TypeAdapter(dict[str, object]).validate_python(["not", "an", "object"])

    assert not providers.automatic_retry_blocked_for_listing_error(caught.value)
    assert not providers.automatic_retry_blocked_for_listing_error(
        providers.InvalidProviderResponseError("missing models")
    )


class _FakeXaiModels:
    async def list(self) -> SimpleNamespace:
        """Return one API-key-visible model."""
        return SimpleNamespace(
            data=[
                SimpleNamespace(
                    id="grok-4.7-api",
                    created=1_787_000_000,
                    owned_by="xai",
                )
            ]
        )


class _FakeXaiSdkClient:
    def __init__(self, *, api_key: str, base_url: str, timeout: float) -> None:
        assert api_key == "xai-test-key"
        assert base_url == providers.resolve_xai_api_base_url()
        assert timeout == 20.0
        self.models = _FakeXaiModels()

    async def __aenter__(self) -> "_FakeXaiSdkClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        del args


async def test_list_xai_api_key_models_uses_sdk_and_conservative_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the SDK boundary without inventing omitted capabilities."""
    monkeypatch.setattr(providers, "AsyncOpenAI", _FakeXaiSdkClient)

    result = await providers.list_xai_models_for_integration(_xai_api_key_integration())

    assert result.summary.source == "xai:developer_models"
    assert result.summary.returned_count == 1
    [candidate] = result.models
    assert candidate.model_identifier == "grok-4.7-api"
    assert candidate.model_developer == LLMModelDeveloper.XAI
    assert candidate.normalized_capabilities.modalities.input == [ModelModality.TEXT]
    assert candidate.normalized_capabilities.modalities.output == [ModelModality.TEXT]
    assert candidate.normalized_capabilities.tool_calling.supported is False
    assert candidate.normalized_capabilities.reasoning.supported is False
    assert candidate.normalized_capabilities.built_in_tools.supported == []
    assert candidate.source_metadata == {"created": 1_787_000_000}


class _FakeXaiOAuthAsyncClient:
    def __init__(self, *, timeout: float) -> None:
        assert timeout == 20.0

    async def __aenter__(self) -> "_FakeXaiOAuthAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
    ) -> httpx.Response:
        assert url == f"{providers.resolve_xai_usage_base_url()}/models"
        assert headers["Authorization"] == "Bearer xai-access-token"
        assert headers["x-userid"] == "xai-account-id"
        assert headers["X-XAI-Token-Auth"] == "xai-grok-cli"
        assert headers["x-grok-client-version"] == providers.XAI_MODELS_CLIENT_VERSION
        assert headers["x-grok-client-identifier"] == "grok-shell"
        assert headers["x-grok-client-mode"] == "interactive"
        return httpx.Response(
            status_code=200,
            request=httpx.Request("GET", url),
            json={
                "object": "list",
                "data": [
                    {
                        "id": "grok-4.6",
                        "model": "grok-4.6",
                        "name": "Grok 4.6",
                        "context_window": 500000,
                        "api_backend": "responses",
                        "supports_reasoning_effort": True,
                        "reasoning_efforts": [
                            {"id": "xhigh", "default": True},
                            {"id": "high", "default": True},
                            {"id": "medium"},
                            {"id": "low"},
                        ],
                        "supports_backend_search": True,
                        "auto_compact_threshold_percent": 90,
                        "compaction_at_tokens": True,
                        "show_model_fingerprint": True,
                        "provider_instructions": "must not be persisted",
                    },
                    {
                        "id": "grok-4.5",
                        "context_window": 500000,
                        "api_backend": "responses",
                        "supports_reasoning_effort": True,
                        "reasoning_efforts": [
                            {"value": "high"},
                            {"value": "medium"},
                            {"value": "low"},
                        ],
                        "supports_backend_search": True,
                    },
                ],
            },
        )


async def test_list_xai_oauth_models_projects_verified_account_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve provider-owned capabilities and discard unsafe unknown fields."""
    monkeypatch.setattr(httpx, "AsyncClient", _FakeXaiOAuthAsyncClient)

    result = await providers.list_xai_models_for_integration(_xai_oauth_integration())

    assert result.summary.source == "xai_oauth:grok_models"
    assert [model.model_identifier for model in result.models] == [
        "grok-4.6",
        "grok-4.5",
    ]
    current, previous = result.models
    assert current.normalized_capabilities.context_window.max_input_tokens == 500000
    assert current.normalized_capabilities.compatibility.responses_api is True
    assert current.normalized_capabilities.reasoning.effort_levels == [
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
        ModelReasoningEffort.XHIGH,
    ]
    assert current.normalized_capabilities.built_in_tools.supported == ["web_search"]
    assert current.source_metadata is not None
    assert "provider_instructions" not in current.source_metadata
    assert current.source_metadata["auto_compact_threshold_percent"] == 90
    assert previous.normalized_capabilities.reasoning.effort_levels == [
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    ]


class _RejectedXaiOAuthAsyncClient:
    def __init__(self, *, timeout: float) -> None:
        assert timeout == 20.0

    async def __aenter__(self) -> "_RejectedXaiOAuthAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
    ) -> httpx.Response:
        del headers
        return httpx.Response(
            status_code=403,
            request=httpx.Request("GET", url),
            json={"error": "token xai-access-token is not entitled"},
        )


async def test_xai_listing_failure_is_sanitized_and_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not persist provider bodies or credential values in listing errors."""
    monkeypatch.setattr(httpx, "AsyncClient", _RejectedXaiOAuthAsyncClient)

    with pytest.raises(providers.XaiListingProviderError) as caught:
        await providers.list_xai_models_for_integration(_xai_oauth_integration())

    assert caught.value.failure_code == "XaiEntitlementDenied"
    assert caught.value.automatic_retry_blocked is True
    assert str(caught.value) == "xAI model listing failed."
    assert caught.value.__cause__ is None


class _FakeAsyncClient:
    def __init__(self, *, timeout: float) -> None:
        assert timeout == 20.0

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def get(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> httpx.Response:
        assert url == f"{CHATGPT_OAUTH_BACKEND_BASE_URL}/models"
        assert params == {"client_version": CHATGPT_MODEL_CATALOG_CLIENT_VERSION}
        assert headers["Authorization"] == "Bearer access-token"
        assert headers["ChatGPT-Account-Id"] == "account-id"
        assert headers["originator"] == "azents"
        assert "version" not in headers
        return httpx.Response(
            status_code=200,
            request=httpx.Request("GET", url),
            json={
                "models": [
                    {
                        "slug": "gpt-6-astra",
                        "display_name": "GPT-6-Astra",
                        "visibility": "list",
                        "supported_in_api": True,
                        "context_window": 272000,
                        "max_context_window": 872000,
                        "input_modalities": ["text", "image"],
                        "supports_parallel_tool_calls": True,
                        "supports_reasoning_summaries": True,
                        "supported_reasoning_levels": [
                            {"effort": "low"},
                            {"effort": "medium"},
                            {"effort": "high"},
                            {"effort": "xhigh"},
                            {"effort": "max"},
                            {"effort": "ultra"},
                        ],
                        "minimal_client_version": "0.153.0",
                        "tool_mode": "code_mode_only",
                        "base_instructions": "provider-owned instructions",
                    },
                    {
                        "slug": "gpt-5.5-standard",
                        "display_name": "GPT-5.5 Standard",
                        "visibility": "list",
                        "supported_in_api": True,
                        "input_modalities": ["text"],
                        "supported_reasoning_levels": [],
                    },
                    {
                        "slug": "gpt-5.4-legacy",
                        "display_name": "GPT-5.4 Legacy",
                        "visibility": "list",
                        "supported_in_api": True,
                        "max_context_window": 128000,
                        "supported_reasoning_levels": [],
                    },
                    {
                        "slug": "gpt-5.3-empty-modalities",
                        "display_name": "GPT-5.3 Empty Modalities",
                        "visibility": "list",
                        "supported_in_api": True,
                        "input_modalities": [],
                        "supported_reasoning_levels": [],
                    },
                    {
                        "slug": "hidden-model",
                        "display_name": "Hidden",
                        "visibility": "hide",
                        "supported_in_api": True,
                    },
                    {
                        "slug": "unsupported-model",
                        "display_name": "Unsupported",
                        "visibility": "list",
                        "supported_in_api": False,
                    },
                ]
            },
        )


@pytest.mark.asyncio
async def test_list_chatgpt_models_uses_backend_capability_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ChatGPT listing filters visibility and preserves supported metadata."""
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    result = await providers.list_chatgpt_models_for_integration(_chatgpt_integration())

    assert result.summary.source == "chatgpt:codex_models"
    assert result.summary.returned_count == 4
    assert result.summary.skipped_count == 2
    candidate, standard_candidate, legacy_candidate, empty_modalities_candidate = (
        result.models
    )
    assert candidate.model_identifier == "gpt-6-astra"
    assert candidate.normalized_capabilities.built_in_tools.supported == ["web_search"]
    assert all(
        other_candidate.normalized_capabilities.built_in_tools.supported
        == ["web_search", "image_generation"]
        for other_candidate in result.models[1:]
    )
    assert candidate.normalized_capabilities.compatibility.provider_family == "chatgpt"
    assert candidate.normalized_capabilities.compatibility.responses_api is True
    assert (
        candidate.normalized_capabilities.context_window.default_input_tokens == 272000
    )
    assert candidate.normalized_capabilities.context_window.max_input_tokens == 872000
    assert candidate.normalized_capabilities.tool_calling.parallel_tool_calls is True
    assert candidate.normalized_capabilities.reasoning.effort_levels == [
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
        ModelReasoningEffort.XHIGH,
        ModelReasoningEffort.MAX,
    ]
    assert candidate.source_metadata is not None
    assert candidate.source_metadata["tool_mode"] == "code_mode_only"
    assert "base_instructions" not in candidate.source_metadata
    assert standard_candidate.model_identifier == "gpt-5.5-standard"
    assert legacy_candidate.normalized_capabilities.modalities.input == [
        ModelModality.TEXT,
        ModelModality.IMAGE,
    ]
    assert (
        legacy_candidate.normalized_capabilities.context_window.max_input_tokens
        == 128000
    )
    assert (
        legacy_candidate.normalized_capabilities.context_window.default_input_tokens
        is None
    )
    assert empty_modalities_candidate.normalized_capabilities.modalities.input == []


class _FakeKimiAsyncClient:
    """Return one deterministic Kimi account model listing."""

    def __init__(self, *, timeout: float) -> None:
        assert timeout == 20.0

    async def __aenter__(self) -> "_FakeKimiAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
    ) -> httpx.Response:
        assert url == f"{providers.resolve_kimi_code_api_base_url()}/models"
        assert headers["Authorization"] == "Bearer kimi-access-token"
        assert headers["X-Msh-Platform"] == "kimi_cli"
        assert headers["X-Msh-Device-Id"] == "kimi-device-id"
        return httpx.Response(
            status_code=200,
            request=httpx.Request("GET", url),
            json={
                "data": [
                    {
                        "id": "kimi-k2.5",
                        "context_length": 262144,
                        "supports_reasoning": True,
                        "supports_image_in": True,
                        "supports_video_in": False,
                    },
                    {
                        "id": "kimi-for-coding",
                        "display_name": "Kimi for Coding",
                        "context_length": 131072,
                        "supports_reasoning": False,
                        "supports_image_in": False,
                        "supports_video_in": True,
                    },
                    ["invalid"],
                    {"context_length": 1},
                ]
            },
        )


@pytest.mark.asyncio
async def test_list_kimi_models_projects_authenticated_account_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kimi listing projects account-visible models without LiteLLM gating."""
    monkeypatch.setattr(httpx, "AsyncClient", _FakeKimiAsyncClient)

    result = await providers.list_kimi_models_for_integration(_kimi_integration())

    assert result.summary.source == "kimi:code_models"
    assert result.summary.returned_count == 2
    assert result.summary.skipped_count == 2
    reasoning, coding = result.models
    assert reasoning.model_identifier == "kimi-k2.5"
    assert reasoning.model_developer == LLMModelDeveloper.MOONSHOT
    assert reasoning.model_family == "kimi-k2.5"
    assert reasoning.normalized_capabilities.context_window.max_input_tokens == 262144
    assert reasoning.normalized_capabilities.modalities.input == [
        ModelModality.TEXT,
        ModelModality.IMAGE,
    ]
    assert reasoning.normalized_capabilities.reasoning.supported is True
    assert reasoning.normalized_capabilities.tool_calling.supported is True
    assert reasoning.normalized_capabilities.compatibility.provider_family == "moonshot"
    assert reasoning.normalized_capabilities.compatibility.responses_api is True
    assert coding.normalized_capabilities.modalities.input == [
        ModelModality.TEXT,
        ModelModality.VIDEO,
    ]
    assert coding.source_metadata == {
        "context_length": 131072,
        "supports_reasoning": False,
        "supports_image_in": False,
        "supports_video_in": True,
    }


class _FakeOpenRouterAsyncClient:
    def __init__(self, *, timeout: float) -> None:
        assert timeout == 20.0

    async def __aenter__(self) -> "_FakeOpenRouterAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def get(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> httpx.Response:
        assert url == f"{providers.OPENROUTER_API_BASE_URL}/models/user"
        assert params == {"output_modalities": "text"}
        assert headers == {"Authorization": "Bearer openrouter-test-key"}
        return httpx.Response(
            status_code=200,
            request=httpx.Request("GET", url),
            json={
                "data": [
                    {
                        "id": "anthropic/claude-example",
                        "name": "Claude Example",
                        "description": "not persisted",
                        "architecture": {
                            "input_modalities": ["text", "image", "file"],
                            "output_modalities": ["text"],
                        },
                        "context_length": 200000,
                        "top_provider": {"max_completion_tokens": 32000},
                        "supported_parameters": [
                            "tools",
                            "parallel_tool_calls",
                            "reasoning",
                            "reasoning_effort",
                            "temperature",
                            "max_tokens",
                            "top_p",
                            "top_k",
                            "stop",
                            "structured_outputs",
                        ],
                        "pricing": {"prompt": "0.1", "completion": "0.2"},
                        "links": {"homepage": "https://example.invalid"},
                        "benchmarks": {"score": 1},
                    },
                    {
                        "id": "new-publisher/new-model",
                        "name": "New Model",
                        "supported_parameters": [],
                    },
                    ["invalid"],
                    {"name": "Missing id"},
                    {
                        "id": "vendor/image-only-output",
                        "architecture": {"output_modalities": ["image"]},
                    },
                ]
            },
        )


@pytest.mark.asyncio
async def test_list_openrouter_models_projects_account_metadata_without_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenRouter listing keeps every valid text model and safe capabilities."""
    monkeypatch.setattr(httpx, "AsyncClient", _FakeOpenRouterAsyncClient)

    result = await providers.list_openrouter_models_for_integration(
        _openrouter_integration()
    )

    assert result.summary.source == "openrouter:account_models"
    assert result.summary.returned_count == 2
    assert result.summary.skipped_count == 3
    known, unknown = result.models
    assert known.model_identifier == "anthropic/claude-example"
    assert known.model_developer == LLMModelDeveloper.ANTHROPIC
    assert known.normalized_capabilities.context_window.max_input_tokens == 200000
    assert known.normalized_capabilities.context_window.max_output_tokens == 32000
    assert known.normalized_capabilities.modalities.input == [
        ModelModality.TEXT,
        ModelModality.IMAGE,
    ]
    assert known.normalized_capabilities.tool_calling.supported is True
    assert known.normalized_capabilities.tool_calling.parallel_tool_calls is True
    assert known.normalized_capabilities.tool_calling.strict_json_schema is None
    assert known.normalized_capabilities.reasoning.effort_levels == [
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    ]
    assert known.normalized_capabilities.built_in_tools.supported == ["web_search"]
    assert known.normalized_capabilities.parameters.temperature is True
    assert known.normalized_capabilities.parameters.max_output_tokens is True
    assert known.normalized_capabilities.parameters.top_p is True
    assert known.normalized_capabilities.parameters.top_k is True
    assert known.normalized_capabilities.parameters.stop_sequences is True
    assert known.source_metadata is not None
    assert "description" not in known.source_metadata
    assert "links" not in known.source_metadata
    assert "benchmarks" not in known.source_metadata
    assert unknown.model_developer == LLMModelDeveloper.OTHER
    assert unknown.normalized_capabilities.modalities.input == [ModelModality.TEXT]
