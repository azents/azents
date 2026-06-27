"""ModelFile repository data models."""

import datetime

from azcommon.types import JSONValue
from pydantic import BaseModel, Field

from azents.core.enums import ModelFileStatus


class ModelFile(BaseModel):
    """ModelFile domain model."""

    id: str = Field(description="ModelFile ID")
    workspace_id: str = Field(description="Workspace ID")
    session_id: str = Field(description="AgentSession ID")
    agent_id: str = Field(description="Agent ID")
    name: str | None = Field(default=None, description="Display filename")
    media_type: str = Field(description="MIME type")
    kind: str = Field(description="Broad file kind")
    size_bytes: int = Field(description="Normalized blob size")
    created_run_index: int = Field(ge=1, description="Created run index")
    storage_key: str = Field(description="Object storage key")
    status: ModelFileStatus = Field(description="ModelFile status")
    normalized_format: str = Field(description="Normalized blob format")
    sha256: str = Field(description="normalized blob SHA-256 digest")
    metadata: dict[str, JSONValue] = Field(
        default_factory=dict, description="Additional metadata"
    )
    created_at: datetime.datetime = Field(description="Created time")
    deleted_at: datetime.datetime | None = Field(
        default=None, description="Deletion time"
    )
    blob_deleted_at: datetime.datetime | None = Field(
        default=None, description="Blob deletion time"
    )


class ModelFileCreate(BaseModel):
    """ModelFile create schema."""

    workspace_id: str = Field(description="Workspace ID")
    session_id: str = Field(description="AgentSession ID")
    agent_id: str = Field(description="Agent ID")
    name: str | None = Field(default=None, description="Display filename")
    media_type: str = Field(description="MIME type")
    kind: str = Field(description="Broad file kind")
    size_bytes: int = Field(description="Normalized blob size")
    created_run_index: int = Field(ge=1, description="Created run index")
    normalized_format: str = Field(description="Normalized blob format")
    sha256: str = Field(description="normalized blob SHA-256 digest")
    metadata: dict[str, JSONValue] = Field(
        default_factory=dict, description="Additional metadata"
    )
