"""Single final LLM capability view and descriptive route metadata."""

import enum
import re
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from azents.core._legacy_model_capability_contract import decode_historical_capabilities
from azents.core.builtin_tools import BUILTIN_TOOL_RULES
from azents.core.enums import LLMProvider
from azents.core.model_capability_contract import (
    ModelCapabilityFeature,
    ModelRequestConstraints,
)

INTEGRATION_SCOPED_CATALOG_PROVIDERS: frozenset[LLMProvider] = frozenset(
    {
        LLMProvider.AWS_BEDROCK,
        LLMProvider.CHATGPT_OAUTH,
        LLMProvider.XAI,
        LLMProvider.XAI_OAUTH,
        LLMProvider.KIMI_OAUTH,
        LLMProvider.GOOGLE_VERTEX_AI,
        LLMProvider.OPENROUTER,
    }
)


def model_freshness_rank(model_identifier: str) -> int:
    """Rank model identifiers so newer generations sort first."""
    match = re.search(r"(\d+)(?:\.(\d+))?", model_identifier)
    if match is None:
        return 0
    major = int(match.group(1))
    minor = int(match.group(2) or "0")
    preview_bonus = 1 if "preview" in model_identifier.lower() else 0
    return major * 1000 + minor * 10 + preview_bonus


class ModelModality(enum.StrEnum):
    """Normalized model input/output modality."""

    TEXT = "text"
    IMAGE = "image"
    PDF = "pdf"
    AUDIO = "audio"
    VIDEO = "video"


class ModelReasoningEffort(enum.StrEnum):
    """Normalized reasoning effort level in ascending order."""

    NONE = "none"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class UnsupportedMediaPolicy(enum.StrEnum):
    """Descriptive unsupported media handling policy."""

    TEXT_SUBSTITUTION = "text_substitution"
    BLOCK = "block"


class ModelContextWindow(BaseModel):
    """Saved context limits, independent of supported control membership."""

    model_config = ConfigDict(extra="ignore")

    default_input_tokens: int | None = Field(default=None, ge=1)
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)


class ModelModalities(BaseModel):
    """Supported input/output forms; absent entries mean unsupported."""

    model_config = ConfigDict(extra="ignore")

    input: list[ModelModality] = Field(default_factory=list)
    output: list[ModelModality] = Field(default_factory=list)

    @field_validator("input", "output")
    @classmethod
    def validate_unique_modalities(
        cls, value: list[ModelModality]
    ) -> list[ModelModality]:
        """Reject duplicate membership rather than storing conflicting lists."""
        if len(value) != len(set(value)):
            raise ValueError("Supported modalities must be unique.")
        return value


class ModelToolCallingCapabilities(BaseModel):
    """Final function and function-schema capabilities."""

    model_config = ConfigDict(extra="ignore")

    supported: bool = False
    parallel_tool_calls: bool = False
    strict_json_schema: bool = False

    @field_validator("parallel_tool_calls", "strict_json_schema", mode="before")
    @classmethod
    def decode_historical_null(cls, value: object) -> object:
        """Read old null flags as absent final features, never permissive states."""
        return False if value is None else value


class ModelReasoningCapabilities(BaseModel):
    """Final reasoning support and the supported selectable effort list."""

    model_config = ConfigDict(extra="ignore")

    supported: bool = False
    effort_levels: list[ModelReasoningEffort] = Field(default_factory=list)
    summaries: bool = False

    @field_validator("summaries", mode="before")
    @classmethod
    def decode_historical_null(cls, value: object) -> object:
        """Retain historical readability without a final unknown state."""
        return False if value is None else value


class ModelBuiltInToolCapabilities(BaseModel):
    """Supported route-projected built-in tools."""

    model_config = ConfigDict(extra="ignore")

    supported: list[str] = Field(default_factory=list)

    @field_validator("supported")
    @classmethod
    def validate_known_tools(cls, value: list[str]) -> list[str]:
        """Allow only unique registered built-in tools."""
        if set(value) - set(BUILTIN_TOOL_RULES):
            raise ValueError("Unknown built-in tools are not supported.")
        if len(value) != len(set(value)):
            raise ValueError("Supported built-in tools must be unique.")
        return value


class ModelParameterCapabilities(BaseModel):
    """Final supported generation controls."""

    model_config = ConfigDict(extra="ignore")

    temperature: bool = False
    max_output_tokens: bool = False
    top_p: bool = False
    top_k: bool = False
    stop_sequences: bool = False


class ModelCompatibilityCapabilities(BaseModel):
    """Descriptive route metadata; never a second feature admission authority."""

    model_config = ConfigDict(extra="ignore")

    provider_family: str | None = None
    responses_api: bool | None = None
    unsupported_media_policy: UnsupportedMediaPolicy | None = None


