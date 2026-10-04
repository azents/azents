"""Own-provider declarations retain presence without network or legacy flags."""

import pytest
from pydantic import ValidationError

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_capability_contract import ModelCapabilityFeature
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_capability_projection import (
    compile_model_capabilities,
    compile_stored_choice,
)
from azents.core.model_catalog_source import CatalogFact
from azents.core.model_provider_declarations import (
    MalformedProviderDeclarations,
    decode_stored_provider_evidence,
)


def _decode(
    provider: LLMProvider, raw: dict[str, object]
) -> ProviderCapabilityEvidence:
    return decode_stored_provider_evidence(
        provider=provider, provider_metadata=raw, capability_evidence=None
    )


@pytest.mark.parametrize("provider", list(LLMProvider))
def test_typed_canonical_evidence_precedes_even_malformed_raw_metadata(
    provider: LLMProvider,
) -> None:
    canonical = ProviderCapabilityEvidence(
        function_calling=CatalogFact(state="value", value=False)
    )
    assert (
        decode_stored_provider_evidence(
            provider=provider,
            provider_metadata={
                "context_window": "malformed",
                "input_modalities": False,
            },
            capability_evidence=canonical,
        )
        is canonical
    )


@pytest.mark.parametrize("provider", list(LLMProvider))
def test_empty_provider_metadata_does_not_read_legacy_flat_booleans(
    provider: LLMProvider,
) -> None:
    evidence = _decode(provider, {"tool_calling": {"supported": True}})
    assert evidence.function_calling.state == "absent"
    assert evidence.strict_function_schema.state == "absent"
    assert evidence.structured_response.state == "absent"


@pytest.mark.parametrize("current", [None, False, True])
@pytest.mark.parametrize("legacy", [None, False, True])
def test_chatgpt_current_summary_parameter_presence_wins_over_legacy_alias(
    current: bool | None, legacy: bool | None
) -> None:
    evidence = _decode(
        LLMProvider.CHATGPT_OAUTH,
        {
            "supports_reasoning_summary_parameter": current,
            "supports_reasoning_summaries": legacy,
            "supports_search_tool": True,
        },
    )
    assert evidence.reasoning_summaries == CatalogFact(
        state="null" if current is None else "value", value=current
    )
    assert evidence.web_search.state == "absent"


@pytest.mark.parametrize("legacy", [None, False, True])
def test_chatgpt_legacy_summary_alias_is_used_only_when_current_key_is_absent(
    legacy: bool | None,
) -> None:
    evidence = _decode(
        LLMProvider.CHATGPT_OAUTH, {"supports_reasoning_summaries": legacy}
    )
    assert evidence.reasoning_summaries == CatalogFact(
        state="null" if legacy is None else "value", value=legacy
    )


def test_chatgpt_ultra_retains_pretransition_exclusion_without_effort_aliases() -> None:
    evidence = _decode(
        LLMProvider.CHATGPT_OAUTH,
        {
            "supported_reasoning_levels": [
                {"effort": "low"},
                {"effort": "ultra"},
                {"effort": "low"},
                {"effort": "future-level"},
            ],
            "default_reasoning_level": "ultra",
            "tool_mode": "code_mode_only",
        },
    )
    assert evidence.reasoning_efforts.value == (ModelReasoningEffort.LOW,)
    compiled = compile_model_capabilities(
        provider=LLMProvider.CHATGPT_OAUTH,
        exact_model="literal-new-account-model",
        source_model=None,
        evidence=evidence,
        model_developer=LLMModelDeveloper.OPENAI,
    )
    assert compiled.capabilities.reasoning.effort_levels == [ModelReasoningEffort.LOW]
    assert compiled.capabilities.request_constraints.known_default is None
    assert compiled.capabilities.supports(ModelCapabilityFeature.FUNCTION_CALLING)
    assert compiled.capabilities.supports(ModelCapabilityFeature.IMAGE_GENERATION)


