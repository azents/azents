"""Final supported sets agree with scoped provider facts and actual route contracts."""

import json

import pytest

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelModality,
    ModelReasoningEffort,
)
from azents.core.model_capability_contract import ModelCapabilityFeature
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_capability_projection import (
    CompiledModelCapabilities,
    compile_model_capabilities,
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
    prefix = (
        ""
        if namespace in {"openai", "anthropic", "bedrock_converse"}
        else f"{namespace}/"
    )
    return decode_catalog_source(
        json.dumps(
            {
                f"{prefix}{identifier}": {
                    "litellm_provider": namespace,
                    "mode": "chat",
                    **fields,
                }
            }
        ).encode()
    ).models[0]


def _compile(
    provider: LLMProvider,
    *,
    model: str = "literal-model",
    source: CatalogSourceModel | None = None,
    evidence: ProviderCapabilityEvidence | None = None,
    developer: LLMModelDeveloper | None = None,
) -> CompiledModelCapabilities:
    return compile_model_capabilities(
        provider=provider,
        exact_model=model,
        source_model=source,
        evidence=evidence,
        model_developer=developer,
    )


@pytest.mark.parametrize("provider", list(LLMProvider))
def test_all_provider_routes_publish_only_final_feature_membership(
    provider: LLMProvider,
) -> None:
    compiled = _compile(provider)
    caps = compiled.capabilities
    assert ModelCapabilities.model_validate_json(caps.model_dump_json()) == caps
    assert caps.capability_schema_version == 3
    assert "semantic_contract" not in caps.model_dump()
    for feature in ModelCapabilityFeature:
        assert caps.supports(feature) is (feature in caps.supported_features())
    assert compiled.facts.declarations.function_calling.state == "absent"
    assert caps.tool_calling.supported is (
        provider
        in {
            LLMProvider.CHATGPT_OAUTH,
            LLMProvider.XAI_OAUTH,
            LLMProvider.KIMI_OAUTH,
        }
    )


@pytest.mark.parametrize(
    "provider",
    [LLMProvider.CHATGPT_OAUTH, LLMProvider.XAI_OAUTH, LLMProvider.KIMI_OAUTH],
)
@pytest.mark.parametrize("presence", ["absent", "null"])
def test_known_coding_function_contract_is_stored_as_support(
    provider: LLMProvider, presence: str
) -> None:
    compiled = _compile(
        provider,
        evidence=ProviderCapabilityEvidence.model_validate(
            {"function_calling": {"state": presence, "value": None}}
        ),
    )
    assert compiled.capabilities.tool_calling.supported is True
    assert compiled.capabilities.supports(ModelCapabilityFeature.FUNCTION_CALLING)
    assert compiled.facts.declarations.function_calling.state == presence
    assert compiled.capabilities.tool_calling.parallel_tool_calls is False
    assert compiled.capabilities.tool_calling.strict_json_schema is False
    assert compiled.capabilities.structured_response is False


@pytest.mark.parametrize(
    "provider",
    [LLMProvider.CHATGPT_OAUTH, LLMProvider.XAI_OAUTH, LLMProvider.KIMI_OAUTH],
)
def test_explicit_function_denial_remains_a_final_denial(provider: LLMProvider) -> None:
    compiled = _compile(
        provider,
        evidence=ProviderCapabilityEvidence(
            function_calling=CatalogFact(state="value", value=False)
        ),
    )
    assert compiled.capabilities.tool_calling.supported is False
    assert not compiled.capabilities.supports(ModelCapabilityFeature.IMAGE_GENERATION)


@pytest.mark.parametrize(
    "provider,namespace",
    [(LLMProvider.CHATGPT_OAUTH, "chatgpt"), (LLMProvider.XAI_OAUTH, "xai_oauth")],
)
def test_exact_source_denial_is_not_overwritten_by_coding_contract(
    provider: LLMProvider, namespace: str
) -> None:
    compiled = _compile(
        provider,
        source=_source(
            namespace, "literal-model", {"supports_function_calling": False}
        ),
    )
    assert compiled.capabilities.tool_calling.supported is False


@pytest.mark.parametrize(
    "provider",
    [
        item
        for item in LLMProvider
        if item
        not in {
            LLMProvider.CHATGPT_OAUTH,
            LLMProvider.XAI_OAUTH,
            LLMProvider.KIMI_OAUTH,
        }
    ],
)
def test_coding_contract_does_not_enable_unrelated_missing_function_facts(
    provider: LLMProvider,
) -> None:
    assert _compile(provider).capabilities.tool_calling.supported is False


def test_actual_chatgpt_astra_sol_rows_retain_limits_levels_defaults_and_tools() -> (
    None
):
    """Expected values are root's own-account HTTP200 rows, not public API limits."""
    for model, default in [
        ("gpt-6-astra", ModelReasoningEffort.MEDIUM),
        ("gpt-6.1-sol", ModelReasoningEffort.LOW),
    ]:
        declared = ProviderCapabilityEvidence(
            default_input_tokens=CatalogFact(state="value", value=272000),
            max_input_tokens=CatalogFact(state="value", value=872000),
            input_modalities=CatalogFact(state="value", value=("text", "image")),
            parallel_function_calling=CatalogFact(state="value", value=True),
            reasoning=CatalogFact(state="value", value=True),
            reasoning_efforts=CatalogFact(
                state="value",
                value=(
                    ModelReasoningEffort.LOW,
                    ModelReasoningEffort.MEDIUM,
                    ModelReasoningEffort.HIGH,
                    ModelReasoningEffort.XHIGH,
                    ModelReasoningEffort.MAX,
                ),
            ),
            default_reasoning_effort=CatalogFact(state="value", value=default),
            reasoning_summaries=CatalogFact(state="value", value=True),
            temperature=CatalogFact(state="value", value=True),
            top_p=CatalogFact(state="value", value=True),
        )
        caps = _compile(
            LLMProvider.CHATGPT_OAUTH, model=model, evidence=declared
        ).capabilities
        assert caps.tool_calling.supported is True
        assert caps.tool_calling.parallel_tool_calls is True
        assert caps.context_window.default_input_tokens == 272000
        assert caps.context_window.max_input_tokens == 872000
        assert caps.request_constraints.known_default == default.value
        assert caps.reasoning.effort_levels == list(
            declared.reasoning_efforts.value or ()
        )
        assert caps.modalities.input == [ModelModality.TEXT, ModelModality.IMAGE]
        assert caps.reasoning.summaries is True
        assert caps.parameters.temperature is False
        assert caps.parameters.top_p is False
        assert not any(
            condition.feature
            in {ModelCapabilityFeature.TEMPERATURE, ModelCapabilityFeature.TOP_P}
            for condition in caps.request_constraints.feature_conditions
        )


@pytest.mark.parametrize("provider", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
def test_actual_grok47_provider_acceptance_features_are_exact_model_scoped(
    provider: LLMProvider,
) -> None:
    caps = _compile(
        provider,
        model="grok-4.7",
        evidence=ProviderCapabilityEvidence(
            default_input_tokens=CatalogFact(state="value", value=256000),
            max_input_tokens=CatalogFact(state="value", value=500000),
            web_search=CatalogFact(state="value", value=True),
        ),
    ).capabilities
    assert caps.tool_calling.supported is True
    assert caps.tool_calling.strict_json_schema is True
    assert caps.tool_calling.parallel_tool_calls is True
    assert caps.structured_response is True
    assert caps.reasoning.summaries is True
    assert caps.reasoning.effort_levels == [
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
        ModelReasoningEffort.XHIGH,
    ]
    assert caps.request_constraints.known_default == "high"
    assert caps.modalities.input == [ModelModality.TEXT, ModelModality.IMAGE]
    assert caps.modalities.output == [ModelModality.TEXT]
    assert caps.context_window.default_input_tokens == 256000
    assert caps.context_window.max_input_tokens == 500000
    assert caps.context_window.max_output_tokens is None
    assert caps.parameters.temperature is True
    assert caps.parameters.top_p is True
    assert caps.parameters.top_k is False
    assert caps.parameters.stop_sequences is False
    other = _compile(provider, model="unrelated-account-model").capabilities
    assert ModelModality.IMAGE not in other.modalities.input
    assert other.structured_response is False
    assert other.tool_calling.strict_json_schema is False


@pytest.mark.parametrize("provider", [LLMProvider.CHATGPT_OAUTH, LLMProvider.XAI_OAUTH])
def test_explicit_empty_media_is_not_reenabled_by_route_contract(
    provider: LLMProvider,
) -> None:
    caps = _compile(
        provider,
        model="grok-4.7",
        evidence=ProviderCapabilityEvidence(
            input_modalities=CatalogFact(state="value", value=()),
            output_modalities=CatalogFact(state="value", value=()),
        ),
    ).capabilities
    assert caps.modalities.input == []
    assert caps.modalities.output == []


def test_unreviewed_native_sampling_preserves_explicit_model_declarations() -> None:
    source = _source(
        "openai",
        "declared-model",
        {
            "supports_function_calling": True,
            "supports_reasoning": True,
            "reasoning_effort_levels": ["none", "low", "high"],
            "default_reasoning_effort": "low",
            "supports_sampling_params": True,
        },
    )
    caps = _compile(
        LLMProvider.OPENAI, model="declared-model", source=source
    ).capabilities
    assert caps.parameters.temperature is True
    assert caps.parameters.top_p is True
    conditions = {
        condition.feature: condition
        for condition in caps.request_constraints.feature_conditions
    }
    assert ModelCapabilityFeature.TEMPERATURE not in conditions
    assert ModelCapabilityFeature.TOP_P not in conditions
    assert caps.request_constraints.known_default == "low"


def test_model_audio_video_facts_remain_positive_when_product_route_excludes_them() -> (
    None
):
    compiled = _compile(
        LLMProvider.GOOGLE_GEMINI,
        model="gemini-2.5-pro",
        source=_source(
            "gemini",
            "gemini-2.5-pro",
            {
                "supported_modalities": ["text", "image", "audio", "video", "pdf"],
                "supported_output_modalities": ["text"],
                "supports_function_calling": True,
                "supports_reasoning": True,
                "max_input_tokens": 1048576,
                "max_output_tokens": 65536,
            },
        ),
    )
    assert all(
        item.declaration.value is True for item in compiled.facts.input_modalities
    )
    assert compiled.capabilities.modalities.input == [
        ModelModality.TEXT,
        ModelModality.IMAGE,
        ModelModality.PDF,
    ]
    assert {item.feature for item in compiled.route_exclusions} >= {
        ModelCapabilityFeature.INPUT_AUDIO,
        ModelCapabilityFeature.INPUT_VIDEO,
    }
    assert compiled.capabilities.reasoning.supported is True
    assert compiled.capabilities.reasoning.effort_levels == []
    assert compiled.capabilities.context_window.max_output_tokens == 65536


def test_unknown_google_scalar_codec_preserves_explicit_supported_effort_domain() -> (
    None
):
    caps = _compile(
        LLMProvider.GOOGLE_GEMINI,
        model="literal-future-model",
        evidence=ProviderCapabilityEvidence(
            reasoning=CatalogFact(state="value", value=True),
            reasoning_efforts=CatalogFact(
                state="value", value=tuple(ModelReasoningEffort)
            ),
        ),
    ).capabilities
    assert caps.reasoning.effort_levels == [
        ModelReasoningEffort.MINIMAL,
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    ]


@pytest.mark.parametrize(
    "developer,expected",
    [(LLMModelDeveloper.ANTHROPIC, True), (LLMModelDeveloper.META, False)],
)
def test_bedrock_preserves_model_schema_fact_separately_from_codec_ceiling(
    developer: LLMModelDeveloper, expected: bool
) -> None:
    compiled = _compile(
        LLMProvider.AWS_BEDROCK,
        developer=developer,
        evidence=ProviderCapabilityEvidence(
            function_calling=CatalogFact(state="value", value=True),
            structured_response=CatalogFact(state="value", value=True),
            reasoning=CatalogFact(state="value", value=True),
            reasoning_efforts=CatalogFact(
                state="value", value=(ModelReasoningEffort.HIGH,)
            ),
        ),
    )
    assert compiled.facts.declarations.structured_response.value is True
    assert compiled.capabilities.structured_response is False
    assert bool(compiled.capabilities.reasoning.effort_levels) is expected
    assert any(
        item.feature is ModelCapabilityFeature.STRUCTURED_RESPONSE
        for item in compiled.route_exclusions
    )


@pytest.mark.parametrize("value", [False, None, True])
def test_chatgpt_web_policy_preserves_explicit_false_and_supplements_missing_knowledge(
    value: bool | None,
) -> None:
    caps = _compile(
        LLMProvider.CHATGPT_OAUTH,
        evidence=ProviderCapabilityEvidence(
            web_search=CatalogFact(
                state="null" if value is None else "value", value=value
            )
        ),
    ).capabilities
    assert caps.supports(ModelCapabilityFeature.WEB_SEARCH) is (value is not False)


def test_explicit_denials_win_over_grok_contract() -> None:
    caps = _compile(
        LLMProvider.XAI_OAUTH,
        model="grok-4.7",
        evidence=ProviderCapabilityEvidence(
            structured_response=CatalogFact(state="value", value=False),
            strict_function_schema=CatalogFact(state="value", value=False),
            reasoning=CatalogFact(state="value", value=False),
            reasoning_summaries=CatalogFact(state="value", value=False),
            temperature=CatalogFact(state="value", value=False),
            top_p=CatalogFact(state="value", value=False),
        ),
    ).capabilities
    assert caps.structured_response is False
    assert caps.tool_calling.strict_json_schema is False
    assert caps.reasoning.supported is False
    assert caps.reasoning.effort_levels == []
    assert caps.request_constraints.known_default is None
    assert caps.reasoning.summaries is False
    assert caps.parameters.temperature is False
    assert caps.parameters.top_p is False


def test_final_projector_wrapper_retains_existing_publication_interface() -> None:
    projected = project_capabilities(
        provider=LLMProvider.CHATGPT_OAUTH,
        exact_model="gpt-6.1-sol",
        source_model=None,
        evidence=None,
        model_developer=LLMModelDeveloper.OPENAI,
    )
    compiled = compile_model_capabilities(
        provider=LLMProvider.CHATGPT_OAUTH,
        exact_model="gpt-6.1-sol",
        source_model=None,
        evidence=None,
        model_developer=LLMModelDeveloper.OPENAI,
    )
    assert projected == compiled.capabilities


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6.1-sol"])
@pytest.mark.parametrize(
    ("declaration", "expected"),
    [
        (CatalogFact[bool](state="absent", value=None), True),
        (CatalogFact[bool](state="null", value=None), True),
        (CatalogFact[bool](state="value", value=True), True),
        (CatalogFact[bool](state="value", value=False), False),
    ],
)
def test_reviewed_exact_oauth_schema_contract_preserves_declaration_denials(
    model: str, declaration: CatalogFact[bool], expected: bool
) -> None:
    compiled = _compile(
        LLMProvider.CHATGPT_OAUTH,
        model=model,
        evidence=ProviderCapabilityEvidence(
            strict_function_schema=declaration,
            structured_response=declaration,
        ),
    )
    assert compiled.capabilities.tool_calling.strict_json_schema is expected
    assert compiled.capabilities.structured_response is expected
    assert compiled.facts.declarations.strict_function_schema == declaration
    assert compiled.facts.declarations.structured_response == declaration


@pytest.mark.parametrize(
    "model",
    ["gpt-5.6-terra", "gpt-5.6-luna", "gpt-6-astra-other", "gpt-6.1-sol-other"],
)
def test_reviewed_oauth_schema_contract_does_not_predict_other_model_support(
    model: str,
) -> None:
    caps = _compile(LLMProvider.CHATGPT_OAUTH, model=model).capabilities
    assert caps.tool_calling.supported is True
    assert caps.tool_calling.strict_json_schema is False
    assert caps.structured_response is False


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6.1-sol"])
def test_reviewed_oauth_schema_contract_does_not_borrow_into_public_api(
    model: str,
) -> None:
    caps = _compile(LLMProvider.OPENAI, model=model).capabilities
    assert caps.tool_calling.strict_json_schema is False
    assert caps.structured_response is False


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6.1-sol"])
def test_explicit_function_denial_does_not_deny_independent_structured_response(
    model: str,
) -> None:
    caps = _compile(
        LLMProvider.CHATGPT_OAUTH,
        model=model,
        evidence=ProviderCapabilityEvidence(
            function_calling=CatalogFact(state="value", value=False),
        ),
    ).capabilities
    assert caps.tool_calling.supported is False
    assert caps.tool_calling.strict_json_schema is False
    assert caps.structured_response is True


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6.1-sol"])
def test_reviewed_oauth_contract_preserves_exact_source_structured_response_denial(
    model: str,
) -> None:
    compiled = _compile(
        LLMProvider.CHATGPT_OAUTH,
        model=model,
        source=_source("chatgpt", model, {"supports_response_schema": False}),
    )
    assert compiled.capabilities.tool_calling.strict_json_schema is True
    assert compiled.capabilities.structured_response is False
    assert compiled.facts.declarations.structured_response.value is False


@pytest.mark.parametrize(
    "provider", [LLMProvider.GOOGLE_GEMINI, LLMProvider.GOOGLE_VERTEX_AI]
)
@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gemini-2.5-pro", []),
        ("gemini-2.5-flash", []),
        ("gemini-3-pro-preview", [ModelReasoningEffort.LOW, ModelReasoningEffort.HIGH]),
        (
            "gemini-3.1-pro-preview",
            [
                ModelReasoningEffort.LOW,
                ModelReasoningEffort.MEDIUM,
                ModelReasoningEffort.HIGH,
            ],
        ),
        (
            "gemini-3-flash-preview",
            [
                ModelReasoningEffort.MINIMAL,
                ModelReasoningEffort.LOW,
                ModelReasoningEffort.MEDIUM,
                ModelReasoningEffort.HIGH,
            ],
        ),
        (
            "literal-future-model",
            [
                ModelReasoningEffort.MINIMAL,
                ModelReasoningEffort.LOW,
                ModelReasoningEffort.MEDIUM,
                ModelReasoningEffort.HIGH,
            ],
        ),
        (
            "gemini-3.7-flash",
            [
                ModelReasoningEffort.LOW,
                ModelReasoningEffort.MEDIUM,
                ModelReasoningEffort.HIGH,
            ],
        ),
        (
            "gemini-3.8-flash",
            [
                ModelReasoningEffort.LOW,
                ModelReasoningEffort.MEDIUM,
                ModelReasoningEffort.HIGH,
            ],
        ),
    ],
)
def test_google_declarations_intersect_only_lossless_physical_scalar_codec_domain(
    provider: LLMProvider, model: str, expected: list[ModelReasoningEffort]
) -> None:
    exact_model = (
        f"projects/p/locations/l/publishers/google/models/{model}"
        if provider == LLMProvider.GOOGLE_VERTEX_AI
        else f"models/{model}"
    )
    declared_efforts = tuple(ModelReasoningEffort)
    compiled = _compile(
        provider,
        model=exact_model,
        evidence=ProviderCapabilityEvidence(
            reasoning=CatalogFact(state="value", value=True),
            reasoning_efforts=CatalogFact(state="value", value=declared_efforts),
            default_reasoning_effort=CatalogFact(
                state="value", value=ModelReasoningEffort.HIGH
            ),
        ),
    )
    assert compiled.capabilities.reasoning.supported is True
    assert compiled.capabilities.reasoning.effort_levels == expected
    assert compiled.capabilities.request_constraints.known_default == (
        "high" if expected else None
    )
    assert compiled.facts.declarations.reasoning_efforts.value == declared_efforts


