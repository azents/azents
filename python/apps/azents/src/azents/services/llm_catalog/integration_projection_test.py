"""Integration model catalog projection tests."""

import datetime

from azents.core.enums import LLMCatalogEntryVisibility, LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities, ModelCompatibilityCapabilities
from azents.repos.llm_catalog.data import LiteLLMSourceSnapshot
from azents.services.llm_catalog import (
    project_chatgpt_integration_entries,
    project_integration_entries,
    project_openrouter_integration_entries,
)
from azents.services.model_listing.data import (
    ModelListingOutput,
    ModelListingSummary,
    NormalizedModelCandidate,
)


def test_project_integration_entries_requires_exact_target_projection() -> None:
    """Integration projection exposes exact matches and hides missing target keys."""
    fetched_at = datetime.datetime.now(datetime.UTC)
    listing = ModelListingOutput(
        models=[
            NormalizedModelCandidate(
                provider=LLMProvider.AWS_BEDROCK,
                model_identifier="anthropic.claude-3-haiku-20240307-v1:0",
                model_display_name="Claude 3 Haiku",
                model_developer=LLMModelDeveloper.ANTHROPIC,
                model_family="claude",
                normalized_capabilities=ModelCapabilities(),
                model_snapshot={},
                source_metadata=None,
                last_refreshed_at=fetched_at,
            ),
            NormalizedModelCandidate(
                provider=LLMProvider.AWS_BEDROCK,
                model_identifier="unmatched.model-v1",
                model_display_name="Unmatched",
                model_developer=LLMModelDeveloper.ANTHROPIC,
                model_family="unmatched",
                normalized_capabilities=ModelCapabilities(),
                model_snapshot={},
                source_metadata=None,
                last_refreshed_at=fetched_at,
            ),
        ],
        summary=ModelListingSummary(
            source="aws_bedrock:list_foundation_models",
            fetched_at=fetched_at,
            returned_count=2,
            skipped_count=0,
        ),
        skips=[],
    )
    source_snapshot = LiteLLMSourceSnapshot(
        id="source-id",
        source_key="litellm_model_cost",
        source_url=None,
        source_hash="hash",
        model_count=1,
        litellm_version="1.0.0",
        loaded_source="fixture",
        payload={
            "bedrock/anthropic.claude-3-haiku-20240307-v1:0": {
                "litellm_provider": "bedrock",
                "mode": "chat",
                "supports_function_calling": True,
            }
        },
        created_at=fetched_at,
    )

    entries = project_integration_entries(
        integration_id="integration-id",
        provider=LLMProvider.AWS_BEDROCK,
        listing=listing,
        source_snapshot=source_snapshot,
    )

    assert entries[0].visibility_status == LLMCatalogEntryVisibility.SELECTABLE
    assert entries[0].runtime_model_identifier == (
        "bedrock/anthropic.claude-3-haiku-20240307-v1:0"
    )
    assert entries[1].visibility_status == LLMCatalogEntryVisibility.HIDDEN
    assert entries[1].hidden_reason == "missing_target_projection"


def test_project_chatgpt_entries_does_not_require_litellm_metadata() -> None:
    """ChatGPT backend models remain selectable without LiteLLM projection keys."""
    fetched_at = datetime.datetime.now(datetime.UTC)
    listing = ModelListingOutput(
        models=[
            NormalizedModelCandidate(
                provider=LLMProvider.CHATGPT_OAUTH,
                model_identifier="gpt-5.6-luna",
                model_display_name="GPT-5.6 Luna",
                model_developer=LLMModelDeveloper.OPENAI,
                model_family="gpt-5.6",
                normalized_capabilities=ModelCapabilities(
                    compatibility=ModelCompatibilityCapabilities(
                        provider_family="chatgpt",
                        responses_api=True,
                    )
                ),
                model_snapshot={},
                source_metadata={"context_window": 272000},
                last_refreshed_at=fetched_at,
            )
        ],
        summary=ModelListingSummary(
            source="chatgpt:codex_models",
            fetched_at=fetched_at,
            returned_count=1,
            skipped_count=0,
        ),
        skips=[],
    )

    entries = project_chatgpt_integration_entries(
        integration_id="integration-id",
        listing=listing,
        source_hash="source-hash",
    )

    [entry] = entries
    assert entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
    assert entry.runtime_model_identifier == "gpt-5.6-luna"
    assert entry.normalized_capabilities["compatibility"] == {
        "provider_family": "chatgpt",
        "responses_api": True,
        "unsupported_media_policy": None,
    }
    assert entry.projection_metadata == {
        "lowerer_target": "litellm",
        "freshness_rank": 5060,
    }


def test_project_openrouter_entries_does_not_require_litellm_metadata() -> None:
    """OpenRouter account models remain selectable without target metadata."""
    fetched_at = datetime.datetime.now(datetime.UTC)
    listing = ModelListingOutput(
        models=[
            NormalizedModelCandidate(
                provider=LLMProvider.OPENROUTER,
                model_identifier="new-publisher/new-model",
                model_display_name="New Model",
                model_developer=LLMModelDeveloper.OTHER,
                model_family="new",
                normalized_capabilities=ModelCapabilities(
                    compatibility=ModelCompatibilityCapabilities(
                        provider_family="openrouter",
                        responses_api=True,
                    )
                ),
                model_snapshot={},
                source_metadata={"supported_parameters": []},
                last_refreshed_at=fetched_at,
            )
        ],
        summary=ModelListingSummary(
            source="openrouter:account_models",
            fetched_at=fetched_at,
            returned_count=1,
            skipped_count=0,
        ),
        skips=[],
    )

    entries = project_openrouter_integration_entries(
        integration_id="integration-id",
        listing=listing,
        source_hash="source-hash",
    )

    [entry] = entries
    assert entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
    assert entry.provider_model_identifier == "new-publisher/new-model"
    assert entry.runtime_model_identifier == "openrouter/new-publisher/new-model"
    assert entry.publisher == "other"
    assert entry.hidden_reason is None
    assert entry.projection_metadata == {
        "lowerer_target": "litellm",
        "target_metadata_match_required": False,
        "freshness_rank": 0,
    }
