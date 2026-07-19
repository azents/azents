"""Public LLM Provider Integration data contract tests."""

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from azents.api.public.llm_provider_integration.v1.data import (
    LLMProviderIntegrationCreateRequest,
    LLMProviderIntegrationUpdateRequest,
)


def test_generic_integration_create_excludes_oauth_credentials() -> None:
    """Keep server-owned OAuth tokens out of the public create contract."""
    schema = LLMProviderIntegrationCreateRequest.model_json_schema()
    serialized = json.dumps(schema)

    assert schema["properties"]["provider"]["enum"] == [
        "openai",
        "xai",
        "openrouter",
        "anthropic",
        "google_gemini",
        "aws_bedrock",
        "google_vertex_ai",
    ]
    assert "ChatGPTOAuthSecrets" not in serialized
    assert "XaiOAuthSecrets" not in serialized
    assert "KimiOAuthSecrets" not in serialized

    with pytest.raises(ValidationError):
        LLMProviderIntegrationCreateRequest.model_validate(
            {
                "provider": "kimi_oauth",
                "secrets": {
                    "type": "kimi_oauth",
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_at": "2030-01-01T00:00:00Z",
                    "device_id": "device-id",
                },
                "config": {
                    "type": "kimi_oauth",
                    "connection_method": "device",
                    "status": "connected",
                    "connected_at": "2026-07-19T00:00:00Z",
                    "last_refreshed_at": "2026-07-19T00:00:00Z",
                    "last_failed_at": None,
                    "last_failure_reason": None,
                },
            }
        )


def test_generic_integration_update_excludes_oauth_credentials() -> None:
    """Keep server-owned OAuth tokens out of the public patch contract."""
    schema = TypeAdapter(LLMProviderIntegrationUpdateRequest).json_schema()
    serialized = json.dumps(schema)

    assert "ChatGPTOAuthSecrets" not in serialized
    assert "XaiOAuthSecrets" not in serialized
    assert "KimiOAuthSecrets" not in serialized
    assert "ChatGPTOAuthConfig" not in serialized
    assert "XaiOAuthConfig" not in serialized
    assert "KimiOAuthConfig" not in serialized
