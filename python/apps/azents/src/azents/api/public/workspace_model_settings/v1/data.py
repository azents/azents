"""Workspace model settings v1 Public API data models."""

from pydantic import BaseModel, Field

from azents.core.agent import (
    AgentModelSelection,
    AgentModelSelectionInput,
    SelectableModelOption,
    SelectableModelOptionInput,
)
from azents.services.workspace_model_settings.data import WorkspaceModelSettingsOutput


class WorkspaceModelSettingsResponse(BaseModel):
    """Workspace model settings response."""

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

    @classmethod
    def convert_from(
        cls,
        data: WorkspaceModelSettingsOutput,
    ) -> "WorkspaceModelSettingsResponse":
        """Convert service output to response model."""
        return cls(
            default_model_selection=data.default_model_selection,
            default_lightweight_model_selection=data.default_lightweight_model_selection,
            default_selectable_model_options=data.default_selectable_model_options,
            default_main_model_label=data.default_main_model_label,
            default_lightweight_model_label=data.default_lightweight_model_label,
            effective_default_lightweight_model_selection=(
                data.effective_default_lightweight_model_selection
            ),
        )


class WorkspaceModelSettingsUpdateRequest(BaseModel):
    """Workspace model settings update request."""

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