def test_google_scalar_codec_domain_does_not_invent_model_reasoning_facts() -> None:
    caps = _compile(
        LLMProvider.GOOGLE_GEMINI, model="gemini-3-pro-preview"
    ).capabilities
    assert caps.reasoning.supported is False
    assert caps.reasoning.effort_levels == []
    assert caps.request_constraints.known_default is None


def test_google_scalar_codec_domain_does_not_add_undeclared_effort_levels() -> None:
    caps = _compile(
        LLMProvider.GOOGLE_GEMINI,
        model="gemini-3-pro-preview",
        evidence=ProviderCapabilityEvidence(
            reasoning=CatalogFact(state="value", value=True),
            reasoning_efforts=CatalogFact(
                state="value", value=(ModelReasoningEffort.HIGH,)
            ),
        ),
    ).capabilities
    assert caps.reasoning.effort_levels == [ModelReasoningEffort.HIGH]


@pytest.mark.parametrize(
    "model",
    [
        "k3",
        "k3-256k",
        "kimi-for-coding",
        "kimi-for-coding-highspeed",
        "managed-exact-id",
    ],
)
@pytest.mark.parametrize(
    ("declaration", "expected"),
    [
        (CatalogFact[bool](state="absent", value=None), True),
        (CatalogFact[bool](state="null", value=None), True),
        (CatalogFact[bool](state="value", value=True), True),
        (CatalogFact[bool](state="value", value=False), False),
    ],
)
def test_kimi_managed_coding_function_contract_preserves_declarations(
    model: str, declaration: CatalogFact[bool], expected: bool
) -> None:
    compiled = _compile(
        LLMProvider.KIMI_OAUTH,
        model=model,
        evidence=ProviderCapabilityEvidence(function_calling=declaration),
    )
    caps = compiled.capabilities
    assert caps.tool_calling.supported is expected
    assert compiled.facts.declarations.function_calling == declaration
    assert caps.tool_calling.parallel_tool_calls is False
    assert caps.tool_calling.strict_json_schema is False
    assert caps.structured_response is False
    assert caps.reasoning.supported is False
    assert caps.reasoning.effort_levels == []
    assert caps.built_in_tools.supported == []


