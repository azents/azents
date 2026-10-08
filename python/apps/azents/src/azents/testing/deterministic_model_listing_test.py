"""Tests for deterministic model listing fixtures."""

import dataclasses
import json

import pytest

from azents.core.active_model_capabilities import (
    CapturedStoredChoice,
    CompiledActiveChoice,
    ConfiguredModelIdentity,
    compile_capture,
)
from azents.core.agent import AgentModelSelection
from azents.core.enums import LLMProvider
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelModality,
    ModelReasoningEffort,
)
from azents.core.model_capability_contract import ModelCapabilityFeature
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.engine.events.effective_model_request import (
    normalize_effective_model_request,
)
from azents.engine.events.model_support_contract import validate_saved_model_request
from azents.repos.llm_catalog.data import LLMCatalogEntryCreate
from azents.services.llm_catalog import project_deterministic_integration_entries
from azents.services.model_listing.data import NormalizedModelCandidate
from azents.testing.deterministic_model_listing import (
    build_deterministic_listing,
    parse_deterministic_fixture_variant,
)


def test_plain_title_fixture_is_an_exact_openai_candidate() -> None:
    """Keep the known no-schema title scenario separate from baseline models."""
    variant = parse_deterministic_fixture_variant(
        "__testenv_model_listing:deterministic-title-plain"
    )
    assert variant == "deterministic-title-plain"
    listing = build_deterministic_listing(
        variant=variant,
        provider=LLMProvider.OPENAI,
        integration_id="plain-title-integration",
    )
    assert listing.summary.returned_count == 1
    assert listing.summary.skipped_count == 0
    assert listing.models[0].model_identifier == "gpt-5.5-title-plain"
    metadata = listing.models[0].source_metadata
    assert metadata is not None
    assert metadata["fixture_lightweight"] is True
    with pytest.raises(ValueError, match="requires provider=openai"):
        build_deterministic_listing(
            variant=variant,
            provider=LLMProvider.ANTHROPIC,
            integration_id="wrong-provider",
        )


def test_model_settings_fixture_exposes_supported_and_unsupported_tools() -> None:
    """Expose one hosted-tool model and one model without built-in tools."""
    variant = parse_deterministic_fixture_variant(
        "__testenv_model_listing:deterministic-model-settings"
    )

    assert variant == "deterministic-model-settings"
    listing = build_deterministic_listing(
        variant=variant,
        provider=LLMProvider.OPENAI,
        integration_id="integration-id",
    )

    by_identifier = {model.model_identifier: model for model in listing.models}
    assert by_identifier[
        "gpt-5.5"
    ].normalized_capabilities.built_in_tools.supported == [
        "web_search",
        "image_generation",
    ]
    assert (
        by_identifier["gpt-5.5-mini"].normalized_capabilities.built_in_tools.supported
        == []
    )


def test_context_ranges_fixture_exposes_default_and_maximum() -> None:
    """Expose a split main range and a maximum-only lightweight range."""
    variant = parse_deterministic_fixture_variant(
        "__testenv_model_listing:deterministic-context-ranges"
    )

    assert variant == "deterministic-context-ranges"
    listing = build_deterministic_listing(
        variant=variant,
        provider=LLMProvider.OPENAI,
        integration_id="integration-id",
    )

    main, lightweight = listing.models
    assert main.normalized_capabilities.context_window.default_input_tokens == 96_000
    assert main.normalized_capabilities.context_window.max_input_tokens == 256_000
    assert (
        lightweight.normalized_capabilities.context_window.default_input_tokens is None
    )
    assert (
        lightweight.normalized_capabilities.context_window.max_input_tokens == 512_000
    )


