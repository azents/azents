"""Workspace model settings repository data models."""

import dataclasses
import datetime
from typing import Annotated

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from azents.core.agent import AgentModelSelection


class WorkspaceModelSettings(BaseModel):
    """Workspace default model settings."""

    workspace_id: str = Field(description="Workspace ID")
    default_model_selection: AgentModelSelection | None = Field(
        default=None, description="Default main model selection snapshot"
    )
    default_lightweight_model_selection: AgentModelSelection | None = Field(
        default=None, description="Default lightweight model selection snapshot"
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


@dataclasses.dataclass(frozen=True)
class DefaultModelCannotBeCleared:
    """Default model cannot be deleted."""

    workspace_id: str