@pytest.mark.parametrize("source_value", [None, False, True])
def test_kimi_managed_function_contract_preserves_matching_source_denial(
    source_value: bool | None,
) -> None:
    compiled = _compile(
        LLMProvider.KIMI_OAUTH,
        model="managed-exact-id",
        source=_source(
            "kimi_oauth",
            "managed-exact-id",
            {"supports_function_calling": source_value},
        ),
    )
    assert compiled.capabilities.tool_calling.supported is (source_value is not False)
    assert compiled.facts.declarations.function_calling.value is source_value


@pytest.mark.parametrize(
    "provider",
    [
        LLMProvider.OPENAI,
        LLMProvider.XAI,
        LLMProvider.OPENROUTER,
        LLMProvider.GOOGLE_GEMINI,
    ],
)
def test_kimi_function_contract_is_not_a_name_or_developer_guess(
    provider: LLMProvider,
) -> None:
    caps = _compile(
        provider,
        model="kimi-for-coding",
        developer=LLMModelDeveloper.MOONSHOT,
    ).capabilities
    assert caps.tool_calling.supported is False


@pytest.mark.parametrize("provider", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
@pytest.mark.parametrize(
    ("declaration", "expected"),
    [
        (CatalogFact[bool](state="absent", value=None), True),
        (CatalogFact[bool](state="null", value=None), True),
        (CatalogFact[bool](state="value", value=True), True),
        (CatalogFact[bool](state="value", value=False), False),
    ],
)
def test_exact_grok47_hosted_web_contract_preserves_provider_declarations(
    provider: LLMProvider, declaration: CatalogFact[bool], expected: bool
) -> None:
    compiled = _compile(
        provider,
        model="grok-4.7",
        evidence=ProviderCapabilityEvidence(web_search=declaration),
    )
    assert compiled.capabilities.supports(ModelCapabilityFeature.WEB_SEARCH) is expected
    assert compiled.facts.declarations.web_search == declaration


@pytest.mark.parametrize("provider", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
@pytest.mark.parametrize("source_value", [None, False, True])
def test_exact_grok47_hosted_web_contract_preserves_matching_source_denial(
    provider: LLMProvider, source_value: bool | None
) -> None:
    compiled = _compile(
        provider,
        model="grok-4.7",
        source=_source(
            provider.value, "grok-4.7", {"supports_web_search": source_value}
        ),
    )
    assert compiled.capabilities.supports(ModelCapabilityFeature.WEB_SEARCH) is (
        source_value is not False
    )
    assert compiled.facts.declarations.web_search.value is source_value


@pytest.mark.parametrize("provider", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
@pytest.mark.parametrize("model", ["grok-4.70", "grok-4.7-other", "unrelated-model"])
def test_grok47_hosted_web_contract_does_not_predict_other_model_support(
    provider: LLMProvider, model: str
) -> None:
    assert not _compile(provider, model=model).capabilities.supports(
        ModelCapabilityFeature.WEB_SEARCH
    )


@pytest.mark.parametrize("provider", list(LLMProvider))
def test_grok47_hosted_web_contract_is_bound_to_its_actual_auth_routes(
    provider: LLMProvider,
) -> None:
    caps = _compile(provider, model="grok-4.7").capabilities
    assert caps.supports(ModelCapabilityFeature.WEB_SEARCH) is (
        provider in {LLMProvider.XAI, LLMProvider.XAI_OAUTH, LLMProvider.CHATGPT_OAUTH}
    )


@pytest.mark.parametrize("provider_value", [None, False, True])
@pytest.mark.parametrize("source_value", [False, True])
def test_kimi_function_supplement_respects_source_denial_without_changing_facts(
    provider_value: bool | None, source_value: bool
) -> None:
    declaration = CatalogFact[bool](
        state="null" if provider_value is None else "value", value=provider_value
    )
    compiled = _compile(
        LLMProvider.KIMI_OAUTH,
        model="managed-exact-id",
        source=_source(
            "kimi_oauth",
            "managed-exact-id",
            {"supports_function_calling": source_value},
        ),
        evidence=ProviderCapabilityEvidence(function_calling=declaration),
    )
    assert compiled.capabilities.tool_calling.supported is (
        provider_value is True or (provider_value is None and source_value)
    )
    assert compiled.facts.provider_declarations.function_calling == declaration
    assert compiled.facts.declarations.function_calling == declaration
    assert any(
        exclusion.feature == ModelCapabilityFeature.FUNCTION_CALLING
        for exclusion in compiled.route_exclusions
    ) is (source_value is False and provider_value is not True)


@pytest.mark.parametrize("provider", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
@pytest.mark.parametrize("provider_value", [None, False, True])
@pytest.mark.parametrize("source_value", [False, True])
def test_grok_web_supplement_respects_source_denial_without_changing_facts(
    provider: LLMProvider, provider_value: bool | None, source_value: bool
) -> None:
    declaration = CatalogFact[bool](
        state="null" if provider_value is None else "value", value=provider_value
    )
    compiled = _compile(
        provider,
        model="grok-4.7",
        source=_source(
            provider.value, "grok-4.7", {"supports_web_search": source_value}
        ),
        evidence=ProviderCapabilityEvidence(web_search=declaration),
    )
    assert compiled.capabilities.supports(ModelCapabilityFeature.WEB_SEARCH) is (
        provider_value is True or (provider_value is None and source_value)
    )
    assert compiled.facts.provider_declarations.web_search == declaration
    assert compiled.facts.declarations.web_search == declaration
    assert any(
        exclusion.feature == ModelCapabilityFeature.WEB_SEARCH
        for exclusion in compiled.route_exclusions
    ) is (source_value is False and provider_value is not True)


@pytest.mark.parametrize("provider", [LLMProvider.CHATGPT_OAUTH, LLMProvider.XAI_OAUTH])
def test_new_kimi_guard_does_not_change_other_coding_function_contracts(
    provider: LLMProvider,
) -> None:
    namespace = "chatgpt" if provider == LLMProvider.CHATGPT_OAUTH else "xai_oauth"
    declaration = CatalogFact[bool](state="null", value=None)
    compiled = _compile(
        provider,
        source=_source(
            namespace, "literal-model", {"supports_function_calling": False}
        ),
        evidence=ProviderCapabilityEvidence(function_calling=declaration),
    )
    assert compiled.capabilities.tool_calling.supported is True
    assert compiled.facts.declarations.function_calling == declaration
    assert not compiled.route_exclusions


@pytest.mark.parametrize("owner", ["provider", "source"])
@pytest.mark.parametrize(
    "model", ["k3", "k3-256k", "kimi-for-coding", "kimi-for-coding-highspeed"]
)
def test_kimi_declared_efforts_remain_model_facts_outside_current_scalar_codec(
    owner: str, model: str
) -> None:
    declared_efforts = (
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.HIGH,
        ModelReasoningEffort.MAX,
    )
    source = (
        _source(
            "kimi_oauth",
            model,
            {
                "supports_reasoning": True,
                "reasoning_effort_levels": ["low", "high", "max"],
                "default_reasoning_effort": "high",
            },
        )
        if owner == "source"
        else None
    )
    evidence = (
        ProviderCapabilityEvidence(
            reasoning=CatalogFact(state="value", value=True),
            reasoning_efforts=CatalogFact(state="value", value=declared_efforts),
            default_reasoning_effort=CatalogFact(
                state="value", value=ModelReasoningEffort.HIGH
            ),
        )
        if owner == "provider"
        else None
    )
    compiled = _compile(
        LLMProvider.KIMI_OAUTH,
        model=model,
        source=source,
        evidence=evidence,
    )
    assert compiled.capabilities.reasoning.supported is True
    assert compiled.capabilities.reasoning.effort_levels == []
    assert compiled.capabilities.request_constraints.known_default is None
    assert compiled.capabilities.tool_calling.supported is True
    assert compiled.facts.declarations.reasoning.value is True
    assert compiled.facts.declarations.reasoning_efforts.value == declared_efforts
    assert (
        compiled.facts.declarations.default_reasoning_effort.value
        == ModelReasoningEffort.HIGH
    )
    if evidence is not None:
        assert compiled.facts.provider_declarations == evidence
    if source is not None:
        assert compiled.facts.source_model == source
