"""Workspace model settings service data models."""

import dataclasses

from pydantic import BaseModel, Field

from azents.core.agent import (
    AgentModelSelection,
    AgentModelSelectionInput,
    SelectableModelOption,
    SelectableModelOptionInput,
)


class WorkspaceModelSettingsOutput(BaseModel):
    """Workspace model settings output."""

    default_model_selection: AgentModelSelection | None = Field(
        default=None, description="Default main model selection snapshot"
    )
    default_lightweight_model_selection: AgentModelSelection | None = Field(
        default=None, description="Default lightweight model selection snapshot"
    )
    default_selectable_model_options: list[SelectableModelOption] | None = Field(
        default=None, description="Ordered default selectable model options"
    )
    default_main_model_label: str | None = Field(
        default=None, description="Default main model option label"
    )
    default_lightweight_model_label: str | None = Field(
        default=None, description="Default lightweight model option label"
    )
    effective_default_lightweight_model_selection: AgentModelSelection | None = Field(
        default=None, description="Effective default lightweight model selection"
    )


class WorkspaceModelSettingsUpdateInput(BaseModel):
    """Workspace model settings update input."""

    default_model_selection: AgentModelSelectionInput | None = Field(
        default=None, description="Default main model selection input"
    )
    default_lightweight_model_selection: AgentModelSelectionInput | None = Field(
        default=None, description="Default lightweight model selection input"
    )
    default_selectable_model_options: list[SelectableModelOptionInput] | None = Field(
        default=None, description="Ordered default selectable model option inputs"
    )
    default_main_model_label: str | None = Field(
        default=None, description="Default main model option label"
    )
    default_lightweight_model_label: str | None = Field(
        default=None, description="Default lightweight model option label"
    )


@dataclasses.dataclass(frozen=True)
class ModelSelectionNotFound:
    """Selected model candidate not found."""

    llm_provider_integration_id: str
    model_identifier: str


@dataclasses.dataclass(frozen=True)
class DefaultModelCannotBeCleared:
    """Default model cannot be deleted."""

    workspace_id: str


@dataclasses.dataclass(frozen=True)
class InvalidSelectableModelOptions:
    """Selectable model option payload is invalid."""

    errors: list[str]
