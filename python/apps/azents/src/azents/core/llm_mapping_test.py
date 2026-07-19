"""LLM mapping function tests."""

import datetime

import pytest

from azents.core.chatgpt_oauth import CHATGPT_OAUTH_BACKEND_BASE_URL
from azents.core.credentials import (
    ApiKeySecrets,
    AwsConfig,
    AwsSecrets,
    ChatGPTOAuthConfig,
    ChatGPTOAuthSecrets,
    GcpConfig,
    GcpSecrets,
    ProviderConfig,
    ProviderSecrets,
    XaiOAuthSecrets,
)
from azents.core.enums import LLMProvider
from azents.core.llm_mapping import (
    build_credential_kwargs,
    to_litellm_model,
    to_runtime_model,
)
from azents.core.openrouter import OPENROUTER_API_BASE_URL, OPENROUTER_APP_TITLE
from azents.core.xai import XAI_API_BASE_URL
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationWithSecrets,
)


def _make_integration(
    provider: LLMProvider,
    secrets: ProviderSecrets,
    config: ProviderConfig | None = None,
) -> LLMProviderIntegrationWithSecrets:
    """Helper to create LLMProviderIntegrationWithSecrets for tests."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return LLMProviderIntegrationWithSecrets(
        id="test-integration-id",
        workspace_id="test-workspace-id",
        provider=provider,
        name="Test integration",
        config=config,
        enabled=True,
        created_at=now,
        updated_at=now,
        secrets=secrets,
    )


class TestToLitellmModel:
    """to_litellm_model function tests."""

    def test_openai(self) -> None:
        """OpenAI provider mapping."""
        # Given: OpenAI provider and model identifier
        # When: convert to LiteLLM model string
        result = to_litellm_model(LLMProvider.OPENAI, "gpt-4o")

        # Then: openai/ prefix
        assert result == "openai/gpt-4o"

    def test_anthropic(self) -> None:
        """Anthropic provider mapping."""
        # Given: Anthropic provider and model identifier
        # When: convert to LiteLLM model string
        result = to_litellm_model(LLMProvider.ANTHROPIC, "claude-opus-4-6")

        # Then: anthropic/ prefix
        assert result == "anthropic/claude-opus-4-6"

    def test_google_gemini(self) -> None:
        """Google Gemini provider mapping."""
        # Given: Google Gemini provider and model identifier
        # When: convert to LiteLLM model string
        result = to_litellm_model(LLMProvider.GOOGLE_GEMINI, "gemini-2.0-flash")

        # Then: gemini/ prefix
        assert result == "gemini/gemini-2.0-flash"

    def test_aws_bedrock(self) -> None:
        """AWS Bedrock provider mapping."""
        # Given: AWS Bedrock provider and model identifier
        # When: convert to LiteLLM model string
        result = to_litellm_model(LLMProvider.AWS_BEDROCK, "anthropic.claude-v2")

        # Then: bedrock/ prefix
        assert result == "bedrock/anthropic.claude-v2"

    def test_google_vertex_ai(self) -> None:
        """Google Vertex AI provider mapping."""
        # Given: Google Vertex AI provider and model identifier
        # When: convert to LiteLLM model string
        result = to_litellm_model(LLMProvider.GOOGLE_VERTEX_AI, "gemini-2.0-flash")

        # Then: vertex_ai/ prefix
        assert result == "vertex_ai/gemini-2.0-flash"

    def test_chatgpt_oauth(self) -> None:
        """ChatGPT OAuth provider uses Responses model ID as-is."""
        result = to_litellm_model(LLMProvider.CHATGPT_OAUTH, "gpt-5.1-codex")

        assert result == "gpt-5.1-codex"

    def test_xai(self) -> None:
        """xAI API key provider uses LiteLLM xAI routing prefix."""
        result = to_litellm_model(LLMProvider.XAI, "grok-4.5")

        assert result == "xai/grok-4.5"

    def test_xai_oauth(self) -> None:
        """xAI OAuth provider uses LiteLLM xAI routing prefix."""
        result = to_litellm_model(LLMProvider.XAI_OAUTH, "grok-4.5")

        assert result == "xai/grok-4.5"

    def test_openrouter(self) -> None:
        """OpenRouter keeps its publisher-qualified model identifier."""
        result = to_litellm_model(
            LLMProvider.OPENROUTER,
            "anthropic/claude-sonnet-4.6",
        )

        assert result == "openrouter/anthropic/claude-sonnet-4.6"


class TestToRuntimeModel:
    """to_runtime_model function tests."""

    def test_openai_responses_uses_raw_model_id(self) -> None:
        """Pass model ID without LiteLLM prefix to OpenAI Responses SDK."""
        result = to_runtime_model(LLMProvider.OPENAI, "gpt-5.5")

        assert result == "gpt-5.5"

    def test_chatgpt_oauth_uses_raw_model_id(self) -> None:
        """ChatGPT OAuth Responses SDK also uses raw model ID."""
        result = to_runtime_model(LLMProvider.CHATGPT_OAUTH, "gpt-5.1-codex")

        assert result == "gpt-5.1-codex"

    def test_bedrock_uses_litellm_routing_id(self) -> None:
        """LiteLLM provider keeps provider prefix."""
        result = to_runtime_model(
            LLMProvider.AWS_BEDROCK,
            "anthropic.claude-v2",
        )

        assert result == "bedrock/anthropic.claude-v2"

    @pytest.mark.parametrize("provider", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
    def test_xai_uses_litellm_routing_id(self, provider: LLMProvider) -> None:
        """Both xAI credential modes use LiteLLM xAI routing."""
        result = to_runtime_model(provider, "grok-4.5")

        assert result == "xai/grok-4.5"

    def test_openrouter_uses_litellm_routing_id(self) -> None:
        """OpenRouter runtime uses the LiteLLM OpenRouter routing prefix."""
        result = to_runtime_model(
            LLMProvider.OPENROUTER,
            "anthropic/claude-sonnet-4.6",
        )

        assert result == "openrouter/anthropic/claude-sonnet-4.6"


class TestBuildCredentialKwargs:
    """build_credential_kwargs function tests."""

    def test_api_key_secrets(self) -> None:
        """ApiKeySecrets to api_key kwargs conversion."""
        # Given: API key based integration
        integration = _make_integration(
            provider=LLMProvider.OPENAI,
            secrets=ApiKeySecrets(api_key="sk-test-key-123"),
        )

        # When: create credential kwargs
        result = build_credential_kwargs(integration)

        # Then: contains only api_key
        assert result == {"api_key": "sk-test-key-123"}

    def test_xai_api_key_secrets(self) -> None:
        """xAI API key credentials include explicit provider routing."""
        integration = _make_integration(
            provider=LLMProvider.XAI,
            secrets=ApiKeySecrets(api_key="xai-test-key"),
        )

        result = build_credential_kwargs(integration)

        assert result == {
            "api_key": "xai-test-key",
            "base_url": XAI_API_BASE_URL,
            "api_base": XAI_API_BASE_URL,
            "custom_llm_provider": "xai",
        }

    def test_openrouter_api_key_secrets(self) -> None:
        """OpenRouter credentials use its fixed Responses endpoint and title."""
        integration = _make_integration(
            provider=LLMProvider.OPENROUTER,
            secrets=ApiKeySecrets(api_key="openrouter-test-key"),
        )

        result = build_credential_kwargs(integration)

        assert result == {
            "api_key": "openrouter-test-key",
            "base_url": OPENROUTER_API_BASE_URL,
            "api_base": OPENROUTER_API_BASE_URL,
            "custom_llm_provider": "openrouter",
            "extra_headers": {
                "X-OpenRouter-Title": OPENROUTER_APP_TITLE,
            },
        }
        headers = result["extra_headers"]
        assert isinstance(headers, dict)
        assert "HTTP-Referer" not in headers

    def test_aws_secrets(self) -> None:
        """AwsSecrets + AwsConfig to aws_* kwargs conversion."""
        # Given: AWS IAM based integration
        integration = _make_integration(
            provider=LLMProvider.AWS_BEDROCK,
            secrets=AwsSecrets(secret_access_key="aws-secret-123"),
            config=AwsConfig(access_key_id="AKIA-test", region="us-east-1"),
        )

        # When: create credential kwargs
        result = build_credential_kwargs(integration)

        # Then: AWS credential kwargs
        assert result == {
            "aws_access_key_id": "AKIA-test",
            "aws_secret_access_key": "aws-secret-123",
            "aws_region_name": "us-east-1",
        }

    def test_gcp_secrets(self) -> None:
        """GcpSecrets + GcpConfig to vertex_* kwargs conversion."""
        # Given: GCP service account based integration
        sa_json = '{"type": "service_account", "project_id": "test"}'
        integration = _make_integration(
            provider=LLMProvider.GOOGLE_VERTEX_AI,
            secrets=GcpSecrets(service_account_json=sa_json),
            config=GcpConfig(project_id="my-project", region="us-central1"),
        )

        # When: create credential kwargs
        result = build_credential_kwargs(integration)

        # Then: Vertex AI credential kwargs
        assert result == {
            "vertex_project": "my-project",
            "vertex_location": "us-central1",
            "vertex_credentials": sa_json,
        }

    def test_chatgpt_oauth_secrets(self) -> None:
        """Convert ChatGPT OAuth secrets to Responses client kwargs."""
        integration = _make_integration(
            provider=LLMProvider.CHATGPT_OAUTH,
            secrets=ChatGPTOAuthSecrets(
                access_token="access-token",
                refresh_token="refresh-token",
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(hours=1),
            ),
            config=ChatGPTOAuthConfig(
                account_id="account-id",
                connection_method="device",
                status="connected",
            ),
        )

        result = build_credential_kwargs(integration)

        assert result == {
            "api_key": "access-token",
            "base_url": CHATGPT_OAUTH_BACKEND_BASE_URL,
            "api_base": CHATGPT_OAUTH_BACKEND_BASE_URL,
            "extra_headers": {
                "originator": "azents",
                "user-agent": "azents/0.1.0",
                "ChatGPT-Account-Id": "account-id",
            },
        }

    def test_xai_oauth_secrets(self) -> None:
        """Convert xAI OAuth secrets to Responses client kwargs."""
        integration = _make_integration(
            provider=LLMProvider.XAI_OAUTH,
            secrets=XaiOAuthSecrets(
                access_token="access-token",
                refresh_token="refresh-token",
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(hours=1),
            ),
        )

        result = build_credential_kwargs(integration)

        assert result == {
            "api_key": "access-token",
            "base_url": XAI_API_BASE_URL,
            "api_base": XAI_API_BASE_URL,
            "custom_llm_provider": "xai",
        }
