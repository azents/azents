"""Artifact repository data models."""

import datetime

from azcommon.types import JSONValue
from pydantic import BaseModel, Field

from azents.core.enums import ArtifactStatus


class Artifact(BaseModel):
    """Artifact domain model."""

    id: str = Field(description="Artifact ID")
    workspace_id: str = Field(description="Workspace ID")
    session_id: str = Field(description="AgentSession ID")
    agent_id: str = Field(description="Agent ID")
    created_run_id: str = Field(description="Created run ID")
    created_run_index: int = Field(description="Created run index")
    expires_after_run_index: int = Field(description="Expiration reference run index")
    name: str = Field(description="Display filename")
    media_type: str = Field(description="MIME type")
    size_bytes: int = Field(description="File size")
    storage_key: str = Field(description="Object storage key")
    status: ArtifactStatus = Field(description="Artifact status")
    sha256: str | None = Field(default=None, description="SHA-256 digest")
    source_tool_name: str | None = Field(default=None, description="Created tool name")
    source_call_id: str | None = Field(default=None, description="Created call ID")
    source_part_index: int | None = Field(
        default=None, description="Created output part index"
    )
    description: str | None = Field(default=None, description="Description")
    metadata: dict[str, JSONValue] = Field(
        default_factory=dict, description="Additional metadata"
    )
    created_at: datetime.datetime = Field(description="Created time")
    expired_at: datetime.datetime | None = Field(
        default=None, description="Expiration time"
    )
    blob_deleted_at: datetime.datetime | None = Field(
        description="Blob deletion success time",
    )

    @property
    def uri(self) -> str:
        """Return Artifact file-location URI."""
        return f"artifact://{self.storage_key}"


class ArtifactCreate(BaseModel):
    """Artifact create schema."""

    workspace_id: str = Field(description="Workspace ID")
    session_id: str = Field(description="AgentSession ID")
    agent_id: str = Field(description="Agent ID")
    created_run_id: str = Field(description="Created run ID")
    created_run_index: int = Field(description="Created run index")
    expires_after_run_index: int = Field(description="Expiration reference run index")
    name: str = Field(description="Display filename")
    media_type: str = Field(description="MIME type")
    size_bytes: int = Field(description="File size")
    sha256: str = Field(description="SHA-256 digest")
    source_tool_name: str | None = Field(default=None, description="Created tool name")
    source_call_id: str | None = Field(default=None, description="Created call ID")
    source_part_index: int | None = Field(
        default=None, description="Created output part index"
    )
    description: str | None = Field(default=None, description="Description")
    metadata: dict[str, JSONValue] = Field(
        default_factory=dict, description="Additional metadata"
    )