def test_openrouter_fixture_preserves_known_and_unknown_publishers() -> None:
    """Expose broad OpenRouter model ids with conservative capabilities."""
    variant = parse_deterministic_fixture_variant(
        "__testenv_model_listing:deterministic-openrouter"
    )

    assert variant == "deterministic-openrouter"
    listing = build_deterministic_listing(
        variant=variant,
        provider=LLMProvider.OPENROUTER,
        integration_id="integration-id",
    )

    by_identifier = {model.model_identifier: model for model in listing.models}
    known = by_identifier["anthropic/claude-sonnet-4.6"]
    unknown = by_identifier["new-publisher/frontier-text"]

    assert known.model_developer.value == "anthropic"
    assert unknown.model_developer.value == "other"
    assert known.normalized_capabilities.modalities.input == ["text", "image"]
    assert unknown.normalized_capabilities.built_in_tools.supported == ["web_search"]
    assert listing.summary.returned_count == 2
    assert listing.summary.skipped_count == 1


def test_model_settings_fixture_adds_astra_sol_without_changing_old_models() -> None:
    """Expose premium-speed models in the existing deterministic fixture mode."""
    listing = build_deterministic_listing(
        variant="deterministic-model-settings",
        provider=LLMProvider.OPENAI,
        integration_id="integration-id",
    )
    by_identifier = {model.model_identifier: model for model in listing.models}
    assert listing.summary.returned_count == 4
    assert listing.summary.skipped_count == 1
    assert by_identifier["gpt-5.5"].supported_execution_options == [
        ModelExecutionOptionId.FAST
    ]
    assert by_identifier["gpt-5.5-mini"].supported_execution_options == []
    for identifier, name in (
        ("gpt-6-astra", "GPT 6 Astra Deterministic"),
        ("gpt-5.6-sol", "GPT 5.6 Sol Deterministic"),
    ):
        model = by_identifier[identifier]
        assert model.model_display_name == name
        assert model.supported_execution_options == [
            ModelExecutionOptionId.FAST,
            ModelExecutionOptionId.ULTRAFAST,
        ]
        assert {
            ModelReasoningEffort.XHIGH,
            ModelReasoningEffort.HIGH,
        } <= set(model.normalized_capabilities.reasoning.effort_levels)
        assert model.normalized_capabilities.context_window.max_input_tokens == 128_000
        assert model.normalized_capabilities.context_window.max_output_tokens == 16_000
        assert model.model_snapshot["fixture_variant"] == "deterministic-model-settings"


@pytest.mark.parametrize(
    "provider", [LLMProvider.CHATGPT_OAUTH, LLMProvider.XAI, LLMProvider.OPENROUTER]
)
def test_model_settings_fixture_leaves_other_providers_unchanged(
    provider: LLMProvider,
) -> None:
    """The additive API fixture does not invent another provider's speed support."""
    listing = build_deterministic_listing(
        variant="deterministic-model-settings",
        provider=provider,
        integration_id="integration-id",
    )
    assert listing.summary.returned_count == 2
    assert all(model.supported_execution_options == [] for model in listing.models)


@dataclasses.dataclass(frozen=True)
class _Capture:
    choices: tuple[CapturedStoredChoice, ...]


def _active_choice(
    entry: LLMCatalogEntryCreate, candidate: NormalizedModelCandidate
) -> CompiledActiveChoice:
    """Replay the actual published envelope, with deliberately stale saved flags."""
    selection = AgentModelSelection(
        llm_provider_integration_id="integration-id",
        provider=candidate.provider,
        model_identifier=candidate.model_identifier,
        model_display_name=candidate.model_display_name,
        model_developer=candidate.model_developer,
        normalized_capabilities=ModelCapabilities(),
        pricing=entry.pricing,
        model_snapshot=candidate.model_snapshot,
    )
    capture = _Capture(
        choices=(
            CapturedStoredChoice(
                identity=ConfiguredModelIdentity.from_selection(selection),
                source_metadata=json.loads(json.dumps(entry.source_metadata)),
                source_models=(),
                supported_execution_options=tuple(
                    candidate.supported_execution_options
                ),
                model_developer=candidate.model_developer,
                catalog_id="synthetic-catalog-id",
            ),
        )
    )
    compiled = compile_capture(capture, selections=[selection])
    [outcome] = compiled.outcomes
    assert isinstance(outcome, CompiledActiveChoice)
    assert not selection.normalized_capabilities.tool_calling.supported
    return outcome