@pytest.mark.parametrize("provider", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
def test_ultra_is_not_borrowed_by_other_provider_declarations(
    provider: LLMProvider,
) -> None:
    raw: dict[str, object] = (
        {"capabilities": {"reasoning_effort": ["high", "ultra"]}}
        if provider == LLMProvider.XAI
        else {"reasoning_efforts": [{"id": "high"}, {"id": "ultra"}]}
    )
    evidence = _decode(provider, raw)
    assert evidence.reasoning_efforts.value == (ModelReasoningEffort.HIGH,)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({}, "high"),
        ({"reasoning_effort": None}, None),
        ({"reasoning_effort": "future-level"}, None),
        ({"reasoning_effort": "low"}, "low"),
        ({"reasoning_efforts": [{"id": "high", "default": True}]}, "high"),
        (
            {
                "reasoning_effort": "low",
                "reasoning_efforts": [{"id": "high", "default": True}, {"id": "low"}],
            },
            None,
        ),
        (
            {
                "reasoning_efforts": [
                    {"id": "low", "default": True},
                    {"id": "high", "default": True},
                ]
            },
            None,
        ),
        ({"supports_reasoning_effort": False, "reasoning_effort": "high"}, None),
    ],
)
def test_grok_reviewed_default_fills_only_absent_compatible_knowledge(
    raw: dict[str, object], expected: str | None
) -> None:
    evidence = _decode(LLMProvider.XAI_OAUTH, raw)
    compiled = compile_model_capabilities(
        provider=LLMProvider.XAI_OAUTH,
        exact_model="grok-4.7",
        source_model=None,
        evidence=evidence,
        model_developer=LLMModelDeveloper.XAI,
    )
    assert compiled.capabilities.request_constraints.known_default == expected
    assert compiled.facts.provider_declarations == evidence


@pytest.mark.parametrize("declaration", [None, [], ["tools", "structured_outputs"]])
def test_openrouter_parameter_presence_remains_separate_from_final_support(
    declaration: list[str] | None,
) -> None:
    evidence = _decode(LLMProvider.OPENROUTER, {"supported_parameters": declaration})
    assert evidence.function_calling == CatalogFact(
        state="null" if declaration is None else "value",
        value=None if declaration is None else "tools" in declaration,
    )
    assert evidence.structured_response == CatalogFact(
        state="null" if declaration is None else "value",
        value=None if declaration is None else "structured_outputs" in declaration,
    )
    assert evidence.strict_function_schema.state == "absent"
    assert evidence.reasoning_efforts.value == (() if declaration is not None else None)


@pytest.mark.parametrize(
    "raw", [{}, {"architecture": None}, {"architecture": {"input_modalities": []}}]
)
def test_openrouter_nested_absent_null_and_empty_survive_decode(
    raw: dict[str, object],
) -> None:
    evidence = _decode(LLMProvider.OPENROUTER, raw)
    expected = (
        CatalogFact(state="absent", value=None)
        if not raw
        else CatalogFact(state="null", value=None)
        if raw["architecture"] is None
        else CatalogFact(state="value", value=())
    )
    assert evidence.input_modalities == expected


