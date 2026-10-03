"""Exact source/provider facts survive projection without profile ceilings."""

import json
from typing import Never

import pytest
from pydantic_ai.profiles.google import GoogleModelProfile
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelModality,
    ModelReasoningEffort,
)
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_capability_projection import (
    google_lossless_efforts,
    project_capabilities,
)
from azents.core.model_catalog_source import (
    CatalogFact,
    CatalogSourceModel,
    decode_catalog_source,
)


def _source(
    namespace: str, identifier: str, fields: dict[str, object]
) -> CatalogSourceModel:
    key = (
        f"{namespace}/{identifier}"
        if namespace
        in {"chatgpt", "xai", "openrouter", "gemini", "vertex_ai", "kimi_oauth"}
        else identifier
    )
    payload = decode_catalog_source(
        json.dumps(
            {key: {"litellm_provider": namespace, "mode": "chat", **fields}}
        ).encode()
    )
    return payload.models[0]


def _project(
    provider: LLMProvider,
    source: CatalogSourceModel | None,
    evidence: ProviderCapabilityEvidence | None,
    developer: LLMModelDeveloper | None,
) -> ModelCapabilities:
    identifier = (
        source.source_key.removeprefix(f"{source.provider}/")
        if source
        and source.provider
        in {"chatgpt", "xai", "openrouter", "gemini", "vertex_ai", "kimi_oauth"}
        else source.source_key
        if source
        else "account-visible"
    )
    return project_capabilities(
        provider=provider,
        exact_model=identifier,
        source_model=source,
        evidence=evidence,
        model_developer=developer,
    )


@pytest.mark.parametrize("value", [False, None, True])
def test_chatgpt_explicit_web_evidence_is_not_replaced_by_route_policy(
    value: bool | None,
) -> None:
    evidence = ProviderCapabilityEvidence(
        web_search=CatalogFact(state="null" if value is None else "value", value=value)
    )
    caps = _project(LLMProvider.CHATGPT_OAUTH, None, evidence, LLMModelDeveloper.OPENAI)
    assert caps.semantic_contract is not None
    web = next(
        item.support
        for item in caps.semantic_contract.built_in_tools
        if item.tool == "web_search"
    )
    assert web.state == (
        "unknown" if value is None else "supported" if value else "unsupported"
    )
    assert web.origin == (None if value is None else "explicit")


@pytest.mark.parametrize(
    "provider", [LLMProvider.OPENAI, LLMProvider.XAI, LLMProvider.OPENROUTER]
)
def test_chatgpt_web_route_policy_does_not_enable_other_provider_unknowns(
    provider: LLMProvider,
) -> None:
    caps = _project(provider, None, None, LLMModelDeveloper.OPENAI)
    assert "web_search" not in caps.built_in_tools.supported
    assert caps.semantic_contract is not None
    web = next(
        item.support
        for item in caps.semantic_contract.built_in_tools
        if item.tool == "web_search"
    )
    assert web.state == "unknown"


def test_native_source_efforts_do_not_consult_pydantic_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_profile(*args: object, **kwargs: object) -> Never:
        raise AssertionError(
            "Native capability projection must not query library profiles"
        )

    monkeypatch.setattr(OpenAIProvider, "model_profile", reject_profile)
    source = _source(
        "openai",
        "gpt-5",
        {
            "supports_reasoning": True,
            "reasoning_effort_levels": [
                "none",
                "minimal",
                "low",
                "high",
                "xhigh",
                "max",
            ],
            "supported_endpoints": ["/v1/responses"],
            "supports_function_calling": True,
        },
    )
    caps = _project(LLMProvider.OPENAI, source, None, LLMModelDeveloper.OPENAI)
    assert caps.reasoning.effort_levels == [
        ModelReasoningEffort.NONE,
        ModelReasoningEffort.MINIMAL,
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.HIGH,
        ModelReasoningEffort.XHIGH,
        ModelReasoningEffort.MAX,
    ]
    assert caps.semantic_contract is not None
    assert caps.semantic_contract.reasoning.completeness == "complete"
    assert ModelCapabilities.model_validate_json(caps.model_dump_json()) == caps


