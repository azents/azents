"""Workspace model settings v1 Public API data models."""

from pydantic import BaseModel, Field

from azents.core.agent import AgentModelSelection, AgentModelSelectionInput
from azents.services.workspace_model_settings.data import WorkspaceModelSettingsOutput


class WorkspaceModelSettingsResponse(BaseModel):
    """Workspace model settings response."""

    default_model_selection: AgentModelSelection | None = Field(
        default=None, description="Default main model selection snapshot"
    )
    default_lightweight_model_selection: AgentModelSelection | None = Field(
        default=None, description="Default lightweight model selection snapshot"
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
