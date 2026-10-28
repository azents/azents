"""Request-local projection of existing Agent settings, not a policy store."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
Feature = Literal[
    "function_calling",
    "parallel_function_calls",
    "strict_function_schema",
    "structured_response",
    "reasoning",
    "reasoning_summaries",
    "temperature",
    "max_output_tokens",
    "top_p",
    "top_k",
    "stop_sequences",
    "input:text",
    "input:image",
    "input:pdf",
    "input:audio",
    "input:video",
    "output:text",
    "output:image",
    "output:pdf",
    "output:audio",
    "output:video",
    "builtin:web_search",
    "builtin:image_generation",
]
PositiveTokens = Annotated[int, Field(ge=1)]


class SettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class BuiltinToolSetting(SettingsPayload):
    """Saved tool-local configuration, never merged into transport/SDK kwargs."""

    name: Literal["web_search", "image_generation"]
    config: dict[str, JsonValue]


class FeatureCondition(SettingsPayload):
    feature: Feature
    reasoning_efforts: tuple[ReasoningEffort, ...] | None
    function_tools: bool | None


class GenerationSettings(SettingsPayload):
    temperature: Annotated[float, Field(ge=0, le=2)] | None
    top_p: Annotated[float, Field(ge=0, le=1)] | None
    top_k: Annotated[int, Field(ge=1)] | None
    stop_sequences: Annotated[tuple[str, ...], Field(max_length=4)] | None
    reasoning_effort: ReasoningEffort | None


class ModelConfiguration(SettingsPayload):
    """Current selected candidate and Agent controls, without snapshot diagnostics.

    Null candidate caps retain their existing unset semantics. Output cap clamping
    and provider field mapping belong to the actual request normalizer, not this
    transport projection. Tool configurations remain tool-local typed inputs.
    """

    protocol: Literal[
        "native_responses", "responses", "chat", "anthropic", "google", "bedrock"
    ]
    parameters: GenerationSettings | None
    context_window_tokens: PositiveTokens | None
    max_output_tokens: PositiveTokens | None
    default_input_tokens: PositiveTokens | None
    maximum_input_tokens: PositiveTokens | None
    maximum_output_tokens: PositiveTokens | None
    builtin_tools: tuple[BuiltinToolSetting, ...]
    supported_features: tuple[Feature, ...]
    reasoning_efforts: tuple[ReasoningEffort, ...]
    known_default_reasoning: ReasoningEffort | None
    feature_conditions: tuple[FeatureCondition, ...]
    supported_execution_options: tuple[Literal["fast", "ultrafast"], ...]
