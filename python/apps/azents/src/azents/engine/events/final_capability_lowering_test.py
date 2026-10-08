"""Complete encoded requests, not authored hints, determine final feature admission."""

import pytest
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.tools import ToolDefinition

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelParameterCapabilities,
    ModelReasoningCapabilities,
    ModelReasoningEffort,
    ModelToolCallingCapabilities,
)
from azents.core.model_capability_contract import (
    ModelCapabilityFeature,
    ModelFeatureCondition,
    ModelRequestConstraints,
)
from azents.engine.events.effective_model_request import (
    normalize_effective_model_request,
)
from azents.engine.events.model_support_contract import validate_saved_model_request
from azents.engine.events.openai_responses import OpenAIResponsesLowerer
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.providers.model_profiles import protocol_for_provider


def _caps() -> ModelCapabilities:
    return ModelCapabilities(
        tool_calling=ModelToolCallingCapabilities(supported=True),
        reasoning=ModelReasoningCapabilities(
            supported=True,
            effort_levels=[ModelReasoningEffort.LOW, ModelReasoningEffort.HIGH],
        ),
        parameters=ModelParameterCapabilities(temperature=True),
        request_constraints=ModelRequestConstraints(
            known_default="low",
            feature_conditions=(
                ModelFeatureCondition(
                    feature=ModelCapabilityFeature.TEMPERATURE,
                    reasoning_efforts=("low",),
                    function_tools=None,
                ),
            ),
        ),
    )


def _pyd(
    provider: LLMProvider,
    capabilities: ModelCapabilities,
    options: dict[str, object],
    *,
    effort: str | None = None,
    developer: LLMModelDeveloper | None = None,
    model: str = "exact",
) -> PydanticAILowerer:
    return PydanticAILowerer(
        top_k=None,
        provider=provider.value,
        provider_id=provider,
        model=model,
        tools=None,
        model_capabilities=capabilities,
        supported_execution_options=[],
        enabled_execution_options=[],
        kwargs=options,
        reasoning_effort=effort,
        model_developer=developer,
    )


@pytest.mark.parametrize(
    "provider",
    [
        LLMProvider.XAI,
        LLMProvider.XAI_OAUTH,
        LLMProvider.OPENROUTER,
        LLMProvider.KIMI_OAUTH,
    ],
)
@pytest.mark.parametrize("reasoning", [None, {}, {"effort": "high"}])
def test_explicit_body_reasoning_never_uses_saved_default(
    provider: LLMProvider, reasoning: object
) -> None:
    with pytest.raises(ValueError, match="conditions"):
        _pyd(
            provider,
            _caps(),
            {"temperature": 0.1, "extra_body": {"reasoning": reasoning}},
        ).lower([], model="exact", native_replay_context=None)


@pytest.mark.parametrize(
    "provider",
    [
        LLMProvider.XAI,
        LLMProvider.XAI_OAUTH,
        LLMProvider.OPENROUTER,
        LLMProvider.KIMI_OAUTH,
    ],
)
def test_actual_omission_uses_saved_default_without_injecting_reasoning(
    provider: LLMProvider,
) -> None:
    request = _pyd(provider, _caps(), {"temperature": 0.0}).lower(
        [], model="exact", native_replay_context=None
    )
    assert request.settings.get("extra_body") == {"temperature": 0.0}


@pytest.mark.parametrize(
    "provider", [LLMProvider.GOOGLE_GEMINI, LLMProvider.GOOGLE_VERTEX_AI]
)
def test_google_encoded_high_beats_selected_low(provider: LLMProvider) -> None:
    with pytest.raises(ValueError, match="conditions"):
        _pyd(
            provider,
            _caps(),
            {"temperature": 0.1, "google_thinking_config": {"thinking_level": "HIGH"}},
            effort="low",
            model="gemini-3-flash-preview",
        ).lower([], model="gemini-3-flash-preview", native_replay_context=None)


@pytest.mark.parametrize("budget", [0, -1, 2048])
def test_google_encoded_budget_is_not_a_default_level(budget: int) -> None:
    with pytest.raises(ValueError, match="conditions"):
        _pyd(
            LLMProvider.GOOGLE_GEMINI,
            _caps(),
            {"temperature": 0.1, "google_thinking_config": {"thinking_budget": budget}},
        ).lower([], model="exact", native_replay_context=None)


def test_bedrock_encoded_effort_wins_without_clamping() -> None:
    with pytest.raises(ValueError, match="conditions"):
        _pyd(
            LLMProvider.AWS_BEDROCK,
            _caps(),
            {
                "temperature": 0.1,
                "bedrock_additional_model_requests_fields": {
                    "output_config": {"effort": "high"}
                },
            },
            effort="low",
            developer=LLMModelDeveloper.ANTHROPIC,
        ).lower([], model="exact", native_replay_context=None)