@pytest.mark.parametrize(
    "variant",
    [
        "deterministic-success",
        "deterministic-model-settings",
        "deterministic-brave-text-only",
    ],
)
def test_fixture_publication_capture_and_active_dispatch_share_authoritative_facts(
    variant: str,
) -> None:
    parsed = parse_deterministic_fixture_variant(f"__testenv_model_listing:{variant}")
    assert parsed is not None
    listing = build_deterministic_listing(
        variant=parsed, provider=LLMProvider.OPENAI, integration_id="integration-id"
    )
    entries = project_deterministic_integration_entries(
        integration_id="integration-id",
        provider=LLMProvider.OPENAI,
        listing=listing,
        source=None,
    )
    for entry, candidate in zip(entries, listing.models, strict=True):
        assert candidate.capability_evidence is not None
        assert entry.source_metadata is not None
        assert entry.source_metadata["capability_evidence"] == (
            candidate.capability_evidence.model_dump(mode="json")
        )
        published = ModelCapabilities.model_validate(entry.normalized_capabilities)
        active = _active_choice(entry, candidate)
        assert active.capabilities == published == candidate.normalized_capabilities
        assert active.capabilities.supports(ModelCapabilityFeature.FUNCTION_CALLING)
        request = normalize_effective_model_request(
            dialect="native_responses",
            options={
                "tools": [
                    {
                        "type": "function",
                        "name": "tool_search",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ]
            },
            parameters=None,
            native_tools=None,
        )
        validate_saved_model_request(active.capabilities, request=request)
        expected_tools = (
            ["web_search", "image_generation"]
            if variant == "deterministic-model-settings"
            and candidate.model_identifier != "gpt-5.5-mini"
            else []
        )
        assert active.capabilities.built_in_tools.supported == expected_tools
        assert active.supported_execution_options == tuple(
            candidate.supported_execution_options
        )


@pytest.mark.parametrize("provider", list(LLMProvider))
def test_provider_core_fixture_declarations_survive_publication_and_active_capture(
    provider: LLMProvider,
) -> None:
    listing = build_deterministic_listing(
        variant="deterministic-provider-core",
        provider=provider,
        integration_id="integration-id",
    )
    entries = project_deterministic_integration_entries(
        integration_id="integration-id",
        provider=provider,
        listing=listing,
        source=None,
    )
    for entry, candidate in zip(entries, listing.models, strict=True):
        assert candidate.capability_evidence is not None
        active = _active_choice(entry, candidate)
        published = ModelCapabilities.model_validate(entry.normalized_capabilities)
        assert active.capabilities == published == candidate.normalized_capabilities
        image_output = candidate.model_identifier == "gemini-3.1-flash-image-preview"
        assert active.capabilities.tool_calling.supported is (not image_output)
        assert (
            ModelModality.IMAGE in active.capabilities.modalities.output
        ) is image_output
        assert active.capabilities.reasoning.supported is False
        assert active.capabilities.reasoning.effort_levels == []


def test_deterministic_projector_does_not_replace_compiled_facts_with_stale_flags() -> (
    None
):
    listing = build_deterministic_listing(
        variant="deterministic-model-settings",
        provider=LLMProvider.OPENAI,
        integration_id="integration-id",
    )
    listing.models = [
        candidate.model_copy(update={"normalized_capabilities": ModelCapabilities()})
        for candidate in listing.models
    ]
    entries = project_deterministic_integration_entries(
        integration_id="integration-id",
        provider=LLMProvider.OPENAI,
        listing=listing,
        source=None,
    )
    for entry, candidate in zip(entries, listing.models, strict=True):
        published = ModelCapabilities.model_validate(entry.normalized_capabilities)
        assert published.tool_calling.supported is True
        assert _active_choice(entry, candidate).capabilities == published
