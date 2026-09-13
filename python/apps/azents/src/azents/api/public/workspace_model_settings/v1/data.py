"""Workspace model settings v1 Public API data models."""

from pydantic import BaseModel, ConfigDict, Field

from azents.core.agent import (
    SelectableModelOption,
    SelectableModelOptionInput,
)
from azents.services.workspace_model_settings.data import WorkspaceModelSettingsOutput


class WorkspaceModelSettingsResponse(BaseModel):
    """Workspace model settings response."""

    default_selectable_model_options: list[SelectableModelOption] | None = Field(
        default=None, description="Ordered default selectable model options"
    )
    default_main_model_label: str | None = Field(
        default=None, description="Default main model option label"
    )
    default_lightweight_model_label: str | None = Field(
        default=None, description="Default lightweight model option label"
    )

    @classmethod
    def convert_from(
        cls,
        data: WorkspaceModelSettingsOutput,
    ) -> "WorkspaceModelSettingsResponse":
        """Convert service output to response model."""
        return cls(
            default_selectable_model_options=data.default_selectable_model_options,
            default_main_model_label=data.default_main_model_label,
            default_lightweight_model_label=data.default_lightweight_model_label,
        )


class WorkspaceModelSettingsUpdateRequest(BaseModel):
    """Workspace model settings update request."""

    model_config = ConfigDict(extra="forbid")

    default_selectable_model_options: list[SelectableModelOptionInput] | None = Field(
        default=None, description="Ordered default selectable model option inputs"
    )
    default_main_model_label: str | None = Field(
        default=None, description="Default main model option label"
    )
    default_lightweight_model_label: str | None = Field(
        default=None, description="Default lightweight model option label"
    )