def test_provider_array_supersedes_weaker_source_denial() -> None:
    source = _source("chatgpt", "account-visible", {"supports_reasoning": False})
    evidence = ProviderCapabilityEvidence(
        reasoning_efforts=CatalogFact(
            state="value", value=(ModelReasoningEffort.XHIGH, ModelReasoningEffort.MAX)
        ),
    )
    caps = _project(
        LLMProvider.CHATGPT_OAUTH, source, evidence, LLMModelDeveloper.OPENAI
    )
    assert caps.reasoning.supported is True
    assert caps.reasoning.effort_levels == [
        ModelReasoningEffort.XHIGH,
        ModelReasoningEffort.MAX,
    ]


@pytest.mark.parametrize("state", ["null", "empty", "denial"])
def test_provider_unknown_empty_and_denial_do_not_restore_source_efforts(
    state: str,
) -> None:
    source = _source(
        "xai",
        "grok-visible",
        {"supports_reasoning": True, "reasoning_effort_levels": ["low", "max"]},
    )
    if state == "denial":
        evidence = ProviderCapabilityEvidence(
            reasoning=CatalogFact(state="value", value=False)
        )
    elif state == "empty":
        evidence = ProviderCapabilityEvidence(
            reasoning_efforts=CatalogFact(state="value", value=())
        )
    else:
        evidence = ProviderCapabilityEvidence(
            reasoning_efforts=CatalogFact(state="null", value=None)
        )
    caps = _project(LLMProvider.XAI, source, evidence, LLMModelDeveloper.XAI)
    assert caps.reasoning.effort_levels == []
    assert caps.reasoning.supported is (state != "denial")
    assert caps.semantic_contract is not None
    assert caps.semantic_contract.reasoning.completeness == (
        "unknown" if state == "null" else "complete"
    )


def test_flag_contract_keeps_explicit_and_derived_efforts() -> None:
    source = _source(
        "openai",
        "gpt-5",
        {
            "mode": "responses",
            "supports_reasoning": True,
            "supports_xhigh_reasoning_effort": True,
        },
    )
    caps = _project(LLMProvider.OPENAI, source, None, LLMModelDeveloper.OPENAI)
    assert caps.semantic_contract is not None
    declarations = {
        item.level: item for item in caps.semantic_contract.reasoning.efforts
    }
    assert declarations["xhigh"].origin == "explicit"
    assert declarations["medium"].origin == "contract_derived"
    assert declarations["max"].state == "unsupported"


def test_reasoning_boolean_alone_does_not_invent_effort_controls() -> None:
    source = _source("kimi_oauth", "kimi-visible", {"supports_reasoning": True})
    caps = _project(LLMProvider.KIMI_OAUTH, source, None, LLMModelDeveloper.MOONSHOT)
    assert caps.reasoning.supported is True
    assert caps.reasoning.effort_levels == []


def test_native_sampling_unknown_and_unsupported_transport_stay_distinct() -> None:
    source = _source("openai", "gpt-5", {"supports_reasoning": False})
    caps = _project(LLMProvider.OPENAI, source, None, LLMModelDeveloper.OPENAI)
    assert caps.semantic_contract is not None
    assert caps.semantic_contract.parameters.temperature.state == "unknown"
    assert caps.semantic_contract.parameters.top_p.state == "unknown"
    assert caps.semantic_contract.parameters.top_k.state == "unsupported"
    assert caps.semantic_contract.parameters.stop_sequences.state == "unsupported"
    assert caps.parameters.temperature is False
    assert caps.parameters.max_output_tokens is True


def test_strict_function_contract_is_independent_from_structured_response() -> None:
    source = _source(
        "openai",
        "gpt-5",
        {
            "supports_function_calling": True,
            "supports_response_schema": False,
        },
    )
    caps = _project(LLMProvider.OPENAI, source, None, LLMModelDeveloper.OPENAI)
    assert caps.semantic_contract is not None
    assert caps.tool_calling.strict_json_schema is True
    assert caps.semantic_contract.structured_response.state == "unsupported"