@pytest.mark.parametrize(
    ("provider", "raw"),
    [
        (LLMProvider.CHATGPT_OAUTH, {"supports_reasoning_summary_parameter": "false"}),
        (LLMProvider.CHATGPT_OAUTH, {"context_window": True}),
        (LLMProvider.KIMI_OAUTH, {"supports_image_in": 1}),
        (LLMProvider.AWS_BEDROCK, {"inputModalities": [None]}),
        (LLMProvider.GOOGLE_VERTEX_AI, {"inputTokenLimit": "1000"}),
        (LLMProvider.OPENROUTER, {"supported_parameters": False}),
        (LLMProvider.XAI, {"capabilities": {"reasoning_effort": 1}}),
        (LLMProvider.XAI_OAUTH, {"context_windows": [-1]}),
    ],
)
def test_malformed_consumed_declarations_raise_instead_of_becoming_negative_support(
    provider: LLMProvider, raw: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        _decode(provider, raw)


def test_malformed_xai_context_range_is_retryable_provider_evidence_failure() -> None:
    with pytest.raises(MalformedProviderDeclarations):
        _decode(
            LLMProvider.XAI_OAUTH,
            {"context_window": 600000, "context_windows": [500000]},
        )


@pytest.mark.parametrize(
    "model", ["gpt-6-astra", "gpt-6.1-sol", "literal-unreviewed-model"]
)
def test_native_sampling_exclusions_are_scoped_to_reviewed_exact_models(
    model: str,
) -> None:
    evidence = ProviderCapabilityEvidence(
        reasoning=CatalogFact(state="value", value=True),
        reasoning_efforts=CatalogFact(
            state="value", value=(ModelReasoningEffort.HIGH,)
        ),
        temperature=CatalogFact(state="value", value=True),
        top_p=CatalogFact(state="value", value=True),
    )
    compiled = compile_model_capabilities(
        provider=LLMProvider.CHATGPT_OAUTH,
        exact_model=model,
        source_model=None,
        evidence=evidence,
        model_developer=LLMModelDeveloper.OPENAI,
    )
    assert compiled.capabilities.parameters.temperature is (
        model == "literal-unreviewed-model"
    )
    assert compiled.capabilities.parameters.top_p is (
        model == "literal-unreviewed-model"
    )
    assert compiled.facts.declarations.temperature.value is True


@pytest.mark.parametrize(
    ("publisher", "developer", "supports_top_k"),
    [
        ("anthropic", LLMModelDeveloper.OTHER, True),
        ("google", LLMModelDeveloper.ANTHROPIC, True),
    ],
)
def test_vertex_physical_resource_owns_protocol_not_developer_metadata(
    publisher: str, developer: LLMModelDeveloper, supports_top_k: bool
) -> None:
    evidence = ProviderCapabilityEvidence(
        reasoning=CatalogFact(state="value", value=True),
        reasoning_efforts=CatalogFact(
            state="value",
            value=(ModelReasoningEffort.MINIMAL, ModelReasoningEffort.MAX),
        ),
        top_k=CatalogFact(state="value", value=True),
    )
    compiled = compile_model_capabilities(
        provider=LLMProvider.GOOGLE_VERTEX_AI,
        exact_model=f"projects/p/locations/l/publishers/{publisher}/models/exact",
        source_model=None,
        evidence=evidence,
        model_developer=developer,
    )
    assert compiled.capabilities.reasoning.effort_levels == (
        [ModelReasoningEffort.MAX]
        if publisher == "anthropic"
        else [ModelReasoningEffort.MINIMAL]
    )
    assert compiled.capabilities.parameters.top_k is supports_top_k


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6.1-sol"])
def test_sparse_stored_chatgpt_declarations_recover_verified_exact_schema_support(
    model: str,
) -> None:
    """Root's scoped strict-function and strict-output probes returned schema nonces."""
    evidence = _decode(
        LLMProvider.CHATGPT_OAUTH,
        {
            "input_modalities": ["text", "image"],
            "supported_reasoning_levels": [{"effort": "low"}],
            "default_reasoning_level": "low",
            "tool_mode": "code_mode_only",
        },
    )
    assert evidence.strict_function_schema.state == "absent"
    assert evidence.structured_response.state == "absent"
    replayed = ProviderCapabilityEvidence.model_validate_json(
        evidence.model_dump_json()
    )
    compiled = compile_stored_choice(
        provider=LLMProvider.CHATGPT_OAUTH,
        exact_model=model,
        source_model=None,
        evidence=replayed,
        model_developer=LLMModelDeveloper.OPENAI,
    )
    assert compiled.capabilities.supports(ModelCapabilityFeature.STRICT_FUNCTION_SCHEMA)
    assert compiled.capabilities.supports(ModelCapabilityFeature.STRUCTURED_RESPONSE)
    assert compiled.facts.provider_declarations == evidence
    assert compiled.facts.declarations.strict_function_schema.state == "absent"
    assert compiled.facts.declarations.structured_response.state == "absent"


@pytest.mark.parametrize(
    "model", ["k3", "k3-256k", "kimi-for-coding", "kimi-for-coding-highspeed"]
)
def test_kimi_sparse_account_declarations_replay_managed_function_contract(
    model: str,
) -> None:
    evidence = _decode(
        LLMProvider.KIMI_OAUTH,
        {
            "supports_reasoning": True,
            "supports_image_in": True,
            "supports_video_in": True,
        },
    )
    replayed = ProviderCapabilityEvidence.model_validate_json(
        evidence.model_dump_json()
    )
    compiled = compile_stored_choice(
        provider=LLMProvider.KIMI_OAUTH,
        exact_model=model,
        source_model=None,
        evidence=replayed,
        model_developer=LLMModelDeveloper.MOONSHOT,
    )
    assert compiled.capabilities.tool_calling.supported is True
    assert compiled.capabilities.tool_calling.parallel_tool_calls is False
    assert compiled.capabilities.tool_calling.strict_json_schema is False
    assert compiled.capabilities.structured_response is False
    assert compiled.capabilities.reasoning.supported is True
    assert compiled.capabilities.reasoning.effort_levels == []
    assert compiled.capabilities.built_in_tools.supported == []
    assert compiled.facts.declarations.function_calling.state == "absent"
    assert compiled.facts.provider_declarations == replayed


@pytest.mark.parametrize("provider", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
def test_grok47_sparse_stored_discovery_replays_hosted_web_contract(
    provider: LLMProvider,
) -> None:
    evidence = _decode(provider, {})
    compiled = compile_stored_choice(
        provider=provider,
        exact_model="grok-4.7",
        source_model=None,
        evidence=evidence,
        model_developer=LLMModelDeveloper.XAI,
    )
    assert compiled.capabilities.supports(ModelCapabilityFeature.WEB_SEARCH)
    assert compiled.facts.declarations.web_search.state == "absent"
