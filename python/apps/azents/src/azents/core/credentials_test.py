"""Credential type tests."""

import datetime

from pydantic import TypeAdapter

from azents.core.credentials import (
    PROVIDER_SECRET_TYPES,
    PROVIDERS_WITH_CONFIG,
    ApiKeySecrets,
    ChatGPTOAuthConfig,
    ChatGPTOAuthSecrets,
    ProviderConfig,
    ProviderSecrets,
    XaiOAuthConfig,
    XaiOAuthSecrets,
)
from azents.core.enums import LLMProvider


def test_chatgpt_oauth_secrets_parse_from_provider_union() -> None:
    """ProviderSecrets union parses ChatGPT OAuth secret."""
    expires_at = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
    adapter = TypeAdapter(ProviderSecrets)

    secrets = adapter.validate_python(
        {
            "type": "chatgpt_oauth",
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "id_token": "id-token",
            "expires_at": expires_at,
        }
    )

    assert isinstance(secrets, ChatGPTOAuthSecrets)
    assert secrets.access_token == "access-token"
    assert secrets.refresh_token == "refresh-token"
    assert secrets.id_token == "id-token"
    assert secrets.expires_at == expires_at


def test_chatgpt_oauth_config_parse_from_provider_union() -> None:
    """ProviderConfig union parses ChatGPT OAuth config."""
    connected_at = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
    adapter = TypeAdapter(ProviderConfig)

    config = adapter.validate_python(
        {
            "type": "chatgpt_oauth",
            "account_id": "account-123",
            "email": "user@example.com",
            "plan_type": "plus",
            "connection_method": "device",
            "status": "connected",
            "connected_at": connected_at,
        }
    )

    assert isinstance(config, ChatGPTOAuthConfig)
    assert config.account_id == "account-123"
    assert config.email == "user@example.com"
    assert config.plan_type == "plus"
    assert config.connection_method == "device"
    assert config.status == "connected"
    assert config.connected_at == connected_at


def test_chatgpt_oauth_provider_mappings() -> None:
    """Provider mapping includes ChatGPT OAuth."""
    assert PROVIDER_SECRET_TYPES[LLMProvider.CHATGPT_OAUTH] == "chatgpt_oauth"
    assert LLMProvider.CHATGPT_OAUTH in PROVIDERS_WITH_CONFIG


def test_xai_api_key_provider_mappings() -> None:
    """Provider mapping uses generic API key secrets for stable xAI."""
    assert PROVIDER_SECRET_TYPES[LLMProvider.XAI] == "api_key"
    assert LLMProvider.XAI not in PROVIDERS_WITH_CONFIG


def test_openrouter_provider_mappings() -> None:
    """Provider mapping uses generic API key secrets for OpenRouter."""
    assert PROVIDER_SECRET_TYPES[LLMProvider.OPENROUTER] == "api_key"
    assert LLMProvider.OPENROUTER not in PROVIDERS_WITH_CONFIG


def test_xai_api_key_secrets_parse_from_provider_union() -> None:
    """ProviderSecrets union parses the generic API key secret used by xAI."""
    adapter = TypeAdapter(ProviderSecrets)

    secrets = adapter.validate_python({"type": "api_key", "api_key": "fake-xai-key"})

    assert isinstance(secrets, ApiKeySecrets)
    assert secrets.api_key == "fake-xai-key"


def test_xai_oauth_secrets_parse_from_provider_union() -> None:
    """ProviderSecrets union parses xAI OAuth secret."""
    expires_at = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
    adapter = TypeAdapter(ProviderSecrets)

    secrets = adapter.validate_python(
        {
            "type": "xai_oauth",
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "id_token": "id-token",
            "expires_at": expires_at,
        }
    )

    assert isinstance(secrets, XaiOAuthSecrets)
    assert secrets.access_token == "access-token"
    assert secrets.refresh_token == "refresh-token"
    assert secrets.id_token == "id-token"
    assert secrets.expires_at == expires_at


def test_xai_oauth_config_parse_from_provider_union() -> None:
    """ProviderConfig union parses xAI OAuth config."""
    connected_at = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
    adapter = TypeAdapter(ProviderConfig)

    config = adapter.validate_python(
        {
            "type": "xai_oauth",
            "account_id": "account-123",
            "email": "user@example.com",
            "connection_method": "device",
            "status": "entitlement_denied",
            "entitlement_status": "denied",
            "connected_at": connected_at,
        }
    )

    assert isinstance(config, XaiOAuthConfig)
    assert config.account_id == "account-123"
    assert config.email == "user@example.com"
    assert config.connection_method == "device"
    assert config.status == "entitlement_denied"
    assert config.entitlement_status == "denied"
    assert config.connected_at == connected_at


def test_xai_oauth_provider_mappings() -> None:
    """Provider mapping includes xAI OAuth."""
    assert PROVIDER_SECRET_TYPES[LLMProvider.XAI_OAUTH] == "xai_oauth"
    assert LLMProvider.XAI_OAUTH in PROVIDERS_WITH_CONFIG