def test_web_price_cannot_enable_native_search() -> None:
    source = _source(
        "openai", "gpt-5", {"search_context_cost_per_query": {"low": 0.01}}
    )
    caps = _project(LLMProvider.OPENAI, source, None, LLMModelDeveloper.OPENAI)
    assert "web_search" not in caps.built_in_tools.supported


def test_hosted_image_denial_does_not_disable_reviewed_client_executor() -> None:
    source = _source("openai", "gpt-5", {"supports_function_calling": True})
    caps = _project(
        LLMProvider.OPENAI,
        source,
        ProviderCapabilityEvidence(
            hosted_image_generation=CatalogFact(state="value", value=False)
        ),
        LLMModelDeveloper.OPENAI,
    )
    assert "image_generation" in caps.built_in_tools.supported
    unreviewed = _project(
        LLMProvider.OPENAI,
        _source("openai", "new-unreviewed", {"supports_function_calling": True}),
        None,
        LLMModelDeveloper.OPENAI,
    )
    assert "image_generation" not in unreviewed.built_in_tools.supported


def test_source_media_requires_actual_lowering() -> None:
    source = _source(
        "openai",
        "gpt-5",
        {
            "supports_vision": True,
            "supports_audio_input": True,
            "supports_video_input": True,
            "supports_audio_output": True,
        },
    )
    caps = _project(LLMProvider.OPENAI, source, None, LLMModelDeveloper.OPENAI)
    assert caps.modalities.input == [
        ModelModality.TEXT,
        ModelModality.IMAGE,
        ModelModality.PDF,
    ]
    assert caps.modalities.output == [ModelModality.TEXT]


def test_complete_empty_provider_modalities_remain_empty() -> None:
    source = _source("openrouter", "vendor/opaque", {"supports_vision": True})
    caps = _project(
        LLMProvider.OPENROUTER,
        source,
        ProviderCapabilityEvidence(
            input_modalities=CatalogFact(state="value", value=())
        ),
        LLMModelDeveloper.OTHER,
    )
    assert caps.modalities.input == []


def test_sparse_cloud_listing_does_not_deny_source_facts() -> None:
    source = _source(
        "vertex_ai",
        "gemini-3-pro-preview",
        {
            "supports_function_calling": True,
            "supports_vision": True,
            "supports_reasoning": True,
            "reasoning_effort_levels": ["low", "high", "xhigh"],
            "max_output_tokens": 20000,
        },
    )
    caps = _project(
        LLMProvider.GOOGLE_VERTEX_AI,
        source,
        ProviderCapabilityEvidence(),
        LLMModelDeveloper.GOOGLE,
    )
    assert caps.tool_calling.supported is True
    assert ModelModality.IMAGE in caps.modalities.input
    assert caps.context_window.max_output_tokens == 20000
    assert caps.reasoning.effort_levels == [
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.HIGH,
    ]


def test_bedrock_explicit_efforts_require_implemented_family_lowering() -> None:
    source = _source(
        "bedrock_converse",
        "visible-model",
        {
            "supports_reasoning": True,
            "reasoning_effort_levels": ["high", "max"],
            "bedrock_converse_supports_strict_tools": True,
            "supports_function_calling": True,
        },
    )
    caps = _project(LLMProvider.AWS_BEDROCK, source, None, LLMModelDeveloper.META)
    assert caps.reasoning.supported is True
    assert caps.reasoning.effort_levels == []
    caps = _project(LLMProvider.AWS_BEDROCK, source, None, LLMModelDeveloper.ANTHROPIC)
    assert caps.reasoning.effort_levels == [
        ModelReasoningEffort.HIGH,
        ModelReasoningEffort.MAX,
    ]
    assert caps.tool_calling.strict_json_schema is True


