"""Agent service data models."""

import dataclasses
import datetime
from typing import Annotated

from pydantic import BaseModel, Field
from typing_extensions import Self, TypedDict

from azents.core.agent import (
    AgentModelSelection,
    AgentModelSelectionInput,
    ModelParameters,
    SubagentSettings,
)
from azents.core.enums import AgentType
from azents.repos.agent.data import Agent
from azents.services.uploads.schema import UploadedImage


class AgentOutput(BaseModel):
    """Agent output model."""

    id: str
    workspace_id: str
    name: str
    description: str | None
    model_selection: AgentModelSelection | None
    lightweight_model_selection: AgentModelSelection | None
    effective_context_window_tokens: int | None
    effective_auto_compaction_threshold_tokens: int | None
    model_parameters: ModelParameters | None
    system_prompt: str | None
    enabled: bool
    type: AgentType
    runtime_provider_id: str | None
    shell_enabled: bool
    memory_enabled: bool
    max_turns: int | None
    subagent_settings: SubagentSettings
    avatar: UploadedImage | None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @classmethod
    def convert_from(
        cls,
        data: Agent,
        *,
        avatar: UploadedImage | None,
        effective_context_window_tokens: int | None,
        effective_auto_compaction_threshold_tokens: int | None,
    ) -> Self:
        """Create output by combining domain `Agent` and resolved `avatar`."""
        return cls(
            id=data.id,
            workspace_id=data.workspace_id,
            name=data.name,
            description=data.description,
            model_selection=data.model_selection,
            lightweight_model_selection=data.lightweight_model_selection,
            effective_context_window_tokens=effective_context_window_tokens,
            effective_auto_compaction_threshold_tokens=(
                effective_auto_compaction_threshold_tokens
            ),
            model_parameters=data.model_parameters,
            system_prompt=data.system_prompt,
            enabled=data.enabled,
            type=data.type,
            runtime_provider_id=data.runtime_provider_id,
            shell_enabled=data.shell_enabled,
            memory_enabled=data.memory_enabled,
            max_turns=data.max_turns,
            subagent_settings=data.subagent_settings,
            avatar=avatar,
            created_at=data.created_at,
            updated_at=data.updated_at,
        )


@dataclasses.dataclass(frozen=True)
class AvatarUploadTicketOutput:
    """Avatar presigned PUT ticket — service output boundary."""

    upload_key: str
    upload_url: str
    expires_at: datetime.datetime


class AgentCreateInput(BaseModel):
    """Agent create input model."""

    workspace_id: str = Field(description="Workspace ID")
    name: str = Field(description="Agent name")
    model_selection: AgentModelSelectionInput | None = Field(
        default=None,
        description="Main model selection input. Copy workspace default when None",
    )
    lightweight_model_selection: AgentModelSelectionInput | None = Field(
        default=None,
        description="Lightweight model selection input. Copy default/main when None",
    )
    description: str | None = Field(default=None, description="Agent description")
    model_parameters: ModelParameters | None = Field(
        default=None, description="Model parameters"
    )
    system_prompt: str | None = Field(default=None, description="System prompt")
    enabled: bool = Field(default=True, description="Enabled flag")
    type: AgentType = Field(default=AgentType.PUBLIC, description="Visibility scope")
    runtime_provider_id: str | None = Field(
        default=None, description="Runtime Provider logical ID"
    )
    shell_enabled: bool = Field(default=True, description="Shell Enabled flag")
    memory_enabled: bool = Field(default=True, description="Memory enabled flag")
    max_turns: int | None = Field(default=None, description="Maximum agent turn count")
    subagent_settings: SubagentSettings = Field(
        default_factory=SubagentSettings, description="Subagent execution settings"
    )


class AgentUpdateInput(TypedDict, total=False):
    """Agent update input model."""

    name: Annotated[str, Field(description="Agent name")]
    description: Annotated[str | None, Field(description="Agent description")]
    model_selection: Annotated[
        AgentModelSelectionInput | None,
        Field(
            description=("Main model selection input. Copy workspace default when None")
        ),
    ]
    lightweight_model_selection: Annotated[
        AgentModelSelectionInput | None,
        Field(
            description=(
                "Lightweight model selection input. Copy default/main when None"
            )
        ),
    ]
    model_parameters: Annotated[
        ModelParameters | None, Field(description="Model parameters")
    ]
    system_prompt: Annotated[str | None, Field(description="System prompt")]
    enabled: Annotated[bool, Field(description="Enabled flag")]
    type: Annotated[AgentType, Field(description="Visibility scope")]
    runtime_provider_id: Annotated[
        str | None, Field(description="Runtime Provider logical ID")
    ]
    shell_enabled: Annotated[bool, Field(description="Shell Enabled flag")]
    memory_enabled: Annotated[bool, Field(description="Memory enabled flag")]
    max_turns: Annotated[int | None, Field(description="Maximum agent turn count")]
    subagent_settings: Annotated[
        SubagentSettings, Field(description="Subagent execution settings")
    ]


class AgentListOutput(BaseModel):
    """Agent list output model."""

    items: list[AgentOutput] = Field(description="Agent list")


class AgentAdminOutput(BaseModel):
    """AgentAdmin output model."""

    id: str = Field(description="AgentAdmin ID")
    agent_id: str = Field(description="Agent ID")
    workspace_user_id: str = Field(description="WorkspaceUser ID")
    created_at: datetime.datetime = Field(description="Created time")


class AgentAdminListOutput(BaseModel):
    """AgentAdmin list output model."""

    items: list[AgentAdminOutput] = Field(description="Admin list")


@dataclasses.dataclass(frozen=True)
class NotBelongToWorkspace:
    """Resource does not belong to requested workspace."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class ModelRequired:
    """Model selection is required."""

    workspace_id: str


@dataclasses.dataclass(frozen=True)
class ModelSelectionNotFound:
    """Selected model candidate not found."""

    llm_provider_integration_id: str
    model_identifier: str


@dataclasses.dataclass(frozen=True)
class InvalidModelParameters:
    """Model parameter payload is invalid."""

    errors: list[str]


@dataclasses.dataclass(frozen=True)
class NotAdmin:
    """Requester is not Agent admin."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class PrivateAgentAccessDenied:
    """No access permission to Private Agent."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class LastAdminCannotBeRemoved:
    """Last admin cannot be removed."""

    agent_id: str
    workspace_user_id: str


@dataclasses.dataclass(frozen=True)
class AdminNotFound:
    """Target is not Agent admin."""

    agent_id: str
    workspace_user_id: str


@dataclasses.dataclass(frozen=True)
class DuplicateAdmin:
    """Already admin."""

    agent_id: str
    workspace_user_id: str


@dataclasses.dataclass(frozen=True)
class WorkspaceUserNotFound:
    """WorkspaceUser not found."""

    workspace_user_id: str


@dataclasses.dataclass(frozen=True)
class BuiltinToolValidationFailed:
    """Built-in tool validation failed."""

    errors: dict[str, list[str]]


@dataclasses.dataclass(frozen=True)
class AvatarUploadRejected:
    """Avatar upload violates handler constraints."""

    message: str