def test_bedrock_explicit_budget_never_inherits_default() -> None:
    with pytest.raises(ValueError, match="conditions"):
        _pyd(
            LLMProvider.AWS_BEDROCK,
            _caps(),
            {
                "temperature": 0.1,
                "bedrock_additional_model_requests_fields": {
                    "thinking": {"type": "enabled", "budget_tokens": 2048}
                },
            },
            developer=LLMModelDeveloper.ANTHROPIC,
        ).lower([], model="exact", native_replay_context=None)


def test_native_actual_body_replacement_is_checked() -> None:
    lowerer = OpenAIResponsesLowerer(
        top_k=None,
        provider="openai",
        provider_id=LLMProvider.OPENAI,
        model="exact",
        tools=None,
        model_capabilities=_caps(),
        supported_execution_options=[],
        enabled_execution_options=[],
        temperature=0.1,
        kwargs={"reasoning": {"effort": "high"}},
    )
    with pytest.raises(ValueError, match="conditions"):
        lowerer.lower([], model="exact", native_replay_context=None)


@pytest.mark.parametrize(
    "provider",
    [
        LLMProvider.ANTHROPIC,
        LLMProvider.GOOGLE_GEMINI,
        LLMProvider.AWS_BEDROCK,
        LLMProvider.XAI,
        LLMProvider.KIMI_OAUTH,
    ],
)
def test_absent_final_feature_cannot_be_sent(provider: LLMProvider) -> None:
    with pytest.raises(ValueError, match="temperature"):
        _pyd(provider, ModelCapabilities(), {"temperature": 0.1}).lower(
            [], model="exact", native_replay_context=None
        )


def test_output_tools_count_as_function_context() -> None:
    caps = _caps()
    caps.request_constraints = ModelRequestConstraints(
        feature_conditions=(
            ModelFeatureCondition(
                feature=ModelCapabilityFeature.TEMPERATURE,
                reasoning_efforts=None,
                function_tools=False,
            ),
        )
    )
    parameters = ModelRequestParameters(
        output_tools=[
            ToolDefinition(
                name="synthetic_output",
                parameters_json_schema={"type": "object", "properties": {}},
                strict=False,
            )
        ]
    )
    effective = normalize_effective_model_request(
        dialect="anthropic",
        options={"temperature": 0.1},
        parameters=parameters,
        native_tools=None,
    )
    assert effective.function_tools is True
    with pytest.raises(ValueError, match="conditions"):
        validate_saved_model_request(caps, request=effective)


@pytest.mark.parametrize(
    ("publisher", "developer", "field"),
    [
        ("google", LLMModelDeveloper.ANTHROPIC, "google_thinking_config"),
        ("anthropic", LLMModelDeveloper.GOOGLE, "anthropic_effort"),
    ],
)
def test_vertex_encoder_uses_exact_resource_not_saved_developer(
    publisher: str, developer: LLMModelDeveloper, field: str
) -> None:
    model = (
        f"projects/synthetic/locations/us-central1/publishers/{publisher}/models/"
        + ("gemini-3-flash-preview" if publisher == "google" else "claude-exact")
    )
    lowerer = PydanticAILowerer(
        provider="google_vertex_ai",
        provider_id=LLMProvider.GOOGLE_VERTEX_AI,
        model=model,
        model_developer=developer,
        model_capabilities=_caps(),
        tools=None,
        top_k=None,
        temperature=0.1,
        reasoning_effort="low",
        supported_execution_options=[],
        enabled_execution_options=[],
    )
    request = lowerer.lower([], model=model, native_replay_context=None)
    assert protocol_for_provider(
        provider=LLMProvider.GOOGLE_VERTEX_AI, model=model
    ) == ("google" if publisher == "google" else "anthropic")
    assert field in request.settings
    assert ("anthropic_effort" in request.settings) is (publisher == "anthropic")
    assert ("google_thinking_config" in request.settings) is (publisher == "google")


def test_native_custom_declaration_requires_final_function_feature() -> None:
    lowerer = OpenAIResponsesLowerer(
        provider="openai",
        provider_id=LLMProvider.OPENAI,
        model="exact",
        tools=[{"type": "custom", "name": "apply_patch", "description": "Synthetic"}],
        top_k=None,
        model_capabilities=ModelCapabilities(),
        supported_execution_options=[],
        enabled_execution_options=[],
        historical_plaintext_custom_supported=True,
    )
    with pytest.raises(ValueError, match="function_calling"):
        lowerer.lower([], model="exact", native_replay_context=None)
