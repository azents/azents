"""LLM mapping function tests."""

import datetime

from azents.core.chatgpt_oauth import CHATGPT_OAUTH_BACKEND_BASE_URL
from azents.core.credentials import (
    ApiKeySecrets,
    AwsConfig,
    AwsSecrets,
    ChatGPTOAuthConfig,
    ChatGPTOAuthSecrets,
    GcpConfig,
    GcpSecrets,
    KimiOAuthConfig,
    KimiOAuthSecrets,
    ProviderConfig,
    ProviderSecrets,
    XaiOAuthSecrets,
)
from azents.core.enums import LLMProvider
from azents.core.kimi_oauth import KIMI_CODE_API_BASE_URL
from azents.core.llm_mapping import build_credential_kwargs
from azents.core.openrouter import OPENROUTER_API_BASE_URL, OPENROUTER_APP_TITLE
from azents.core.xai import XAI_API_BASE_URL
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationWithSecrets,
)
from azents.testing.types import is_string_object_dict


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
        catalog_configuration_version=1,
    )


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
        }

    def test_kimi_oauth_secrets(self) -> None:
        """Convert Kimi OAuth secrets to the official compatible client settings."""
        now = datetime.datetime.now(datetime.UTC)
        integration = _make_integration(
            provider=LLMProvider.KIMI_OAUTH,
            secrets=KimiOAuthSecrets(
                access_token="kimi-access-token",
                refresh_token="kimi-refresh-token",
                expires_at=now + datetime.timedelta(hours=1),
                device_id="kimi-device-id",
            ),
            config=KimiOAuthConfig(
                connection_method="device",
                status="connected",
                connected_at=now,
                last_refreshed_at=now,
                last_failed_at=None,
                last_failure_reason=None,
            ),
        )

        result = build_credential_kwargs(integration)

        assert result["api_key"] == "kimi-access-token"
        assert result["base_url"] == KIMI_CODE_API_BASE_URL
        headers = result["extra_headers"]
        assert is_string_object_dict(headers)
        assert headers["X-Msh-Platform"] == "kimi_cli"
        assert headers["X-Msh-Device-Id"] == "kimi-device-id"
