"""LLM catalog capability contract models."""

import enum
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from azents.core.builtin_tools import BUILTIN_TOOL_RULES
from azents.core.enums import LLMProvider

INTEGRATION_SCOPED_CATALOG_PROVIDERS: frozenset[LLMProvider] = frozenset(
    {
        LLMProvider.AWS_BEDROCK,
        LLMProvider.CHATGPT_OAUTH,
        LLMProvider.KIMI_OAUTH,
        LLMProvider.GOOGLE_VERTEX_AI,
        LLMProvider.OPENROUTER,
    }
)


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


def build_initial_model_capabilities(
    *, thinking: bool, metadata: Mapping[str, Any] | None
) -> ModelCapabilities:
    """Convert legacy provider model values to initial capability contract."""
    capabilities = ModelCapabilities()
    if thinking:
        capabilities.reasoning.supported = True

    if metadata is None:
        return capabilities

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