class ModelCapabilities(BaseModel):
    """One final boolean/list feature contract with separate request constraints."""

    model_config = ConfigDict(extra="ignore")

    capability_schema_version: Literal[3] = 3
    context_window: ModelContextWindow = Field(default_factory=ModelContextWindow)
    modalities: ModelModalities = Field(default_factory=ModelModalities)
    tool_calling: ModelToolCallingCapabilities = Field(
        default_factory=ModelToolCallingCapabilities
    )
    reasoning: ModelReasoningCapabilities = Field(
        default_factory=ModelReasoningCapabilities
    )
    built_in_tools: ModelBuiltInToolCapabilities = Field(
        default_factory=ModelBuiltInToolCapabilities
    )
    parameters: ModelParameterCapabilities = Field(
        default_factory=ModelParameterCapabilities
    )
    compatibility: ModelCompatibilityCapabilities = Field(
        default_factory=ModelCompatibilityCapabilities
    )
    structured_response: bool = False
    request_constraints: ModelRequestConstraints = Field(
        default_factory=ModelRequestConstraints
    )

    @model_validator(mode="before")
    @classmethod
    def decode_historical_descriptor(cls, value: object) -> object:
        """Decode old JSON without writing rows or restoring unknown support."""
        if not isinstance(value, Mapping):
            return value
        if (
            value.get("capability_schema_version") == 3
            and value.get("semantic_contract") is not None
        ):
            raise ValueError("Final capabilities cannot contain a semantic descriptor.")
        return decode_historical_capabilities(value)

    def configurable_reasoning_efforts(self) -> list[ModelReasoningEffort]:
        """Expose final declared levels; dispatch owns effective request conditions."""
        return list(self.reasoning.effort_levels) if self.reasoning.supported else []

    def supported_features(self) -> frozenset[ModelCapabilityFeature]:
        """Derive membership from final fields without storing a second list."""
        flags = {
            ModelCapabilityFeature.FUNCTION_CALLING: self.tool_calling.supported,
            ModelCapabilityFeature.PARALLEL_FUNCTION_CALLS: (
                self.tool_calling.parallel_tool_calls
            ),
            ModelCapabilityFeature.STRICT_FUNCTION_SCHEMA: (
                self.tool_calling.strict_json_schema
            ),
            ModelCapabilityFeature.STRUCTURED_RESPONSE: self.structured_response,
            ModelCapabilityFeature.REASONING: self.reasoning.supported,
            ModelCapabilityFeature.REASONING_SUMMARIES: self.reasoning.summaries,
            ModelCapabilityFeature.TEMPERATURE: self.parameters.temperature,
            ModelCapabilityFeature.MAX_OUTPUT_TOKENS: self.parameters.max_output_tokens,
            ModelCapabilityFeature.TOP_P: self.parameters.top_p,
            ModelCapabilityFeature.TOP_K: self.parameters.top_k,
            ModelCapabilityFeature.STOP_SEQUENCES: self.parameters.stop_sequences,
        }
        features = {feature for feature, present in flags.items() if present}
        features.update(
            ModelCapabilityFeature(f"input:{modality.value}")
            for modality in self.modalities.input
        )
        features.update(
            ModelCapabilityFeature(f"output:{modality.value}")
            for modality in self.modalities.output
        )
        features.update(
            ModelCapabilityFeature(f"builtin:{tool}")
            for tool in self.built_in_tools.supported
        )
        return frozenset(features)

    def supports(self, feature: ModelCapabilityFeature) -> bool:
        """Return feature membership without evaluating an incomplete request."""
        return feature in self.supported_features()

    @model_validator(mode="after")
    def validate_final_capabilities(self) -> Self:
        """Keep metadata subordinate to the single final feature view."""
        features = self.supported_features()
        for condition in self.request_constraints.feature_conditions:
            if condition.feature not in features:
                raise ValueError("A feature condition requires a present feature.")
        if self.reasoning.effort_levels and not self.reasoning.supported:
            raise ValueError("Reasoning effort levels require reasoning support.")
        if len(self.reasoning.effort_levels) != len(set(self.reasoning.effort_levels)):
            raise ValueError("Reasoning effort levels must be unique.")
        if not self.tool_calling.supported and (
            self.tool_calling.parallel_tool_calls
            or self.tool_calling.strict_json_schema
        ):
            raise ValueError("Function refinements require function calling support.")
        return self


def build_initial_model_capabilities(
    *, thinking: bool, metadata: Mapping[str, Any] | None
) -> ModelCapabilities:
    """Convert legacy provider model values to initial capability fields."""
    capabilities = ModelCapabilities()
    if thinking:
        capabilities.reasoning.supported = True
    if metadata is None:
        return capabilities
    default_input_tokens = metadata.get("default_input_tokens")
    if (
        isinstance(default_input_tokens, int)
        and not isinstance(default_input_tokens, bool)
        and default_input_tokens > 0
    ):
        capabilities.context_window.default_input_tokens = default_input_tokens
    max_input_tokens = metadata.get("max_input_tokens")
    if (
        isinstance(max_input_tokens, int)
        and not isinstance(max_input_tokens, bool)
        and max_input_tokens > 0
    ):
        capabilities.context_window.max_input_tokens = max_input_tokens
    supported_builtin_tools = metadata.get("supported_builtin_tools")
    if isinstance(supported_builtin_tools, list):
        capabilities.built_in_tools.supported = list(
            dict.fromkeys(
                tool_id
                for tool_id in supported_builtin_tools
                if isinstance(tool_id, str) and tool_id in BUILTIN_TOOL_RULES
            )
        )
    return capabilities
