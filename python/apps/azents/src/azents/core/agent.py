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
DEFAULT_MAIN_MODEL_OPTION_LABEL = "default"
DEFAULT_LIGHTWEIGHT_MODEL_OPTION_LABEL = "lightweight"


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


class SelectableModelOption(BaseModel):
    """Stored selectable model option keyed by label."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="Selectable model label")
    model_selection: AgentModelSelection = Field(
        description="Selectable model selection snapshot"
    )


class BuiltinToolConfig(BaseModel):
    """Built-in tool setting to enable on an Agent."""

    name: str = Field(description="Built-in tool name, for example web_search")
    config: dict[str, object] = Field(
        default_factory=dict, description="Per-tool options"
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
    context_window_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Agent-level context window cap for input budgeting",
    )
    max_output_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Maximum output token count",
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
    builtin_tools: list[BuiltinToolConfig] = Field(
        default_factory=list,
        description="Built-in tool list to enable",
    )
