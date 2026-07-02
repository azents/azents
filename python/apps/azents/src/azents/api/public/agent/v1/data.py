"""Agent v1 Public API data models."""

import datetime
from typing import Annotated

from pydantic import BaseModel, Field
from typing_extensions import Self, TypedDict

from azents.core.agent import (
    AgentModelSelection,
    AgentModelSelectionInput,
    ModelParameters,
)
from azents.core.enums import AgentRole, AgentType
from azents.repos.agent_subagent.data import SubagentToolkitInheritMode
from azents.repos.memory.data import MemoryScope
from azents.services.agent.data import (
    AgentAdminOutput,
    AgentOutput,
    AvatarUploadTicketOutput,
)
from azents.services.agent_subagent.data import (
    AgentSubagentOutput,
    AgentSubagentUpdateInput,
)
from azents.services.memory.data import MemoryOutput
from azents.services.uploads.schema import UploadedImage


class AgentResponse(BaseModel):
    """Agent response."""

    id: str
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
    role: AgentRole
    runtime_provider_id: str | None
    shell_enabled: bool
    memory_enabled: bool
    max_turns: int | None
    toolkit_inherit_mode: SubagentToolkitInheritMode
    avatar: UploadedImage | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @classmethod
    def convert_from(cls, data: AgentOutput) -> Self:
        """Convert service output to a response object."""
        return cls(
            id=data.id,
            name=data.name,
            description=data.description,
            model_selection=data.model_selection,
            lightweight_model_selection=data.lightweight_model_selection,
            effective_context_window_tokens=data.effective_context_window_tokens,
            effective_auto_compaction_threshold_tokens=(
                data.effective_auto_compaction_threshold_tokens
            ),
            model_parameters=data.model_parameters,
            system_prompt=data.system_prompt,
            enabled=data.enabled,
            type=data.type,
            role=data.role,
            runtime_provider_id=data.runtime_provider_id,
            shell_enabled=data.shell_enabled,
            memory_enabled=data.memory_enabled,
            max_turns=data.max_turns,
            toolkit_inherit_mode=data.toolkit_inherit_mode,
            avatar=data.avatar,
            created_at=data.created_at,
            updated_at=data.updated_at,
        )


class AgentListResponse(BaseModel):
    """Agent list response."""

    items: list[AgentResponse]


class AgentCreateRequest(BaseModel):
    """Agent creation request."""

    name: str = Field(description="Agent name")
    model_selection: AgentModelSelectionInput | None = Field(
        default=None,
        description="Main model selection. Copies workspace default when None",
    )
    lightweight_model_selection: AgentModelSelectionInput | None = Field(
        default=None,
        description="Lightweight model selection. Copies default/main when None",
    )
    description: str | None = Field(default=None, description="Agent description")
    model_parameters: ModelParameters | None = Field(
        default=None, description="Model parameters"
    )
    system_prompt: str | None = Field(default=None, description="System prompt")
    enabled: bool = Field(default=True, description="Enabled state")
    type: AgentType = Field(default=AgentType.PUBLIC, description="Visibility scope")
    role: AgentRole = Field(
        default=AgentRole.AGENT, description="Role (agent/subagent)"
    )
    runtime_provider_id: str | None = Field(
        default=None, description="Runtime Provider logical ID"
    )
    shell_enabled: bool = Field(default=True, description="Shell enabled state")
    memory_enabled: bool = Field(default=True, description="Memory enabled state")
    max_turns: int | None = Field(
        default=None, gt=0, description="Maximum agent turn count"
    )
    toolkit_inherit_mode: SubagentToolkitInheritMode = Field(
        default=SubagentToolkitInheritMode.ALL,
        description="Toolkit inherit mode; default all, meaningful for role=subagent",
    )


class AgentUpdateRequest(TypedDict, total=False):
    """Agent update request, for partial updates."""

    name: Annotated[str, Field(description="Agent name")]
    description: Annotated[str | None, Field(description="Agent description")]
    model_selection: Annotated[
        AgentModelSelectionInput | None,
        Field(description="Main model selection. Copies workspace default when None"),
    ]
    lightweight_model_selection: Annotated[
        AgentModelSelectionInput | None,
        Field(description="Lightweight model selection. Copies default/main when None"),
    ]
    model_parameters: Annotated[
        ModelParameters | None, Field(description="Model parameters")
    ]
    system_prompt: Annotated[str | None, Field(description="System prompt")]
    enabled: Annotated[bool, Field(description="Enabled state")]
    type: Annotated[AgentType, Field(description="Visibility scope")]
    role: Annotated[AgentRole, Field(description="Role (agent/subagent)")]
    runtime_provider_id: Annotated[
        str | None, Field(description="Runtime Provider logical ID")
    ]
    shell_enabled: Annotated[bool, Field(description="Shell enabled state")]
    memory_enabled: Annotated[bool, Field(description="Memory enabled state")]
    max_turns: Annotated[
        int | None, Field(gt=0, description="Maximum agent turn count")
    ]
    toolkit_inherit_mode: Annotated[
        SubagentToolkitInheritMode,
        Field(description="Toolkit inherit mode"),
    ]


