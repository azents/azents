"""Provider-visible model listing adapter tests."""

import datetime

import httpx
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, InvalidRegionError
from google.auth.exceptions import TransportError as GoogleTransportError
from pydantic import TypeAdapter, ValidationError

from azents.core.chatgpt_oauth import (
    CHATGPT_OAUTH_BACKEND_BASE_URL,
    CHATGPT_OAUTH_PROTOCOL_VERSION,
)
from azents.core.credentials import ChatGPTOAuthConfig, ChatGPTOAuthSecrets
from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelModality, ModelReasoningEffort
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationWithSecrets,
)
from azents.services.model_listing import providers


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
        assert params == {"client_version": CHATGPT_OAUTH_PROTOCOL_VERSION}
        assert headers["Authorization"] == "Bearer access-token"
        assert headers["ChatGPT-Account-Id"] == "account-id"
        assert headers["originator"] == "azents"
        assert headers["version"] == CHATGPT_OAUTH_PROTOCOL_VERSION
        return httpx.Response(
            status_code=200,
            request=httpx.Request("GET", url),
            json={
                "models": [
                    {
                        "slug": "gpt-5.6-luna",
                        "display_name": "GPT-5.6 Luna",
                        "visibility": "list",
                        "supported_in_api": True,
                        "context_window": 272000,
                        "input_modalities": ["text", "image"],
                        "supports_parallel_tool_calls": False,
                        "supports_reasoning_summaries": True,
                        "supported_reasoning_levels": [
                            {"effort": "low"},
                            {"effort": "medium"},
                            {"effort": "high"},
                        ],
                        "minimal_client_version": [0, 144, 0],
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
    assert all(
        candidate.normalized_capabilities.built_in_tools.supported
        == ["web_search", "image_generation"]
        for candidate in result.models
    )
    candidate, standard_candidate, legacy_candidate, empty_modalities_candidate = (
        result.models
    )
    assert candidate.model_identifier == "gpt-5.6-luna"
    assert candidate.normalized_capabilities.compatibility.provider_family == "chatgpt"
    assert candidate.normalized_capabilities.compatibility.responses_api is True
    assert candidate.normalized_capabilities.context_window.max_input_tokens == 272000
    assert candidate.normalized_capabilities.tool_calling.parallel_tool_calls is False
    assert candidate.normalized_capabilities.reasoning.effort_levels == [
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
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
    assert empty_modalities_candidate.normalized_capabilities.modalities.input == []
