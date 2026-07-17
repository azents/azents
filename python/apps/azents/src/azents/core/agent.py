"""Agent-related core type definitions."""

import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities, ModelReasoningEffort


class AgentModelSelectionInput(BaseModel):
    """Catalog model selection input."""

    model_config = ConfigDict(extra="forbid")

    llm_provider_integration_id: str = Field(description="LLM provider integration ID")
    model_identifier: str = Field(description="Provider model identifier")


class AgentModelSelection(BaseModel):
    """Model selection snapshot stored on an Agent row."""

    model_config = ConfigDict(extra="forbid")

    llm_provider_integration_id: str = Field(description="LLM provider integration ID")
    provider: LLMProvider = Field(description="LLM hosting provider")
    model_identifier: str = Field(description="Provider model identifier")
    model_display_name: str = Field(description="Model display name")
    model_developer: LLMModelDeveloper = Field(description="Model developer")
    model_family: str | None = Field(default=None, description="Model family")
    normalized_capabilities: ModelCapabilities = Field(
        description="Runtime capability snapshot"
    )
    model_snapshot: dict[str, Any] = Field(description="Normalized model snapshot")
    source_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Source diagnostic metadata",
    )
    last_refreshed_at: datetime.datetime | None = Field(
        default=None,
        description="Latest successful listing refresh timestamp",
    )


MAX_SELECTABLE_MODEL_OPTIONS = 10
MAX_SELECTABLE_MODEL_LABEL_LENGTH = 80
MAX_SUBAGENT_GUIDANCE_LENGTH = 500
DEFAULT_MAIN_MODEL_OPTION_LABEL = "default"
DEFAULT_LIGHTWEIGHT_MODEL_OPTION_LABEL = "lightweight"


class BuiltinToolConfig(BaseModel):
    """Built-in tool setting enabled for one selectable model option."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Built-in tool name, for example web_search")
    config: dict[str, object] = Field(
        default_factory=dict, description="Per-tool options"
    )


class SelectableModelSettingsInput(BaseModel):
    """Optional user settings submitted for one selectable model option."""

    model_config = ConfigDict(extra="forbid")

    context_window_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Model-scoped context window cap for input budgeting",
    )
    max_output_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Model-scoped maximum output token count",
    )
    builtin_tools: list[BuiltinToolConfig] | None = Field(
        default=None,
        description="Enabled built-in tools; omitted enables every supported tool",
    )
    subagent_enabled: bool = Field(
        default=True,
        description="Available as an explicit subagent model target",
    )
    subagent_guidance: str | None = Field(
        default=None,
        max_length=MAX_SUBAGENT_GUIDANCE_LENGTH,
        description="Optional parent-model guidance for explicit subagent selection",
    )


class SelectableModelSettings(BaseModel):
    """Stored user settings for one selectable model option."""

    model_config = ConfigDict(extra="forbid")

    context_window_tokens: int | None = Field(
        ge=1,
        description="Model-scoped context window cap for input budgeting",
    )
    max_output_tokens: int | None = Field(
        ge=1,
        description="Model-scoped maximum output token count",
    )
    builtin_tools: list[BuiltinToolConfig] = Field(
        description="Enabled built-in tools",
    )
    subagent_enabled: bool = Field(
        description="Available as an explicit subagent model target",
    )
    subagent_guidance: str | None = Field(
        max_length=MAX_SUBAGENT_GUIDANCE_LENGTH,
        description="Optional parent-model guidance for explicit subagent selection",
    )


class SelectableModelOptionInput(BaseModel):
    """Selectable model option input keyed by label."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(
        min_length=1,
        max_length=MAX_SELECTABLE_MODEL_LABEL_LENGTH,
        description="Selectable model label",
    )
    model_selection: AgentModelSelectionInput = Field(
        description="Selectable model selection input"
    )
    settings: SelectableModelSettingsInput | None = Field(
        default=None,
        description="Model-scoped settings; omitted uses capability defaults",
    )


class SelectableModelOption(BaseModel):
    """Stored selectable model option keyed by label."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="Selectable model label")
    model_selection: AgentModelSelection = Field(
        description="Selectable model selection snapshot"
    )
    settings: SelectableModelSettings = Field(
        description="Stored model-scoped settings"
    )


def default_selectable_model_settings(
    selection: AgentModelSelection,
) -> SelectableModelSettings:
    """Build model-scoped defaults from implemented capabilities."""
    return SelectableModelSettings(
        context_window_tokens=None,
        max_output_tokens=None,
        builtin_tools=[
            BuiltinToolConfig(name=name)
            for name in dict.fromkeys(
                selection.normalized_capabilities.built_in_tools.supported
            )
        ],
        subagent_enabled=True,
        subagent_guidance=None,
    )


DEFAULT_SUBAGENT_MAX_SUBAGENTS = 3
DEFAULT_SUBAGENT_MAX_DEPTH = 1


class SubagentSettings(BaseModel):
    """Subagent execution settings."""

    model_config = ConfigDict(extra="forbid")

    max_subagents: int = Field(
        default=DEFAULT_SUBAGENT_MAX_SUBAGENTS,
        ge=0,
        description="Maximum active subagents per root session",
    )
    max_depth: int = Field(
        default=DEFAULT_SUBAGENT_MAX_DEPTH,
        ge=0,
        description="Maximum subagent tree depth below the root agent",
    )


class ModelParameters(BaseModel):
    """LLM model parameters.

    Every field is optional; unset fields use model defaults.
    """

    model_config = ConfigDict(extra="forbid")

    temperature: float | None = Field(
        default=None, ge=0.0, le=2.0, description="Generation temperature (0.0-2.0)"
    )
    top_p: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Top-p sampling (0.0-1.0)"
    )
    top_k: int | None = Field(default=None, ge=1, description="Top-k sampling")
    stop_sequences: list[str] | None = Field(
        default=None, max_length=4, description="Stop sequences, up to 4"
    )
    reasoning_effort: ModelReasoningEffort | None = Field(
        default=None,
        description="Reasoning effort, only for models with thinking support",
    )