class AgentAdminResponse(BaseModel):
    """AgentAdmin response."""

    id: str
    agent_id: str
    workspace_user_id: str
    created_at: datetime.datetime

    @classmethod
    def convert_from(cls, data: AgentAdminOutput) -> Self:
        """Convert service model to a response object."""
        return cls(
            id=data.id,
            agent_id=data.agent_id,
            workspace_user_id=data.workspace_user_id,
            created_at=data.created_at,
        )


class AgentAdminListResponse(BaseModel):
    """AgentAdmin list response."""

    items: list[AgentAdminResponse]


class AgentAdminAddRequest(BaseModel):
    """AgentAdmin add request."""

    workspace_user_id: str = Field(description="Workspace member ID to add")


class AgentSubagentResponse(BaseModel):
    """AgentSubagent link response."""

    id: str
    agent_id: str
    subagent_id: str
    description: str
    enabled: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @classmethod
    def convert_from(cls, data: AgentSubagentOutput) -> Self:
        """Convert service model to a response object."""
        return cls(
            id=data.id,
            agent_id=data.agent_id,
            subagent_id=data.subagent_id,
            description=data.description,
            enabled=data.enabled,
            created_at=data.created_at,
            updated_at=data.updated_at,
        )


class AgentSubagentListResponse(BaseModel):
    """AgentSubagent list response."""

    items: list[AgentSubagentResponse]


class AgentSubagentCreateRequest(BaseModel):
    """AgentSubagent creation request."""

    subagent_id: str = Field(description="Subagent ID to link")
    description: str = Field(description="Description exposed to the LLM")
    enabled: bool = Field(default=True, description="Enabled state")


class AgentSubagentUpdateRequest(AgentSubagentUpdateInput):
    """AgentSubagent update request, for partial updates."""

    pass


class MemoryResponse(BaseModel):
    """Memory response."""

    id: str
    agent_id: str
    user_id: str | None
    scope: MemoryScope
    type: str
    name: str
    description: str
    content: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @classmethod
    def convert_from(cls, data: MemoryOutput) -> Self:
        """Convert service model to a response object."""
        return cls(
            id=data.id,
            agent_id=data.agent_id,
            user_id=data.user_id,
            scope=data.scope,
            type=data.type,
            name=data.name,
            description=data.description,
            content=data.content,
            created_at=data.created_at,
            updated_at=data.updated_at,
        )


class MemoryListResponse(BaseModel):
    """Memory list response."""

    items: list[MemoryResponse]


class MemoryCreateRequest(BaseModel):
    """Memory creation request."""

    scope: MemoryScope = Field(description="Scope")
    type: str = Field(min_length=1, max_length=50, description="Type")
    name: str = Field(min_length=1, max_length=255, description="Memory identifier")
    description: str = Field(min_length=1, description="One-line summary")
    content: str = Field(min_length=1, description="Memory body")


class MemoryUpdateRequest(TypedDict, total=False):
    """Memory update request, for partial updates."""

    type: Annotated[str, Field(min_length=1, max_length=50, description="Type")]
    name: Annotated[
        str, Field(min_length=1, max_length=255, description="Memory identifier")
    ]
    description: Annotated[str, Field(min_length=1, description="One-line summary")]
    content: Annotated[str, Field(min_length=1, description="Memory body")]


class AvatarUploadRequest(BaseModel):
    """Avatar upload ticket issue request."""

    content_type: str = Field(
        description="MIME of the file to upload. JPEG/PNG/WebP allowed"
    )
    content_length: int = Field(
        gt=0, description="Byte size of the file to upload, up to 5MB"
    )


class AvatarUploadTicketResponse(BaseModel):
    """Presigned PUT ticket response."""

    upload_key: str = Field(description="Upload key to pass during finalize")
    upload_url: str = Field(description="Presigned URL for the client to PUT to")
    expires_at: datetime.datetime = Field(
        description="URL expiration time, ISO 8601 and tz-aware"
    )

    @classmethod
    def convert_from(cls, data: AvatarUploadTicketOutput) -> Self:
        """Convert service output to a response."""
        return cls(
            upload_key=data.upload_key,
            upload_url=data.upload_url,
            expires_at=data.expires_at,
        )


class AvatarFinalizeRequest(BaseModel):
    """Finalize request after upload completion."""

    upload_key: str = Field(
        description="Upload key from issue-ticket, subject to scope revalidation"
    )
    filename: str = Field(description="Original filename, kept in response metadata")