def test_token_limits_preserve_null_and_independent_meanings() -> None:
    source = _source(
        "openai",
        "gpt-5",
        {"max_tokens": 99999, "max_input_tokens": 7000, "max_output_tokens": 1000},
    )
    caps = _project(
        LLMProvider.OPENAI,
        source,
        ProviderCapabilityEvidence(
            default_input_tokens=CatalogFact(state="value", value=3000),
            max_input_tokens=CatalogFact(state="null", value=None),
        ),
        LLMModelDeveloper.OPENAI,
    )
    assert caps.context_window.default_input_tokens == 3000
    assert caps.context_window.max_input_tokens is None
    assert caps.context_window.max_output_tokens == 1000


@pytest.mark.parametrize("provider", list(LLMProvider))
def test_missing_source_does_not_need_a_fabricated_profile(
    provider: LLMProvider,
) -> None:
    caps = _project(provider, None, None, None)
    assert caps.semantic_contract is not None
    assert caps.reasoning.effort_levels == []
    assert caps.semantic_contract.reasoning.support.state == "unknown"
    assert ModelCapabilities.model_validate_json(caps.model_dump_json()) == caps


@pytest.mark.parametrize("provider", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
def test_client_image_policy_does_not_invent_a_function_fact(
    provider: LLMProvider,
) -> None:
    caps = _project(
        provider,
        None,
        ProviderCapabilityEvidence(
            hosted_image_generation=CatalogFact(state="value", value=False),
        ),
        LLMModelDeveloper.XAI,
    )
    assert caps.semantic_contract is not None
    assert caps.semantic_contract.function_calling.state == "unknown"
    assert "image_generation" in caps.built_in_tools.supported
    denied = _project(
        provider,
        None,
        ProviderCapabilityEvidence(
            function_calling=CatalogFact(state="value", value=False),
        ),
        LLMModelDeveloper.XAI,
    )
    assert "image_generation" not in denied.built_in_tools.supported


def test_sparse_web_listing_enriches_from_source_without_price_evidence() -> None:
    source = _source("xai", "grok-visible", {"supports_web_search": True})
    enriched = _project(
        LLMProvider.XAI, source, ProviderCapabilityEvidence(), LLMModelDeveloper.XAI
    )
    assert "web_search" in enriched.built_in_tools.supported
    unknown = _project(
        LLMProvider.XAI, None, ProviderCapabilityEvidence(), LLMModelDeveloper.XAI
    )
    assert unknown.semantic_contract is not None
    assert unknown.semantic_contract.built_in_tools[0].support.state == "unknown"
    assert "web_search" not in unknown.built_in_tools.supported


def test_partial_kimi_image_flag_preserves_other_source_media_facts() -> None:
    source = _source(
        "kimi_oauth",
        "kimi-visible",
        {"supports_vision": True, "supports_pdf_input": True},
    )
    caps = _project(
        LLMProvider.KIMI_OAUTH,
        source,
        ProviderCapabilityEvidence(
            image_input=CatalogFact(state="value", value=False),
        ),
        LLMModelDeveloper.MOONSHOT,
    )
    assert ModelModality.IMAGE not in caps.modalities.input
    assert ModelModality.PDF in caps.modalities.input


def test_source_empty_media_list_is_not_replenished_by_a_flag() -> None:
    source = _source(
        "openai", "gpt-5", {"supports_vision": True, "supported_modalities": []}
    )
    caps = _project(LLMProvider.OPENAI, source, None, LLMModelDeveloper.OPENAI)
    assert caps.modalities.input == []


def test_google_wire_bounds_use_scalar_codec_domain_without_snapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        GoogleProvider,
        "model_profile",
        staticmethod(
            lambda model: GoogleModelProfile(
                google_supports_thinking_level=True,
                google_thinking_levels=frozenset({"LOW", "HIGH"}),
            )
        ),
    )
    assert google_lossless_efforts(
        provider=LLMProvider.GOOGLE_GEMINI, model="opaque"
    ) == (
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.HIGH,
    )
    monkeypatch.setattr(
        GoogleProvider,
        "model_profile",
        staticmethod(
            lambda model: GoogleModelProfile(google_supports_thinking_level=True)
        ),
    )
    assert google_lossless_efforts(
        provider=LLMProvider.GOOGLE_GEMINI, model="opaque"
    ) == (
        ModelReasoningEffort.MINIMAL,
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    )


