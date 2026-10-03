"""LLM catalog capability contract models."""

import enum
import re
from collections.abc import Mapping
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from azents.core.builtin_tools import BUILTIN_TOOL_RULES
from azents.core.enums import LLMProvider
from azents.core.model_capability_contract import ModelCapabilityContract

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
    """Unsupported media handling policy."""

    TEXT_SUBSTITUTION = "text_substitution"
    BLOCK = "block"


class ModelContextWindow(BaseModel):
    """Model context window capability."""

    model_config = ConfigDict(extra="ignore")

    default_input_tokens: int | None = Field(default=None, ge=1)
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)


class ModelModalities(BaseModel):
    """Input/output modalities supported by the model."""

    model_config = ConfigDict(extra="ignore")

    input: list[ModelModality] = Field(default_factory=list)
    output: list[ModelModality] = Field(default_factory=list)


class ModelToolCallingCapabilities(BaseModel):
    """Represents tool calling capability."""

    model_config = ConfigDict(extra="ignore")

    supported: bool = False
    parallel_tool_calls: bool | None = None
    strict_json_schema: bool | None = None


class ModelReasoningCapabilities(BaseModel):
    """Represents reasoning capability."""

    model_config = ConfigDict(extra="ignore")
    supported: bool = False
    effort_levels: list[ModelReasoningEffort] = Field(default_factory=list)
    summaries: bool | None = None


class ModelBuiltInToolCapabilities(BaseModel):
    """Represents provider built-in tool capability."""

    model_config = ConfigDict(extra="ignore")
    supported: list[str] = Field(default_factory=list)

    @field_validator("supported")
    @classmethod
    def validate_known_tools(cls, value: list[str]) -> list[str]:
        """Allow only registered built-in tools."""
        unknown = set(value) - set(BUILTIN_TOOL_RULES)
        if unknown:
            raise ValueError("Unknown built-in tools are not supported.")
        return value


class ModelParameterCapabilities(BaseModel):
    """Configurable generation parameters supported by the model."""

    model_config = ConfigDict(extra="ignore")

    temperature: bool = False
    max_output_tokens: bool = False
    top_p: bool = False
    top_k: bool = False
    stop_sequences: bool = False


class ModelCompatibilityCapabilities(BaseModel):
    """Provider compatibility capability."""

    model_config = ConfigDict(extra="ignore")
    provider_family: str | None = None
    responses_api: bool | None = None
    unsupported_media_policy: UnsupportedMediaPolicy | None = None


class ModelCapabilities(BaseModel):
    """Normalized LLM model capability contract."""

    model_config = ConfigDict(extra="ignore")

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
    # Descriptor absence is the approved historical snapshot boundary.
    semantic_contract: ModelCapabilityContract | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    def configurable_reasoning_efforts(self) -> list[ModelReasoningEffort]:
        """Expose known selection potential; dispatch evaluates actual conditions."""
        contract = self.semantic_contract
        if contract is None:
            return list(self.reasoning.effort_levels)
        support = contract.reasoning.support
        if support.state not in {"supported", "conditional"}:
            return []
        predicate = support.predicate
        return [
            ModelReasoningEffort(declaration.level)
            for declaration in contract.reasoning.efforts
            if declaration.state == "supported"
            and (
                predicate is None
                or predicate.reasoning_efforts is None
                or declaration.level in predicate.reasoning_efforts
            )
        ]

    @model_validator(mode="after")
    def validate_semantic_views(self) -> Self:
        """Reject competing boolean/list facts for a versioned semantic contract."""
        contract = self.semantic_contract
        if contract is None:
            return self
        flag_views = (
            (
                "tool_calling.supported",
                self.tool_calling.supported,
                contract.function_calling.enabled,
            ),
            (
                "tool_calling.parallel_tool_calls",
                self.tool_calling.parallel_tool_calls,
                contract.parallel_function_calls.nullable_enabled,
            ),
            (
                "tool_calling.strict_json_schema",
                self.tool_calling.strict_json_schema,
                contract.strict_function_schema.nullable_enabled,
            ),
            (
                "reasoning.supported",
                self.reasoning.supported,
                contract.reasoning.support.enabled,
            ),
            (
                "reasoning.summaries",
                self.reasoning.summaries,
                contract.reasoning_summaries.nullable_enabled,
            ),
            (
                "parameters.temperature",
                self.parameters.temperature,
                contract.parameters.temperature.enabled,
            ),
            (
                "parameters.max_output_tokens",
                self.parameters.max_output_tokens,
                contract.parameters.max_output_tokens.enabled,
            ),
            (
                "parameters.top_p",
                self.parameters.top_p,
                contract.parameters.top_p.enabled,
            ),
            (
                "parameters.top_k",
                self.parameters.top_k,
                contract.parameters.top_k.enabled,
            ),
            (
                "parameters.stop_sequences",
                self.parameters.stop_sequences,
                contract.parameters.stop_sequences.enabled,
            ),
        )
        for name, actual, expected in flag_views:
            if actual != expected:
                raise ValueError(f"{name} must match the saved semantic contract.")
        list_views = (
            (
                "reasoning.effort_levels",
                [level.value for level in self.reasoning.effort_levels],
                list(contract.reasoning.enabled_efforts),
            ),
            (
                "modalities.input",
                [modality.value for modality in self.modalities.input],
                [
                    declaration.modality
                    for declaration in contract.input_modalities
                    if declaration.support.enabled
                ],
            ),
            (
                "modalities.output",
                [modality.value for modality in self.modalities.output],
                [
                    declaration.modality
                    for declaration in contract.output_modalities
                    if declaration.support.enabled
                ],
            ),
            (
                "built_in_tools.supported",
                self.built_in_tools.supported,
                [
                    declaration.tool
                    for declaration in contract.built_in_tools
                    if declaration.support.enabled
                ],
            ),
        )
        for name, actual, expected in list_views:
            if actual != expected:
                raise ValueError(f"{name} must match the saved semantic contract.")
        return self


def build_initial_model_capabilities(
    *, thinking: bool, metadata: Mapping[str, Any] | None
) -> ModelCapabilities:
    """Convert legacy provider model values to initial capability contract."""
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
    if isinstance(max_input_tokens, int) and not isinstance(max_input_tokens, bool):
        if max_input_tokens > 0:
            capabilities.context_window.max_input_tokens = max_input_tokens

    supported_builtin_tools = metadata.get("supported_builtin_tools")
    if isinstance(supported_builtin_tools, list):
        capabilities.built_in_tools.supported = [
            tool_id
            for tool_id in supported_builtin_tools
            if isinstance(tool_id, str) and tool_id in BUILTIN_TOOL_RULES
        ]

    return capabilities
