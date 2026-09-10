"""Public LLM Provider Integration data contract tests."""

import json
from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from azents.api.public.llm_provider_integration.v1.data import (
    ImageGenerationModelCatalogResponse,
    LLMProviderIntegrationCreateRequest,
    LLMProviderIntegrationUpdateRequest,
)
from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.services.image_generation_catalog.data import (
    ImageGenerationCatalogAttemptOutput,
    ImageGenerationCatalogEntryOutput,
    ImageGenerationModelCatalogOutput,
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


def test_image_generation_catalog_response_projects_only_safe_stored_data() -> None:
    """Expose registry and sanitized attempt metadata without credentials."""
    now = datetime.now(timezone.utc)
    response = ImageGenerationModelCatalogResponse.convert_from(
        ImageGenerationModelCatalogOutput(
            default_available=True,
            explicit_selection_supported=True,
            catalog_id="catalog",
            snapshot_id="snapshot",
            snapshot_configuration_version=2,
            current_configuration_version=2,
            snapshot_created_at=now,
            latest_attempt=ImageGenerationCatalogAttemptOutput(
                id="attempt",
                status="succeeded",
                started_at=now,
                finished_at=now,
                failure_code=None,
                failure_message=None,
                action_hint=None,
                fetched_count=5,
                matched_count=1,
                skipped_count=4,
                hidden_count=0,
            ),
            stale=False,
            generation_current=True,
            sync_available_at=None,
            automatic_retry_blocked=False,
            entries=[
                ImageGenerationCatalogEntryOutput(
                    id="entry",
                    provider=LLMProvider.OPENAI,
                    provider_model_identifier="gpt-image-2.5-flare",
                    display_name="GPT Image 2.5 Flare",
                    description="Recommended for fast, cost-balanced image generation.",
                    recommendation_rank=1,
                    lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                    visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                    source_metadata={"provider": "openai"},
                    projection_metadata={"registry_revision": 1},
                )
            ],
            total=1,
        )
    )

    assert response.model_dump() == {
        "default_available": True,
        "explicit_selection_supported": True,
        "catalog_id": "catalog",
        "snapshot_id": "snapshot",
        "snapshot_configuration_version": 2,
        "current_configuration_version": 2,
        "snapshot_created_at": now,
        "latest_attempt": {
            "id": "attempt",
            "status": "succeeded",
            "started_at": now,
            "finished_at": now,
            "failure_code": None,
            "failure_message": None,
            "action_hint": None,
            "fetched_count": 5,
            "matched_count": 1,
            "skipped_count": 4,
            "hidden_count": 0,
        },
        "stale": False,
        "generation_current": True,
        "sync_available_at": None,
        "automatic_retry_blocked": False,
        "entries": [
            {
                "id": "entry",
                "provider": LLMProvider.OPENAI,
                "provider_model_identifier": "gpt-image-2.5-flare",
                "display_name": "GPT Image 2.5 Flare",
                "description": (
                    "Recommended for fast, cost-balanced image generation."
                ),
                "recommendation_rank": 1,
                "lifecycle_status": "active",
                "visibility_status": "selectable",
                "source_metadata": {"provider": "openai"},
                "projection_metadata": {"registry_revision": 1},
            }
        ],
        "total": 1,
    }
