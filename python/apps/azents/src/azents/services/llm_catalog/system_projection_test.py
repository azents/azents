"""System model catalog projection tests."""

import datetime

from azents.core.enums import LLMCatalogEntryVisibility, LLMProvider
from azents.repos.llm_catalog.data import LiteLLMSourceSnapshot
from azents.services.llm_catalog import project_system_entries


def test_project_system_entries_keeps_xai_credential_modes_separate() -> None:
    """Project the shared xAI model family into distinct provider catalogs."""
    source_snapshot = LiteLLMSourceSnapshot(
        id="source-id",
        source_key="litellm_model_cost",
        source_url=None,
        source_hash="hash",
        model_count=1,
        litellm_version="1.0.0",
        loaded_source="fixture",
        payload={
            "xai/grok-4": {
                "litellm_provider": "xai",
                "mode": "chat",
                "supports_function_calling": True,
                "supports_web_search": True,
            }
        },
        created_at=datetime.datetime.now(datetime.UTC),
    )

    api_key_entries = project_system_entries(
        provider=LLMProvider.XAI,
        source_snapshot=source_snapshot,
    )
    oauth_entries = project_system_entries(
        provider=LLMProvider.XAI_OAUTH,
        source_snapshot=source_snapshot,
    )

    assert len(api_key_entries) == 1
    assert len(oauth_entries) == 1
    assert api_key_entries[0].provider == LLMProvider.XAI
    assert oauth_entries[0].provider == LLMProvider.XAI_OAUTH
    assert api_key_entries[0].provider_model_identifier == "grok-4"
    assert oauth_entries[0].provider_model_identifier == "grok-4"
    assert api_key_entries[0].runtime_model_identifier == "xai/grok-4"
    assert oauth_entries[0].runtime_model_identifier == "xai/grok-4"
    assert api_key_entries[0].publisher == "xai"
    assert oauth_entries[0].publisher == "xai"


def test_project_system_entries_filters_non_chat_models() -> None:
    """System projection keeps unsupported modes hidden, not selectable."""
    source_snapshot = LiteLLMSourceSnapshot(
        id="source-id",
        source_key="litellm_model_cost",
        source_url=None,
        source_hash="hash",
        model_count=2,
        litellm_version="1.0.0",
        loaded_source="fixture",
        payload={
            "gpt-4o": {
                "litellm_provider": "openai",
                "mode": "chat",
                "max_input_tokens": 128000,
                "supports_function_calling": True,
                "supports_web_search": True,
            },
            "dall-e-3": {
                "litellm_provider": "openai",
                "mode": "image_generation",
            },
        },
        created_at=datetime.datetime.now(datetime.UTC),
    )

    entries = project_system_entries(
        provider=LLMProvider.OPENAI,
        source_snapshot=source_snapshot,
    )

    assert len(entries) == 2
    selectable = [
        entry
        for entry in entries
        if entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
    ]
    hidden = [
        entry
        for entry in entries
        if entry.visibility_status == LLMCatalogEntryVisibility.HIDDEN
    ]
    assert selectable[0].provider_model_identifier == "gpt-4o"
    assert selectable[0].normalized_capabilities["built_in_tools"]["supported"] == [
        "web_search"
    ]
    assert hidden[0].provider_model_identifier == "dall-e-3"
    assert hidden[0].hidden_reason == "unsupported_mode:image_generation"
