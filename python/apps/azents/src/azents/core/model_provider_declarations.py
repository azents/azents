"""Pure provider declaration decoding shared by listing and stored-choice adoption."""

from collections.abc import Mapping
from typing import Annotated, assert_never

from pydantic import BaseModel, ConfigDict, Field

from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_catalog_source import CatalogFact


class MalformedProviderDeclarations(ValueError):
    """Malformed upstream facts remain retryable, not user configuration failures."""


class _Declarations(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class _ReasoningLevel(_Declarations):
    effort: str


class _ReasoningPreset(_Declarations):
    id: str | None = None
    value: str | None = None
    default: bool | None = None


class _ChatGPT(_Declarations):
    context_window: int | None = None
    max_context_window: int | None = None
    input_modalities: list[str] | None = None
    supported_reasoning_levels: list[_ReasoningLevel] | None = None
    default_reasoning_level: str | None = None
    supports_parallel_tool_calls: bool | None = None
    supports_reasoning_summaries: bool | None = None
    supports_reasoning_summary_parameter: bool | None = None
    experimental_supported_tools: list[str] | None = None


class _Kimi(_Declarations):
    context_length: int | None = None
    supports_reasoning: bool | None = None
    supports_image_in: bool | None = None
    supports_video_in: bool | None = None


class _Bedrock(_Declarations):
    inputModalities: list[str] | None = None
    outputModalities: list[str] | None = None


class _Vertex(_Declarations):
    inputTokenLimit: int | None = None
    outputTokenLimit: int | None = None


class _Architecture(_Declarations):
    input_modalities: list[str] | None = None
    output_modalities: list[str] | None = None


class _TopProvider(_Declarations):
    max_completion_tokens: int | None = None


class _OpenRouter(_Declarations):
    context_length: int | None = None
    architecture: _Architecture | None = None
    top_provider: _TopProvider | None = None
    supported_parameters: list[str] | None = None


class _XaiCapabilities(_Declarations):
    reasoning: bool | None = None
    reasoning_effort: bool | list[str] | None = None
    default_reasoning_effort: str | None = None


class _Xai(_Declarations):
    context_length: int | None = None
    input_modalities: list[str] | None = None
    output_modalities: list[str] | None = None
    capabilities: _XaiCapabilities | None = None


class _XaiOAuth(_Declarations):
    context_window: int | None = None
    context_windows: list[Annotated[int, Field(ge=0, le=2**63 - 1)]] | None = None
    input_modalities: list[str] | None = None
    output_modalities: list[str] | None = None
    supports_reasoning_effort: bool | None = None
    reasoning_effort: str | None = None
    reasoning_efforts: list[_ReasoningPreset] | None = None
    supports_backend_search: bool | None = None
    api_backend: str | None = None


def _fact[T](model: BaseModel, field: str, value: T | None) -> CatalogFact[T]:
    if field not in model.model_fields_set:
        return CatalogFact(state="absent", value=None)
    return CatalogFact(state="value" if value is not None else "null", value=value)


def _nested[T](
    parent: BaseModel, field: str, model: BaseModel | None, child: str, value: T | None
) -> CatalogFact[T]:
    if field not in parent.model_fields_set:
        return CatalogFact(state="absent", value=None)
    return (
        _fact(model, child, value)
        if model is not None
        else CatalogFact(state="null", value=None)
    )


def _modalities(value: list[str] | None) -> tuple[str, ...] | None:
    return tuple(item.lower() for item in value) if value is not None else None


def _effort(value: str | None) -> ModelReasoningEffort | None:
    return next((item for item in ModelReasoningEffort if item.value == value), None)


def _efforts(value: list[str] | None) -> tuple[ModelReasoningEffort, ...] | None:
    if value is None:
        return None
    return tuple(
        dict.fromkeys(item for raw in value if (item := _effort(raw)) is not None)
    )


def _chatgpt(raw: Mapping[str, object]) -> ProviderCapabilityEvidence:
    data = _ChatGPT.model_validate(raw)
    efforts = _efforts(
        [item.effort for item in data.supported_reasoning_levels]
        if data.supported_reasoning_levels is not None
        else None,
    )
    context = _fact(data, "context_window", data.context_window)
    summaries = (
        _fact(
            data,
            "supports_reasoning_summary_parameter",
            data.supports_reasoning_summary_parameter,
        )
        if "supports_reasoning_summary_parameter" in data.model_fields_set
        else _fact(
            data, "supports_reasoning_summaries", data.supports_reasoning_summaries
        )
    )
    return ProviderCapabilityEvidence(
        default_input_tokens=context,
        max_input_tokens=_fact(data, "max_context_window", data.max_context_window)
        if "max_context_window" in data.model_fields_set
        else context,
        input_modalities=_fact(
            data, "input_modalities", _modalities(data.input_modalities)
        ),
        parallel_function_calling=_fact(
            data, "supports_parallel_tool_calls", data.supports_parallel_tool_calls
        ),
        reasoning=CatalogFact(state="value", value=True)
        if efforts
        else CatalogFact(state="absent", value=None),
        reasoning_efforts=_fact(data, "supported_reasoning_levels", efforts),
        default_reasoning_effort=_fact(
            data,
            "default_reasoning_level",
            _effort(data.default_reasoning_level),
        ),
        reasoning_summaries=summaries,
        client_image_generation=CatalogFact(state="value", value=True)
        if data.experimental_supported_tools is not None
        and "image_generation" in data.experimental_supported_tools
        else CatalogFact(state="absent", value=None),
    )


def _xai(raw: Mapping[str, object]) -> ProviderCapabilityEvidence:
    data = _Xai.model_validate(raw)
    caps = data.capabilities
    raw_efforts = caps.reasoning_effort if caps is not None else None
    if isinstance(raw_efforts, list):
        efforts = _nested(
            data,
            "capabilities",
            caps,
            "reasoning_effort",
            _efforts(raw_efforts),
        )
    elif raw_efforts is False:
        efforts = CatalogFact[tuple[ModelReasoningEffort, ...]](state="value", value=())
    elif raw_efforts is True:
        efforts = CatalogFact[tuple[ModelReasoningEffort, ...]](
            state="absent", value=None
        )
    else:
        efforts = _nested(data, "capabilities", caps, "reasoning_effort", None)
    reasoning = _nested(
        data,
        "capabilities",
        caps,
        "reasoning",
        caps.reasoning if caps is not None else None,
    )
    if reasoning.state == "absent" and (raw_efforts is True or bool(efforts.value)):
        reasoning = CatalogFact(state="value", value=True)
    return ProviderCapabilityEvidence(
        max_input_tokens=_fact(data, "context_length", data.context_length),
        input_modalities=_fact(
            data, "input_modalities", _modalities(data.input_modalities)
        ),
        output_modalities=_fact(
            data, "output_modalities", _modalities(data.output_modalities)
        ),
        reasoning=reasoning,
        reasoning_efforts=efforts,
        default_reasoning_effort=_nested(
            data,
            "capabilities",
            caps,
            "default_reasoning_effort",
            _effort(caps.default_reasoning_effort) if caps is not None else None,
        ),
    )


def _xai_oauth(raw: Mapping[str, object]) -> ProviderCapabilityEvidence:
    data = _XaiOAuth.model_validate(raw)
    levels: tuple[ModelReasoningEffort, ...] | None = None
    defaults: list[ModelReasoningEffort | None] = []
    if data.reasoning_efforts is not None:
        values = []
        for preset in data.reasoning_efforts:
            raw_level = preset.id if preset.id is not None else preset.value
            if raw_level is None:
                raise MalformedProviderDeclarations(
                    "Provider reasoning preset must contain an effort."
                )
            level = _effort(raw_level)
            if level is not None:
                values.append(level)
            if preset.default is True:
                defaults.append(level)
        levels = tuple(values)
    default = defaults[0] if len(defaults) == 1 else None
    declared_default = _fact(
        data,
        "reasoning_effort",
        _effort(data.reasoning_effort),
    )
    if declared_default.state != "absent":
        default = declared_default.value
        if defaults and (len(defaults) != 1 or defaults[0] != default):
            default = None
        if default is not None and levels is not None and default not in levels:
            default = None
    control = _fact(data, "supports_reasoning_effort", data.supports_reasoning_effort)
    efforts: CatalogFact[tuple[ModelReasoningEffort, ...]] = _fact(
        data, "reasoning_efforts", levels
    )
    if control.value is False:
        efforts = CatalogFact(state="value", value=())
        default = None
    elif efforts.state == "absent" and control.state == "null":
        efforts = CatalogFact(state="null", value=None)
    context = _fact(data, "context_window", data.context_window)
    maximum = (
        _fact(
            data,
            "context_windows",
            max(data.context_windows) if data.context_windows else None,
        )
        if "context_windows" in data.model_fields_set
        else context
    )
    if (
        context.value is not None
        and maximum.value is not None
        and context.value > maximum.value
    ):
        raise MalformedProviderDeclarations(
            "Default context window exceeds the advertised maximum."
        )
    backend = _fact(data, "api_backend", data.api_backend)
    return ProviderCapabilityEvidence(
        default_input_tokens=context,
        max_input_tokens=maximum,
        input_modalities=_fact(
            data, "input_modalities", _modalities(data.input_modalities)
        ),
        output_modalities=_fact(
            data, "output_modalities", _modalities(data.output_modalities)
        ),
        reasoning=CatalogFact(state="value", value=True)
        if data.supports_reasoning_effort is True or bool(levels)
        else CatalogFact(state="absent", value=None),
        reasoning_efforts=efforts,
        default_reasoning_effort=CatalogFact(state="value", value=default)
        if default is not None
        else CatalogFact(state="null", value=None)
        if declared_default.state != "absent" or bool(defaults)
        else CatalogFact(state="absent", value=None),
        web_search=_fact(data, "supports_backend_search", data.supports_backend_search),
        responses_api=CatalogFact(state="value", value=backend.value == "responses")
        if backend.state == "value"
        else CatalogFact(state=backend.state, value=None),
    )


def decode_stored_provider_evidence(
    *,
    provider: LLMProvider,
    provider_metadata: Mapping[str, object] | None,
    capability_evidence: ProviderCapabilityEvidence | None,
) -> ProviderCapabilityEvidence:
    """Decode captured own-provider declarations without network or legacy flags."""
    if capability_evidence is not None:
        return capability_evidence
    raw = provider_metadata if provider_metadata is not None else {}
    match provider:
        case LLMProvider.CHATGPT_OAUTH:
            return _chatgpt(raw)
        case LLMProvider.XAI:
            return _xai(raw)
        case LLMProvider.XAI_OAUTH:
            return _xai_oauth(raw)
        case LLMProvider.KIMI_OAUTH:
            data = _Kimi.model_validate(raw)
            return ProviderCapabilityEvidence(
                max_input_tokens=_fact(data, "context_length", data.context_length),
                image_input=_fact(data, "supports_image_in", data.supports_image_in),
                video_input=_fact(data, "supports_video_in", data.supports_video_in),
                reasoning=_fact(data, "supports_reasoning", data.supports_reasoning),
            )
        case LLMProvider.AWS_BEDROCK:
            data = _Bedrock.model_validate(raw)
            return ProviderCapabilityEvidence(
                input_modalities=_fact(
                    data, "inputModalities", _modalities(data.inputModalities)
                ),
                output_modalities=_fact(
                    data, "outputModalities", _modalities(data.outputModalities)
                ),
            )
        case LLMProvider.GOOGLE_VERTEX_AI:
            data = _Vertex.model_validate(raw)
            return ProviderCapabilityEvidence(
                max_input_tokens=_fact(data, "inputTokenLimit", data.inputTokenLimit),
                max_output_tokens=_fact(
                    data, "outputTokenLimit", data.outputTokenLimit
                ),
            )
        case LLMProvider.OPENROUTER:
            data = _OpenRouter.model_validate(raw)
            parameters = data.supported_parameters

            def parameter(*names: str) -> CatalogFact[bool]:
                return _fact(
                    data,
                    "supported_parameters",
                    any(name in parameters for name in names)
                    if parameters is not None
                    else None,
                )

            effort = parameter("reasoning", "reasoning_effort")
            architecture = data.architecture
            top = data.top_provider
            return ProviderCapabilityEvidence(
                max_input_tokens=_fact(data, "context_length", data.context_length),
                max_output_tokens=_nested(
                    data,
                    "top_provider",
                    top,
                    "max_completion_tokens",
                    top.max_completion_tokens if top else None,
                ),
                input_modalities=_nested(
                    data,
                    "architecture",
                    architecture,
                    "input_modalities",
                    _modalities(architecture.input_modalities)
                    if architecture
                    else None,
                ),
                output_modalities=_nested(
                    data,
                    "architecture",
                    architecture,
                    "output_modalities",
                    _modalities(architecture.output_modalities)
                    if architecture
                    else None,
                ),
                function_calling=parameter("tools"),
                parallel_function_calling=parameter("parallel_tool_calls"),
                structured_response=parameter("structured_outputs"),
                reasoning=parameter(
                    "reasoning", "reasoning_effort", "include_reasoning"
                ),
                reasoning_efforts=CatalogFact(state="value", value=())
                if effort.value is False
                else CatalogFact(state="null", value=None)
                if effort.state == "null"
                else CatalogFact(state="absent", value=None),
                temperature=parameter("temperature"),
                top_p=parameter("top_p"),
                top_k=parameter("top_k"),
                stop_sequences=parameter("stop"),
                max_output_parameter=parameter("max_tokens", "max_completion_tokens"),
            )
        case LLMProvider.OPENAI | LLMProvider.ANTHROPIC | LLMProvider.GOOGLE_GEMINI:
            # Current system catalogs use exact captured source records, not an
            # account-list payload. Their source is resolved separately.
            return ProviderCapabilityEvidence()
        case _ as unreachable:
            assert_never(unreachable)
