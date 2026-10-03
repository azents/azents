"""Provider-visible model listing adapter tests."""

import datetime
import json
from types import SimpleNamespace
from typing import Literal

import httpx
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, InvalidRegionError
from google.auth.exceptions import TransportError as GoogleTransportError
from openai.types import Model as OpenAIModel
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
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelModality,
    ModelReasoningEffort,
)
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_catalog_source import CatalogFact
from azents.core.model_execution_options import (
    ModelExecutionOptionId,
    list_model_execution_option_definitions,
    validate_execution_options,
)
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationWithSecrets,
)
from azents.services.model_listing import providers
from azents.services.model_listing.data import NormalizedModelCandidate
from azents.services.model_metadata_projection import (
    project_integration_replacement_entries,
)
from azents.testing.model_metadata import (
    make_test_source_payload,
    make_test_source_snapshot,
)


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
        catalog_configuration_version=1,
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
        catalog_configuration_version=1,
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
        catalog_configuration_version=1,
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
        catalog_configuration_version=1,
    )


def _openai_integration() -> LLMProviderIntegrationWithSecrets:
    """Build one OpenAI API-key integration for image model listing tests."""
    now = datetime.datetime.now(datetime.UTC)
    return LLMProviderIntegrationWithSecrets(
        id="openai-integration-id",
        workspace_id="workspace-id",
        provider=LLMProvider.OPENAI,
        name="OpenAI",
        config=None,
        enabled=True,
        created_at=now,
        updated_at=now,
        secrets=ApiKeySecrets(api_key="openai-test-key"),
        catalog_configuration_version=1,
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
        catalog_configuration_version=1,
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
                OpenAIModel(
                    id="grok-4.7-api",
                    created=1_787_000_000,
                    owned_by="xai",
                    object="model",
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


class _FakeOpenAIPage:
    def __init__(
        self,
        *,
        data: list[SimpleNamespace],
        next_page: "_FakeOpenAIPage | None" = None,
    ) -> None:
        self.data = data
        self.next_page = next_page

    def has_next_page(self) -> bool:
        """Return whether a deterministic page remains."""
        return self.next_page is not None

    async def get_next_page(self) -> "_FakeOpenAIPage":
        """Return the configured next page."""
        if self.next_page is None:
            raise AssertionError("No page should be requested.")
        return self.next_page


class _FakeOpenAIModels:
    def __init__(self, page: _FakeOpenAIPage) -> None:
        self.page = page

    async def list(self) -> _FakeOpenAIPage:
        """Return the first complete SDK-like page."""
        return self.page


class _FakeOpenAISdkClient:
    page: _FakeOpenAIPage

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        organization: str | None,
        project: str | None,
        default_headers: dict[str, str] | None,
        max_retries: int,
        timeout: float,
    ) -> None:
        assert api_key == "openai-test-key"
        assert base_url == "https://openai.example/v1"
        assert organization == "org-test"
        assert project == "project-test"
        assert default_headers == {"X-OpenAI-Test": "true"}
        assert max_retries == 0
        assert timeout == 20.0
        self.models = _FakeOpenAIModels(self.page)

    async def __aenter__(self) -> "_FakeOpenAISdkClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        del args


async def test_openai_image_model_listing_consumes_complete_sdk_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the supported SDK and return every exact visible identifier."""
    _FakeOpenAISdkClient.page = _FakeOpenAIPage(
        data=[SimpleNamespace(id="gpt-image-2.5-flare")],
        next_page=_FakeOpenAIPage(data=[SimpleNamespace(id="gpt-image-2.5-sunburst")]),
    )
    monkeypatch.setattr(providers, "AsyncOpenAI", _FakeOpenAISdkClient)
    monkeypatch.setattr(
        providers,
        "openai_responses_client_config",
        lambda **kwargs: SimpleNamespace(
            base_url="https://openai.example/v1",
            organization="org-test",
            project="project-test",
            default_headers={"X-OpenAI-Test": "true"},
        ),
    )

    result = await providers.list_openai_image_generation_models_for_integration(
        _openai_integration()
    )

    assert result.provider == LLMProvider.OPENAI
    assert result.source == "openai:models_list"
    assert result.provider_model_identifiers == [
        "gpt-image-2.5-flare",
        "gpt-image-2.5-sunburst",
    ]


@pytest.mark.parametrize(
    "data",
    [
        [SimpleNamespace(id=None)],
        [
            SimpleNamespace(id="gpt-image-2.5-flare"),
            SimpleNamespace(id="gpt-image-2.5-flare"),
        ],
    ],
)
async def test_openai_image_model_listing_rejects_malformed_or_ambiguous_data(
    monkeypatch: pytest.MonkeyPatch,
    data: list[SimpleNamespace],
) -> None:
    """Do not publish a partial or ambiguous provider visibility result."""
    _FakeOpenAISdkClient.page = _FakeOpenAIPage(data=data)
    monkeypatch.setattr(providers, "AsyncOpenAI", _FakeOpenAISdkClient)
    monkeypatch.setattr(
        providers,
        "openai_responses_client_config",
        lambda **kwargs: SimpleNamespace(
            base_url="https://openai.example/v1",
            organization="org-test",
            project="project-test",
            default_headers={"X-OpenAI-Test": "true"},
        ),
    )

    with pytest.raises(providers.ListingProviderError) as caught:
        await providers.list_openai_image_generation_models_for_integration(
            _openai_integration()
        )

    assert caught.value.automatic_retry_blocked is False


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
                        "service_tiers": [
                            {
                                "id": "priority",
                                "name": "Fast",
                                "description": "Faster responses with higher usage.",
                            }
                        ],
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
    assert candidate.supported_execution_options == [ModelExecutionOptionId.FAST]
    assert standard_candidate.supported_execution_options == []
    assert candidate.normalized_capabilities.built_in_tools.supported == [
        "web_search",
        "image_generation",
    ]
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


@pytest.mark.parametrize("source_kind", ["absent", "unmatched", "sparse", "denial"])
async def test_chatgpt_web_search_survives_final_catalog_projection(
    monkeypatch: pytest.MonkeyPatch,
    source_kind: Literal["absent", "unmatched", "sparse", "denial"],
) -> None:
    """Account-visible ChatGPT tools survive the actual replacement producer."""
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    result = await providers.list_chatgpt_models_for_integration(_chatgpt_integration())
    candidates = [
        NormalizedModelCandidate.model_validate_json(candidate.model_dump_json())
        for candidate in result.models
    ]
    rows: dict[str, object] = {
        f"chatgpt/{candidate.model_identifier}": {
            "litellm_provider": "chatgpt",
            "mode": "responses",
            **({"supports_web_search": False} if source_kind == "denial" else {}),
        }
        for candidate in candidates
    }
    if source_kind == "unmatched":
        rows = {
            "gpt-6-astra": {
                "litellm_provider": "openai",
                "mode": "responses",
                "supports_web_search": True,
            }
        }
    source = (
        None
        if source_kind == "absent"
        else make_test_source_snapshot(make_test_source_payload(rows))
    )
    entries = project_integration_replacement_entries(
        integration_id="integration-id",
        provider=LLMProvider.CHATGPT_OAUTH,
        candidates=candidates,
        source=source,
        provider_listing_source=result.summary.source,
    )
    assert len(entries) == 4
    for entry in entries:
        capabilities = ModelCapabilities.model_validate_json(
            json.dumps(entry.normalized_capabilities)
        )
        assert "web_search" in capabilities.built_in_tools.supported
        assert capabilities.semantic_contract is not None
        [web] = [
            declaration
            for declaration in capabilities.semantic_contract.built_in_tools
            if declaration.tool == "web_search"
        ]
        assert web.support.state == "supported"
        assert web.support.origin == "contract_derived"
        assert web.support.predicate is None


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
    """Kimi listing projects account-visible models without metadata gating."""
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
    assert known.normalized_capabilities.reasoning.effort_levels == []
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


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        (
            "gpt-6-astra",
            [ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST],
        ),
        (
            "gpt-5.6-sol",
            [ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST],
        ),
        ("gpt-5.6-terra", [ModelExecutionOptionId.FAST]),
        ("gpt-5.6-luna", [ModelExecutionOptionId.FAST]),
        ("gpt-5.5", [ModelExecutionOptionId.FAST]),
        ("gpt-6-astra-2026-09-30", []),
        ("gpt-6-astra-preview", []),
        ("gpt-5.6-sol-preview", []),
        ("openai/gpt-6-astra", []),
        ("ft:gpt-6-astra:test", []),
        ("gpt-6", []),
        ("unknown", []),
    ],
)
def test_openai_execution_support_uses_exact_reviewed_identifiers(
    model_id: str,
    expected: list[ModelExecutionOptionId],
) -> None:
    """Reviewed support does not imply alias support or preview entitlement."""
    assert providers._openai_supported_execution_options(model_id) == expected


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (
            {"service_tiers": ["priority", "ultrafast"]},
            [ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST],
        ),
        (
            {"service_tiers": [{"id": "fast"}, {"id": "ultrafast"}]},
            [ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST],
        ),
        (
            {"service_tiers": ["ultrafast", {"id": "priority"}, "priority"]},
            [ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST],
        ),
        ({"service_tiers": ["ultrafast"]}, [ModelExecutionOptionId.ULTRAFAST]),
        ({"service_tiers": [{"id": "ultrafast"}]}, [ModelExecutionOptionId.ULTRAFAST]),
        (
            {"service_tiers": ["ultrafast", {"id": "ultrafast"}]},
            [ModelExecutionOptionId.ULTRAFAST],
        ),
        ({"service_tiers": ["fast"]}, [ModelExecutionOptionId.FAST]),
        ({}, []),
        ({"service_tiers": []}, []),
        ({"service_tiers": None}, []),
        ({"service_tiers": "ultrafast"}, []),
        ({"service_tiers": {"id": "ultrafast"}}, []),
        ({"service_tiers": [None, 1, [], {}]}, []),
        ({"service_tiers": [{"id": None}, {"id": 1}, {"id": ["ultrafast"]}]}, []),
        (
            {
                "service_tiers": [
                    "UltraFast",
                    " ultrafast",
                    "ultrafast ",
                    "ultrafast-preview",
                    {"name": "Ultrafast"},
                    {"value": "ultrafast"},
                ]
            },
            [],
        ),
        (
            {
                "default_service_tier": "ultrafast",
                "speed": "ultrafast",
                "plan": "pro",
                "slug": "gpt-6-astra",
            },
            [],
        ),
        (
            {"service_tiers": [None, {"id": 1}, {"id": "ultrafast"}]},
            [ModelExecutionOptionId.ULTRAFAST],
        ),
    ],
)
def test_chatgpt_execution_support_requires_independent_exact_tier_ids(
    metadata: dict[str, object],
    expected: list[ModelExecutionOptionId],
) -> None:
    """Account metadata is support authority, not a global model or plan policy."""
    assert providers._chatgpt_supported_execution_options(metadata) == expected


class _ServiceTierChatGPTClient:
    """Serve synthetic account metadata through the existing listing boundary."""

    metadata: dict[str, object]

    def __init__(self, *, timeout: float) -> None:
        assert timeout == 20.0

    async def __aenter__(self) -> "_ServiceTierChatGPTClient":
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
        assert headers["ChatGPT-Account-Id"] == "account-id"
        return httpx.Response(
            status_code=200,
            request=httpx.Request("GET", url),
            json={
                "models": [
                    {
                        "slug": "account-visible-model",
                        "display_name": "Account Visible Model",
                        "visibility": "list",
                        "supported_in_api": True,
                        **self.metadata,
                    }
                ]
            },
        )


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (
            {"service_tiers": [{"id": "ultrafast"}, {"id": "priority"}]},
            [ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST],
        ),
        ({"service_tiers": ["ultrafast"]}, [ModelExecutionOptionId.ULTRAFAST]),
        ({}, []),
        ({"service_tiers": [{"id": None}]}, []),
    ],
)
async def test_chatgpt_listing_support_is_not_enabled_preference(
    monkeypatch: pytest.MonkeyPatch,
    metadata: dict[str, object],
    expected: list[ModelExecutionOptionId],
) -> None:
    """Project both/only/absent support through the authenticated listing adapter."""
    _ServiceTierChatGPTClient.metadata = metadata
    monkeypatch.setattr(httpx, "AsyncClient", _ServiceTierChatGPTClient)
    result = await providers.list_chatgpt_models_for_integration(_chatgpt_integration())
    [candidate] = result.models
    assert candidate.supported_execution_options == expected
    assert result.summary.returned_count == 1
    definitions = list_model_execution_option_definitions(
        provider=LLMProvider.CHATGPT_OAUTH,
        supported=candidate.supported_execution_options,
    )
    assert [definition.id for definition in definitions] == expected
    if len(expected) == 2:
        with pytest.raises(ValueError, match="exclusive"):
            validate_execution_options(
                provider=LLMProvider.CHATGPT_OAUTH,
                supported=candidate.supported_execution_options,
                enabled=expected,
            )


def _replayed_evidence(
    candidate: NormalizedModelCandidate | None,
) -> ProviderCapabilityEvidence:
    assert candidate is not None
    restored = NormalizedModelCandidate.model_validate_json(candidate.model_dump_json())
    assert restored == candidate
    assert restored.capability_evidence is not None
    return restored.capability_evidence


@pytest.mark.parametrize(
    "provider",
    [
        LLMProvider.CHATGPT_OAUTH,
        LLMProvider.KIMI_OAUTH,
        LLMProvider.XAI,
        LLMProvider.XAI_OAUTH,
        LLMProvider.OPENROUTER,
        LLMProvider.AWS_BEDROCK,
        LLMProvider.GOOGLE_VERTEX_AI,
    ],
)
def test_sparse_listing_replay_does_not_promote_constructor_defaults(
    provider: LLMProvider,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    if provider == LLMProvider.CHATGPT_OAUTH:
        candidate = providers._candidate_from_chatgpt_model(
            {"slug": "new-model", "supported_in_api": True, "visibility": "list"},
            fetched_at=now,
        )
    elif provider == LLMProvider.KIMI_OAUTH:
        candidate = providers._candidate_from_kimi_model(
            {"id": "new-model"}, fetched_at=now
        )
    elif provider == LLMProvider.XAI:
        candidate = providers._candidate_from_xai_api_key_model(
            model_id="new-model", created=1, extra=None, fetched_at=now
        )
    elif provider == LLMProvider.XAI_OAUTH:
        candidate = providers._candidate_from_xai_oauth_model(
            providers._XaiOAuthModelPayload(id="new-model"), fetched_at=now
        )
    elif provider == LLMProvider.OPENROUTER:
        candidate = providers._candidate_from_openrouter_model(
            {"id": "new-publisher/new-model"}, fetched_at=now
        )
    elif provider == LLMProvider.AWS_BEDROCK:
        candidate = providers._candidate_from_bedrock_summary(
            {"modelId": "new-model", "providerName": "Anthropic"}, fetched_at=now
        )
    elif provider == LLMProvider.GOOGLE_VERTEX_AI:
        candidate = providers._candidate_from_vertex_model(
            {"name": "publishers/google/models/new-model"},
            publisher="google",
            developer=LLMModelDeveloper.GOOGLE,
            fetched_at=now,
        )
    else:
        raise AssertionError("Unhandled provider test case.")

    assert _replayed_evidence(candidate) == ProviderCapabilityEvidence()
    assert candidate is not None
    historic_json = json.loads(candidate.model_dump_json())
    del historic_json["capability_evidence"]
    restored_historic = NormalizedModelCandidate.model_validate_json(
        json.dumps(historic_json)
    )
    assert restored_historic.capability_evidence is None
    assert (
        restored_historic.normalized_capabilities == candidate.normalized_capabilities
    )


@pytest.mark.parametrize("flag", [True, False, None])
def test_kimi_media_flags_remain_independent_after_replay(flag: bool | None) -> None:
    candidate = providers._candidate_from_kimi_model(
        {"id": "kimi-new", "supports_image_in": flag},
        fetched_at=datetime.datetime.now(datetime.UTC),
    )
    evidence = _replayed_evidence(candidate)
    assert evidence.image_input == CatalogFact(
        state="null" if flag is None else "value", value=flag
    )
    assert evidence.video_input.state == "absent"
    assert evidence.input_modalities.state == "absent"
    assert evidence.function_calling.state == "absent"


def test_kimi_video_reasoning_evidence_does_not_invent_effort_controls() -> None:
    evidence = _replayed_evidence(
        providers._candidate_from_kimi_model(
            {
                "id": "kimi-new",
                "supports_image_in": False,
                "supports_video_in": True,
                "supports_reasoning": True,
            },
            fetched_at=datetime.datetime.now(datetime.UTC),
        )
    )
    assert evidence.image_input == CatalogFact(state="value", value=False)
    assert evidence.video_input == CatalogFact(state="value", value=True)
    assert evidence.reasoning == CatalogFact(state="value", value=True)
    assert evidence.reasoning_efforts.state == "absent"
    assert evidence.responses_api.state == "absent"


@pytest.mark.parametrize(
    ("parameters", "reasoning", "effort_state", "temperature"),
    [
        (None, None, "null", None),
        ([], False, "value", False),
        (["include_reasoning"], True, "value", False),
        (["reasoning"], True, "absent", False),
        (["reasoning_effort", "temperature"], True, "absent", True),
    ],
)
def test_openrouter_parameter_declarations_are_not_generic_effort_arrays(
    parameters: list[str] | None,
    reasoning: bool | None,
    effort_state: str,
    temperature: bool | None,
) -> None:
    evidence = _replayed_evidence(
        providers._candidate_from_openrouter_model(
            {
                "id": "publisher/new-model",
                "supported_parameters": parameters,
            },
            fetched_at=datetime.datetime.now(datetime.UTC),
        )
    )
    assert evidence.reasoning.value == reasoning
    assert evidence.reasoning_efforts.state == effort_state
    assert evidence.reasoning_efforts.value == (() if effort_state == "value" else None)
    assert evidence.temperature.value == temperature
    assert evidence.strict_function_schema.state == "absent"
    assert evidence.structured_response.state == (
        "null" if parameters is None else "value"
    )
    assert evidence.structured_response.value == (None if parameters is None else False)


@pytest.mark.parametrize(
    ("declaration", "state", "value"),
    [
        ({}, "absent", None),
        ({"supported_parameters": None}, "null", None),
        ({"supported_parameters": []}, "value", False),
        ({"supported_parameters": ["temperature"]}, "value", False),
        ({"supported_parameters": ["response_format"]}, "value", False),
        ({"supported_parameters": ["structured_outputs"]}, "value", True),
        (
            {"supported_parameters": ["response_format", "structured_outputs"]},
            "value",
            True,
        ),
    ],
)
def test_openrouter_structured_response_preserves_complete_parameter_presence(
    declaration: dict[str, object], state: str, value: bool | None
) -> None:
    evidence = _replayed_evidence(
        providers._candidate_from_openrouter_model(
            {"id": "publisher/new-model", **declaration},
            fetched_at=datetime.datetime.now(datetime.UTC),
        )
    )
    assert evidence.structured_response.state == state
    assert evidence.structured_response.value == value
    assert evidence.strict_function_schema.state == "absent"


@pytest.mark.parametrize("source_support", [True, False])
@pytest.mark.parametrize(
    ("declaration", "provider_state"),
    [
        ({}, "absent"),
        ({"supported_parameters": None}, "unknown"),
        ({"supported_parameters": []}, "unsupported"),
        ({"supported_parameters": ["temperature"]}, "unsupported"),
        ({"supported_parameters": ["response_format"]}, "unsupported"),
        ({"supported_parameters": ["structured_outputs"]}, "supported"),
        (
            {"supported_parameters": ["response_format", "structured_outputs"]},
            "supported",
        ),
    ],
)
def test_openrouter_structured_response_source_enriches_only_absent_declaration(
    declaration: dict[str, object], provider_state: str, source_support: bool
) -> None:
    candidate = providers._candidate_from_openrouter_model(
        {"id": "publisher/new-model", **declaration},
        fetched_at=datetime.datetime.now(datetime.UTC),
    )
    assert candidate is not None
    replayed = NormalizedModelCandidate.model_validate_json(candidate.model_dump_json())
    source = make_test_source_snapshot(
        make_test_source_payload(
            {
                "openrouter/publisher/new-model": {
                    "litellm_provider": "openrouter",
                    "mode": "chat",
                    "supports_response_schema": source_support,
                }
            }
        )
    )
    [entry] = project_integration_replacement_entries(
        integration_id="integration-id",
        provider=LLMProvider.OPENROUTER,
        candidates=[replayed],
        source=source,
        provider_listing_source="openrouter:account_models",
    )
    capabilities = ModelCapabilities.model_validate(entry.normalized_capabilities)
    assert entry.projection_metadata is not None
    assert entry.projection_metadata["matched"] is True
    assert capabilities.semantic_contract is not None
    expected_state = (
        ("supported" if source_support else "unsupported")
        if provider_state == "absent"
        else provider_state
    )
    assert capabilities.semantic_contract.structured_response.state == expected_state
    assert not capabilities.semantic_contract.strict_function_schema.enabled


def test_openrouter_explicit_empty_modalities_and_nested_null_survive_replay() -> None:
    evidence = _replayed_evidence(
        providers._candidate_from_openrouter_model(
            {
                "id": "publisher/new-model",
                "architecture": {"input_modalities": [], "output_modalities": None},
                "top_provider": None,
                "supported_parameters": ["structured_outputs", "tools"],
            },
            fetched_at=datetime.datetime.now(datetime.UTC),
        )
    )
    assert evidence.input_modalities == CatalogFact(state="value", value=())
    assert evidence.output_modalities.state == "null"
    assert evidence.max_output_tokens.state == "null"
    assert evidence.function_calling == CatalogFact(state="value", value=True)
    assert evidence.structured_response == CatalogFact(state="value", value=True)
    assert evidence.strict_function_schema.state == "absent"


def test_bedrock_media_declarations_preserve_unsupported_lowering_evidence() -> None:
    evidence = _replayed_evidence(
        providers._candidate_from_bedrock_summary(
            {
                "modelId": "provider-new",
                "providerName": "Anthropic",
                "inputModalities": ["TEXT", "AUDIO", "FUTURE-MEDIA"],
                "outputModalities": [],
            },
            fetched_at=datetime.datetime.now(datetime.UTC),
        )
    )
    assert evidence.input_modalities.value == ("text", "audio", "future-media")
    assert evidence.output_modalities == CatalogFact(state="value", value=())
    assert evidence.function_calling.state == "absent"
    assert evidence.strict_function_schema.state == "absent"


def test_vertex_explicit_null_and_limits_survive_replay() -> None:
    evidence = _replayed_evidence(
        providers._candidate_from_vertex_model(
            {
                "modelId": "provider-new",
                "inputTokenLimit": None,
                "outputTokenLimit": 12345,
            },
            publisher="google",
            developer=LLMModelDeveloper.GOOGLE,
            fetched_at=datetime.datetime.now(datetime.UTC),
        )
    )
    assert evidence.max_input_tokens.state == "null"
    assert evidence.max_output_tokens.value == 12345
    assert evidence.function_calling.state == "absent"


@pytest.mark.parametrize("efforts", [[], ["xhigh", "max"], ["ultra"]])
def test_chatgpt_explicit_effort_arrays_are_not_profile_intersections(
    efforts: list[str],
) -> None:
    candidate = providers._candidate_from_chatgpt_model(
        {
            "slug": "new-model",
            "visibility": "list",
            "supported_in_api": True,
            "supported_reasoning_levels": [{"effort": effort} for effort in efforts],
            "default_reasoning_level": "ultra",
            "supports_parallel_tool_calls": False,
            "supports_reasoning_summaries": None,
            "input_modalities": [],
        },
        fetched_at=datetime.datetime.now(datetime.UTC),
    )
    evidence = _replayed_evidence(candidate)
    assert evidence.reasoning_efforts == CatalogFact(
        state="value",
        value=tuple(
            ModelReasoningEffort(value) for value in efforts if value != "ultra"
        ),
    )
    assert evidence.default_reasoning_effort.state == "null"
    assert evidence.parallel_function_calling.value is False
    assert evidence.reasoning_summaries.state == "null"
    assert evidence.input_modalities.value == ()
    assert evidence.function_calling.state == "absent"
    if efforts == ["ultra"]:
        assert evidence.reasoning.state == "absent"
        assert candidate is not None and candidate.source_metadata is not None
        assert candidate.source_metadata["supported_reasoning_levels"] == [
            {"effort": "ultra"}
        ]
        assert candidate.source_metadata["capability_evidence_diagnostics"] == {
            "unsupported_reasoning_effort_labels": ["ultra"]
        }


@pytest.mark.parametrize(
    "capabilities",
    [
        None,
        {"reasoning": False, "reasoning_effort": []},
        {"reasoning": True, "reasoning_effort": ["xhigh", "max", "ultra"]},
    ],
)
async def test_xai_sdk_extensions_are_consumed_but_request_hints_are_not_persisted(
    monkeypatch: pytest.MonkeyPatch,
    capabilities: dict[str, object] | None,
) -> None:
    class FakeModels:
        async def list(self) -> SimpleNamespace:
            model = OpenAIModel.model_validate(
                {
                    "id": "grok-new",
                    "created": 1,
                    "owned_by": "xai",
                    "object": "model",
                    "context_length": None,
                    "capabilities": capabilities,
                    "provider_instructions": "do not persist",
                    "credential": "do not persist",
                }
            )
            return SimpleNamespace(data=[model])

    class FakeClient(_FakeXaiSdkClient):
        def __init__(self, *, api_key: str, base_url: str, timeout: float) -> None:
            assert api_key == "xai-test-key"
            assert base_url == providers.resolve_xai_api_base_url()
            assert timeout == 20.0
            self.models = FakeModels()

    monkeypatch.setattr(providers, "AsyncOpenAI", FakeClient)
    [candidate] = (
        await providers.list_xai_models_for_integration(_xai_api_key_integration())
    ).models
    evidence = _replayed_evidence(candidate)
    assert evidence.max_input_tokens.state == "null"
    assert "do not persist" not in candidate.model_dump_json()
    if capabilities is None:
        assert evidence.reasoning.state == "null"
        assert evidence.reasoning_efforts.state == "null"
    elif capabilities["reasoning"] is False:
        assert evidence.reasoning.value is False
        assert evidence.reasoning_efforts.value == ()
    else:
        assert evidence.reasoning.value is True
        assert evidence.reasoning_efforts.value == (
            ModelReasoningEffort.XHIGH,
            ModelReasoningEffort.MAX,
        )
        assert candidate.source_metadata is not None
        assert candidate.source_metadata["capability_evidence_diagnostics"] == {
            "unsupported_reasoning_effort_labels": ["ultra"]
        }


def test_xai_oauth_empty_controls_preserve_unknown_reasoning() -> None:
    evidence = _replayed_evidence(
        providers._candidate_from_xai_oauth_model(
            providers._XaiOAuthModelPayload.model_validate(
                {
                    "id": "grok-new",
                    "supports_reasoning_effort": False,
                    "supports_backend_search": False,
                    "api_backend": None,
                    "provider_instructions": "do not persist",
                }
            ),
            fetched_at=datetime.datetime.now(datetime.UTC),
        )
    )
    assert evidence.reasoning_efforts == CatalogFact(state="value", value=())
    assert evidence.reasoning.state == "absent"
    assert evidence.web_search.value is False
    assert evidence.responses_api.state == "null"


def test_xai_oauth_ambiguous_default_is_unknown_not_arbitrarily_selected() -> None:
    candidate = providers._candidate_from_xai_oauth_model(
        providers._XaiOAuthModelPayload.model_validate(
            {
                "id": "grok-new",
                "reasoning_efforts": [
                    {"id": "xhigh", "default": True, "provider_instructions": "unsafe"},
                    {"id": "max", "default": True},
                ],
                "provider_instructions": "unsafe",
            }
        ),
        fetched_at=datetime.datetime.now(datetime.UTC),
    )
    evidence = _replayed_evidence(candidate)
    assert evidence.reasoning_efforts.value == (
        ModelReasoningEffort.XHIGH,
        ModelReasoningEffort.MAX,
    )
    assert evidence.default_reasoning_effort.state == "null"
    assert "unsafe" not in candidate.model_dump_json()


def test_xai_oauth_disabled_controls_win_over_conflicting_presets() -> None:
    candidate = providers._candidate_from_xai_oauth_model(
        providers._XaiOAuthModelPayload.model_validate(
            {
                "id": "grok-new",
                "supports_reasoning_effort": False,
                "reasoning_efforts": [
                    {"id": "low", "default": True},
                    {"id": "high"},
                ],
            }
        ),
        fetched_at=datetime.datetime(2026, 10, 3, tzinfo=datetime.UTC),
    )
    assert candidate is not None
    evidence = _replayed_evidence(candidate)
    assert evidence.reasoning_efforts == CatalogFact(state="value", value=())
    assert evidence.default_reasoning_effort.value is None
    assert candidate.source_metadata is not None
    assert candidate.source_metadata["capability_conflicts"] == [
        "reasoning_effort_controls_disabled_with_presets"
    ]
    [entry] = project_integration_replacement_entries(
        integration_id="integration-xai",
        provider=LLMProvider.XAI_OAUTH,
        candidates=[candidate],
        source=None,
        provider_listing_source="xai_oauth:grok_models",
    )
    caps = ModelCapabilities.model_validate(entry.normalized_capabilities)
    assert caps.reasoning.effort_levels == []
    assert caps.semantic_contract is not None
    assert caps.semantic_contract.reasoning.completeness == "complete"
    assert caps.semantic_contract.reasoning.default_effort is None
