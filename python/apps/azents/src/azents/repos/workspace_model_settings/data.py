"""Workspace model settings repository data models."""

import dataclasses
import datetime
from typing import Annotated

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from azents.core.agent import AgentModelSelection, SelectableModelOption


class WorkspaceModelSettings(BaseModel):
    """Workspace default model settings."""

    workspace_id: str = Field(description="Workspace ID")
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
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class WorkspaceModelSettingsUpdate(TypedDict, total=False):
    """Workspace model settings update payload."""

    default_model_selection: Annotated[
        AgentModelSelection | None,
        Field(description="Default main model selection snapshot"),
    ]
    default_lightweight_model_selection: Annotated[
        AgentModelSelection | None,
        Field(description="Default lightweight model selection snapshot"),
    ]
    default_selectable_model_options: Annotated[
        list[SelectableModelOption] | None,
        Field(description="Ordered default selectable model options"),
    ]
    default_main_model_label: Annotated[
        str | None, Field(description="Default main model option label")
    ]
    default_lightweight_model_label: Annotated[
        str | None, Field(description="Default lightweight model option label")
    ]


@dataclasses.dataclass(frozen=True)
class DefaultModelCannotBeCleared:
    """Default model cannot be deleted."""

    workspace_id: str
