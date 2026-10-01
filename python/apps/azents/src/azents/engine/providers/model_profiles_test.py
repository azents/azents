"""Shared runtime model profile authority tests."""

from decimal import Decimal

from pydantic_ai.native_tools import ImageGenerationTool, WebSearchTool

from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelModality, ModelReasoningEffort
from azents.core.model_metadata_source import (
    SourceEqualsClause,
    SourceModelRecord,
    SourcePriceSet,
    SourceScalarPrice,
)
from azents.engine.providers.model_profiles import (
    RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
    resolve_runtime_model_profile,
)


def _source_model(
    identifier: str,
    *,
    web_search: bool = False,
) -> SourceModelRecord:
    prices = (
        {"web_searches_kcount": SourceScalarPrice(value=Decimal("1"))}
        if web_search
        else {}
    )
    return SourceModelRecord(
        id=identifier,
        name=identifier,
        match=SourceEqualsClause(value=identifier),
        context_window=128_000,
        deprecated=False,
        prices=[SourcePriceSet(constraint=None, prices=prices)],
    )


def test_compatible_responses_profile_preserves_runtime_overrides() -> None:
    """OpenAI-compatible providers retain the reviewed runtime profile."""
    resolution = resolve_runtime_model_profile(
        provider=LLMProvider.XAI,
        model="grok-4.20",
        profile_model="grok-4.20",
        assembly_metadata=None,
        context_window=None,
        context_window_explicit=False,
        source_model=None,
    )

    assert resolution.protocol == "responses"
    assert resolution.model_kind == "openai_responses"
    assert resolution.resolver_revision == RUNTIME_MODEL_PROFILE_RESOLVER_REVISION
    assert resolution.profile["supports_tools"] is True
    assert resolution.profile["supports_json_schema_output"] is True
    assert resolution.profile["supports_thinking"] is True
    assert resolution.profile["supported_native_tools"] == frozenset({WebSearchTool})
    assert resolution.normalized_capabilities.tool_calling.supported is True
    assert resolution.normalized_capabilities.reasoning.supported is True


def test_explicit_context_disables_implicit_global_authority() -> None:
    """The shared profile can explicitly carry known or absent context authority."""
    known = resolve_runtime_model_profile(
        provider=LLMProvider.ANTHROPIC,
        model="claude-sonnet-4-6",
        profile_model="claude-sonnet-4-6",
        assembly_metadata=None,
        context_window=200_000,
        context_window_explicit=True,
        source_model=None,
    )
    absent = resolve_runtime_model_profile(
        provider=LLMProvider.ANTHROPIC,
        model="unknown-claude",
        profile_model="unknown-claude",
        assembly_metadata=None,
        context_window=None,
        context_window_explicit=True,
        source_model=None,
    )

    assert known.profile["context_window"] == 200_000
    assert known.normalized_capabilities.context_window.max_input_tokens == 200_000
    assert "context_window" in absent.profile
    assert absent.profile["context_window"] is None


def test_google_profile_intersects_native_tools_with_model_support() -> None:
    """Catalog claims and runtime construction share the native-tool intersection."""
    resolution = resolve_runtime_model_profile(
        provider=LLMProvider.GOOGLE_GEMINI,
        model="gemini-3.1-pro",
        profile_model="gemini-3.1-pro",
        assembly_metadata=None,
        context_window=1_000_000,
        context_window_explicit=True,
        source_model=_source_model("gemini-3.1-pro"),
    )

    assert resolution.protocol == "google"
    assert resolution.profile["supported_native_tools"] == frozenset(
        {WebSearchTool, ImageGenerationTool}
    )
    assert resolution.normalized_capabilities.built_in_tools.supported == [
        "web_search",
        "image_generation",
    ]


def test_native_openai_route_uses_responses_profile_without_factory_dispatch() -> None:
    """Native OpenAI receives catalog profile evidence without changing its adapter."""
    resolution = resolve_runtime_model_profile(
        provider=LLMProvider.OPENAI,
        model="gpt-5.4",
        profile_model="gpt-5.4",
        assembly_metadata=None,
        context_window=400_000,
        context_window_explicit=True,
        source_model=_source_model("gpt-5.4", web_search=True),
    )

    assert resolution.protocol == "responses"
    assert resolution.model_kind == "native_openai_responses"
    assert resolution.normalized_capabilities.context_window.max_input_tokens == (
        400_000
    )


