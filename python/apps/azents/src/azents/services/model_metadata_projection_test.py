"""Stored catalogs preserve source identity, provider facts and publication inputs."""

import datetime
import importlib.metadata
import json
from typing import Never

import pytest
from pydantic_ai.providers.openai import OpenAIProvider

from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMModelDeveloper,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.llm_catalog import ModelCapabilities, ModelReasoningEffort
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_catalog_source import (
    CatalogFact,
    CatalogSourceDecodeError,
    decode_catalog_source,
)
from azents.repos.model_metadata_source_data import ModelMetadataSource
from azents.services.model_listing.data import NormalizedModelCandidate
from azents.services.model_metadata_projection import (
    MODEL_METADATA_PROJECTION_SCHEMA_VERSION,
    ModelMetadataProjectionError,
    project_integration_replacement_entries,
    project_system_entries,
    projection_runtime_versions,
    projection_source_expectations,
)
from azents.testing.model_metadata import make_test_source

_DATE = datetime.date(2026, 10, 2)


def _source(rows: dict[str, object]) -> ModelMetadataSource:
    payload = decode_catalog_source(json.dumps(rows).encode())
    return make_test_source(payload)


def _candidate(
    provider: LLMProvider, identifier: str, evidence: ProviderCapabilityEvidence | None
) -> NormalizedModelCandidate:
    return NormalizedModelCandidate(
        provider=provider,
        model_identifier=identifier,
        model_display_name=identifier,
        model_developer=LLMModelDeveloper.OTHER,
        normalized_capabilities=ModelCapabilities(),
        capability_evidence=evidence,
        supported_execution_options=[],
        model_snapshot={"source": "provider"},
        source_metadata={"opaque": "diagnostic"},
    )


def test_system_inventory_uses_source_facts_not_model_names_or_price_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_profile(*args: object, **kwargs: object) -> Never:
        raise AssertionError("System native projection must not query a profile")

    monkeypatch.setattr(OpenAIProvider, "model_profile", reject_profile)
    source = _source(
        {
            "opaque-preview-name": {
                "litellm_provider": "openai",
                "mode": "responses",
                "supports_reasoning": True,
                "reasoning_effort_levels": ["high", "xhigh", "max"],
                "supports_function_calling": True,
            },
            "not-chat": {"litellm_provider": "openai", "mode": "embedding"},
            "chat-only": {
                "litellm_provider": "openai",
                "mode": "chat",
                "supported_endpoints": ["/v1/chat/completions"],
            },
        }
    )
    entries = {
        entry.provider_model_identifier: entry
        for entry in project_system_entries(
            provider=LLMProvider.OPENAI,
            source=source,
            effective_date=_DATE,
        )
    }
    assert (
        entries["opaque-preview-name"].visibility_status
        == LLMCatalogEntryVisibility.SELECTABLE
    )
    assert entries["not-chat"].hidden_reason == "unsupported_model_kind"
    assert entries["chat-only"].hidden_reason == "unsupported_endpoint"
    caps = ModelCapabilities.model_validate(
        entries["opaque-preview-name"].normalized_capabilities
    )
    assert caps.reasoning.effort_levels == [
        ModelReasoningEffort.HIGH,
        ModelReasoningEffort.XHIGH,
        ModelReasoningEffort.MAX,
    ]
    assert caps.semantic_contract is not None
    assert MODEL_METADATA_PROJECTION_SCHEMA_VERSION == "2"
    assert "genai_prices" not in json.dumps(
        entries["opaque-preview-name"].source_metadata
    )


def test_system_gemini_excludes_noncanonical_twins_and_other_hosts() -> None:
    source = _source(
        {
            "gemini/opaque": {"litellm_provider": "gemini", "mode": "chat"},
            "opaque": {"litellm_provider": "gemini", "mode": "chat"},
            "vertex_ai/opaque": {"litellm_provider": "vertex_ai", "mode": "chat"},
            "vertex_ai/claude": {
                "litellm_provider": "vertex_ai-anthropic_models",
                "mode": "chat",
            },
        }
    )
    entries = project_system_entries(
        provider=LLMProvider.GOOGLE_GEMINI, source=source, effective_date=_DATE
    )
    assert [entry.provider_model_identifier for entry in entries] == ["opaque"]


def test_deprecation_uses_the_explicit_operation_date() -> None:
    source = _source(
        {
            "opaque": {
                "litellm_provider": "openai",
                "mode": "responses",
                "deprecation_date": "2026-10-03",
            }
        }
    )
    active = project_system_entries(
        provider=LLMProvider.OPENAI, source=source, effective_date=_DATE
    )[0]
    tomorrow = _DATE + datetime.timedelta(days=1)
    deprecated = project_system_entries(
        provider=LLMProvider.OPENAI, source=source, effective_date=tomorrow
    )[0]
    assert active.lifecycle_status == LLMModelLifecycleStatus.ACTIVE
    assert deprecated.lifecycle_status == LLMModelLifecycleStatus.DEPRECATED
    assert deprecated.visibility_status == LLMCatalogEntryVisibility.HIDDEN
    assert active != deprecated


def test_invalid_lifecycle_fact_is_rejected_before_source_publication() -> None:
    with pytest.raises(CatalogSourceDecodeError):
        _source(
            {
                "opaque": {
                    "litellm_provider": "openai",
                    "mode": "chat",
                    "deprecation_date": "not-a-date",
                }
            }
        )