@pytest.mark.parametrize(
    ("provider", "namespace"),
    [
        (LLMProvider.OPENAI, "openai"),
        (LLMProvider.CHATGPT_OAUTH, "chatgpt"),
        (LLMProvider.XAI, "xai"),
        (LLMProvider.XAI_OAUTH, "xai_oauth"),
    ],
)
@pytest.mark.parametrize("function", [True, False])
def test_responses_conversation_mode_retains_client_image_policy(
    provider: LLMProvider, namespace: str, function: bool
) -> None:
    identifier = "gpt-6-astra" if namespace in {"openai", "chatgpt"} else "grok"
    key = identifier if namespace == "openai" else f"{namespace}/{identifier}"
    source = decode_catalog_source(
        json.dumps(
            {
                key: {
                    "litellm_provider": namespace,
                    "mode": "responses",
                    "supports_function_calling": function,
                }
            }
        ).encode()
    ).models[0]
    caps = project_capabilities(
        provider=provider,
        exact_model=identifier,
        source_model=source,
        evidence=None,
        model_developer=None,
    )
    assert ("image_generation" in caps.built_in_tools.supported) is function


@pytest.mark.parametrize(
    ("provider", "namespace"),
    [
        (LLMProvider.GOOGLE_GEMINI, "gemini"),
        (LLMProvider.GOOGLE_VERTEX_AI, "vertex_ai"),
    ],
)
@pytest.mark.parametrize("minimal", [True, False])
def test_google_sparse_scalar_codec_preserves_only_explicit_model_efforts(
    monkeypatch: pytest.MonkeyPatch,
    provider: LLMProvider,
    namespace: str,
    minimal: bool,
) -> None:
    monkeypatch.setattr(
        GoogleProvider,
        "model_profile",
        staticmethod(
            lambda model: GoogleModelProfile(
                google_supports_thinking_level=True,
                google_supports_minimal_thinking_level=minimal,
            )
        ),
    )
    source = _source(
        namespace,
        "account-visible",
        {
            "supports_reasoning": True,
            "reasoning_effort_levels": ["minimal", "low", "medium", "high", "max"],
        },
    )
    caps = _project(provider, source, None, LLMModelDeveloper.GOOGLE)
    expected = [
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    ]
    if minimal:
        expected.insert(0, ModelReasoningEffort.MINIMAL)
    assert caps.reasoning.effort_levels == expected
    assert ModelCapabilities.model_validate_json(caps.model_dump_json()) == caps
    empty = _project(provider, None, None, LLMModelDeveloper.GOOGLE)
    assert empty.reasoning.effort_levels == []


@pytest.mark.parametrize("denied", [False, True])
def test_unknown_function_fact_does_not_erase_explicit_parallel_and_strict(
    denied: bool,
) -> None:
    caps = _project(
        LLMProvider.CHATGPT_OAUTH,
        None,
        ProviderCapabilityEvidence(
            function_calling=CatalogFact(
                state="value" if denied else "absent",
                value=False if denied else None,
            ),
            parallel_function_calling=CatalogFact(state="value", value=True),
            strict_function_schema=CatalogFact(state="value", value=True),
        ),
        LLMModelDeveloper.OPENAI,
    )
    assert caps.semantic_contract is not None
    assert caps.semantic_contract.function_calling.state == (
        "unsupported" if denied else "unknown"
    )
    for support in (
        caps.semantic_contract.parallel_function_calls,
        caps.semantic_contract.strict_function_schema,
    ):
        assert support.state == ("unsupported" if denied else "conditional")
        if not denied:
            assert support.predicate is not None
            assert support.predicate.function_tools is True
            assert support.origin == "explicit"