def test_native_openai_capabilities_follow_product_policy() -> None:
    """Native OpenAI projection uses exact model policy, not class-level tools."""
    o1_mini = resolve_runtime_model_profile(
        provider=LLMProvider.OPENAI,
        model="o1-mini",
        profile_model="o1-mini",
        assembly_metadata=None,
        context_window=128_000,
        context_window_explicit=True,
        source_model=_source_model("o1-mini"),
    ).normalized_capabilities
    gpt_4o = resolve_runtime_model_profile(
        provider=LLMProvider.OPENAI,
        model="gpt-4o",
        profile_model="gpt-4o",
        assembly_metadata=None,
        context_window=128_000,
        context_window_explicit=True,
        source_model=_source_model("gpt-4o", web_search=True),
    ).normalized_capabilities
    gpt_54 = resolve_runtime_model_profile(
        provider=LLMProvider.OPENAI,
        model="gpt-5.4",
        profile_model="gpt-5.4",
        assembly_metadata=None,
        context_window=1_050_000,
        context_window_explicit=True,
        source_model=_source_model("gpt-5.4", web_search=True),
    ).normalized_capabilities

    assert o1_mini.tool_calling.supported is False
    assert o1_mini.built_in_tools.supported == []
    assert o1_mini.modalities.input == [ModelModality.TEXT]
    assert gpt_4o.built_in_tools.supported == [
        "web_search",
        "image_generation",
    ]
    assert gpt_4o.modalities.input == [
        ModelModality.TEXT,
        ModelModality.IMAGE,
        ModelModality.PDF,
    ]
    assert gpt_54.reasoning.effort_levels == [
        ModelReasoningEffort.NONE,
        ModelReasoningEffort.MINIMAL,
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    ]
    assert gpt_54.parameters.temperature is False
    assert gpt_54.parameters.max_output_tokens is True


def test_anthropic_effort_and_media_policy_matches_runtime_profile() -> None:
    """Anthropic effort selection follows its exact runtime profile flags."""
    sonnet = resolve_runtime_model_profile(
        provider=LLMProvider.ANTHROPIC,
        model="claude-sonnet-4-6",
        profile_model="claude-sonnet-4-6",
        assembly_metadata=None,
        context_window=1_000_000,
        context_window_explicit=True,
        source_model=_source_model("claude-sonnet-4-6", web_search=True),
    ).normalized_capabilities
    opus = resolve_runtime_model_profile(
        provider=LLMProvider.ANTHROPIC,
        model="claude-opus-4-1",
        profile_model="claude-opus-4-1",
        assembly_metadata=None,
        context_window=200_000,
        context_window_explicit=True,
        source_model=_source_model("claude-opus-4-1", web_search=True),
    ).normalized_capabilities

    assert sonnet.reasoning.effort_levels == [
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    ]
    assert opus.reasoning.supported is True
    assert opus.reasoning.effort_levels == []
    assert sonnet.modalities.input == [
        ModelModality.TEXT,
        ModelModality.IMAGE,
        ModelModality.PDF,
    ]
    assert sonnet.built_in_tools.supported == ["web_search"]


def test_gemini_thinking_media_and_builtin_policy_matches_lowerer() -> None:
    """Gemini exposes only levels and media that have runtime mappings."""
    capabilities = resolve_runtime_model_profile(
        provider=LLMProvider.GOOGLE_GEMINI,
        model="gemini-3.1-pro",
        profile_model="gemini-3.1-pro",
        assembly_metadata=None,
        context_window=1_000_000,
        context_window_explicit=True,
        source_model=_source_model("gemini-3.1-pro"),
    ).normalized_capabilities

    assert capabilities.reasoning.effort_levels == [
        ModelReasoningEffort.NONE,
        ModelReasoningEffort.MINIMAL,
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    ]
    assert capabilities.modalities.input == [
        ModelModality.TEXT,
        ModelModality.IMAGE,
        ModelModality.PDF,
    ]
    assert capabilities.built_in_tools.supported == [
        "web_search",
        "image_generation",
    ]


def test_vertex_google_family_matches_direct_gemini_capabilities() -> None:
    """Vertex Google publisher resources retain Gemini runtime capability parity."""
    capabilities = resolve_runtime_model_profile(
        provider=LLMProvider.GOOGLE_VERTEX_AI,
        model=(
            "projects/project/locations/global/publishers/google/models/"
            "gemini-3.1-pro-preview"
        ),
        profile_model=(
            "projects/project/locations/global/publishers/google/models/"
            "gemini-3.1-pro-preview"
        ),
        assembly_metadata=None,
        context_window=1_000_000,
        context_window_explicit=True,
        source_model=_source_model("gemini-3.1-pro-preview"),
    ).normalized_capabilities

    assert capabilities.reasoning.effort_levels == [
        ModelReasoningEffort.NONE,
        ModelReasoningEffort.MINIMAL,
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    ]
    assert capabilities.modalities.input == [
        ModelModality.TEXT,
        ModelModality.IMAGE,
        ModelModality.PDF,
    ]
    assert capabilities.built_in_tools.supported == [
        "web_search",
        "image_generation",
    ]


def test_vertex_anthropic_family_matches_direct_anthropic_capabilities() -> None:
    """Vertex Anthropic publisher resources retain Claude runtime capability parity."""
    capabilities = resolve_runtime_model_profile(
        provider=LLMProvider.GOOGLE_VERTEX_AI,
        model=(
            "projects/project/locations/us-east5/publishers/anthropic/models/"
            "claude-sonnet-4-6"
        ),
        profile_model="claude-sonnet-4-6",
        assembly_metadata=None,
        context_window=1_000_000,
        context_window_explicit=True,
        source_model=_source_model("claude-sonnet-4-6", web_search=True),
    ).normalized_capabilities

    assert capabilities.reasoning.effort_levels == [
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    ]
    assert capabilities.modalities.input == [
        ModelModality.TEXT,
        ModelModality.IMAGE,
        ModelModality.PDF,
    ]
    assert capabilities.built_in_tools.supported == ["web_search"]