@pytest.mark.parametrize("source_present", [True, False])
def test_unmatched_integration_model_remains_selectable(source_present: bool) -> None:
    source = (
        _source({"other": {"litellm_provider": "openai", "mode": "chat"}})
        if source_present
        else None
    )
    candidate = _candidate(
        LLMProvider.XAI_OAUTH,
        "opaque/account-model",
        ProviderCapabilityEvidence(
            reasoning_efforts=CatalogFact(
                state="value", value=(ModelReasoningEffort.MAX,)
            ),
            web_search=CatalogFact(state="value", value=True),
        ),
    )
    entries = project_integration_replacement_entries(
        integration_id="i" * 32,
        provider=LLMProvider.XAI_OAUTH,
        candidates=[candidate],
        source=source,
        provider_listing_source="xai_oauth:grok_models",
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry.provider_model_identifier == "opaque/account-model"
    assert entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
    caps = ModelCapabilities.model_validate(entry.normalized_capabilities)
    assert caps.reasoning.effort_levels == [ModelReasoningEffort.MAX]
    assert "web_search" in caps.built_in_tools.supported
    assert "image_generation" in caps.built_in_tools.supported


def test_historical_candidate_default_booleans_do_not_deny_new_source_evidence() -> (
    None
):
    source = _source(
        {
            "openrouter/vendor/model": {
                "litellm_provider": "openrouter",
                "mode": "chat",
                "supports_function_calling": True,
                "supports_reasoning": True,
                "reasoning_effort_levels": ["high"],
            }
        }
    )
    entries = project_integration_replacement_entries(
        integration_id="i" * 32,
        provider=LLMProvider.OPENROUTER,
        candidates=[_candidate(LLMProvider.OPENROUTER, "vendor/model", None)],
        source=source,
        provider_listing_source="openrouter:models_user",
    )
    caps = ModelCapabilities.model_validate(entries[0].normalized_capabilities)
    assert caps.tool_calling.supported is True
    assert caps.reasoning.effort_levels == [ModelReasoningEffort.HIGH]


def test_provider_false_and_complete_empty_override_source_controls() -> None:
    source = _source(
        {
            "openrouter/vendor/model": {
                "litellm_provider": "openrouter",
                "mode": "chat",
                "supports_function_calling": True,
                "supports_reasoning": True,
                "reasoning_effort_levels": ["high", "max"],
            }
        }
    )
    entry = project_integration_replacement_entries(
        integration_id="i" * 32,
        provider=LLMProvider.OPENROUTER,
        candidates=[
            _candidate(
                LLMProvider.OPENROUTER,
                "vendor/model",
                ProviderCapabilityEvidence(
                    function_calling=CatalogFact(state="value", value=False),
                    reasoning_efforts=CatalogFact(state="value", value=()),
                ),
            )
        ],
        source=source,
        provider_listing_source="openrouter:models_user",
    )[0]
    caps = ModelCapabilities.model_validate(entry.normalized_capabilities)
    assert caps.tool_calling.supported is False
    assert caps.reasoning.supported is True
    assert caps.reasoning.effort_levels == []


def test_preparation_captures_exact_values_and_absent_adopted_keys() -> None:
    candidates = [
        _candidate(LLMProvider.XAI, "a", ProviderCapabilityEvidence()),
        _candidate(LLMProvider.XAI, "b", ProviderCapabilityEvidence()),
    ]
    source = _source({"xai/a": {"litellm_provider": "xai", "max_input_tokens": 10}})
    before = projection_source_expectations(
        provider=LLMProvider.XAI, candidates=candidates, source=source
    )
    assert [item.source_model_key for item in before] == ["xai/a", "xai/b"]
    assert before[0].current is not None
    assert before[1].current is None
    assert before == projection_source_expectations(
        provider=LLMProvider.XAI, candidates=list(reversed(candidates)), source=source
    )
    changed = _source({"xai/a": {"litellm_provider": "xai", "max_input_tokens": 20}})
    assert before != projection_source_expectations(
        provider=LLMProvider.XAI, candidates=candidates, source=changed
    )


def test_projection_describes_only_relevant_runtime_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = projection_runtime_versions(LLMProvider.OPENAI)
    anthropic_before = projection_runtime_versions(LLMProvider.ANTHROPIC)
    installed = importlib.metadata.version
    monkeypatch.setattr(
        "azents.services.model_metadata_projection.importlib.metadata.version",
        lambda name: "changed" if name == "pydantic-ai-slim" else installed(name),
    )
    assert projection_runtime_versions(LLMProvider.OPENAI) == before
    assert projection_runtime_versions(LLMProvider.ANTHROPIC) != anthropic_before
    monkeypatch.setattr(
        "azents.services.model_metadata_projection.importlib.metadata.version",
        lambda name: "changed-sdk" if name == "openai" else installed(name),
    )
    assert projection_runtime_versions(LLMProvider.OPENAI) != before


def test_projection_rejects_missing_system_namespace() -> None:
    source = _source({"opaque": {"litellm_provider": "openai", "mode": "chat"}})
    with pytest.raises(ModelMetadataProjectionError, match="missing provider"):
        project_system_entries(
            provider=LLMProvider.ANTHROPIC, source=source, effective_date=_DATE
        )
