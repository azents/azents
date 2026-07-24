"""ExchangeFile repository data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field

from azents.core.enums import (
    ExchangeFileOrigin,
    ExchangeFileProvenanceKind,
    ExchangeFileStatus,
)


@dataclasses.dataclass(frozen=True)
class ExchangeFileClaimNotFound:
    """One referenced ExchangeFile or preview row was not found."""


@dataclasses.dataclass(frozen=True)
class ExchangeFileClaimWrongScope:
    """A referenced ExchangeFile belongs to another workspace or Agent."""


@dataclasses.dataclass(frozen=True)
class ExchangeFileClaimExpired:
    """A referenced ExchangeFile is no longer available for new input."""


@dataclasses.dataclass(frozen=True)
class ExchangeFileClaimUnavailable:
    """A referenced ExchangeFile has no available backing blob."""


@dataclasses.dataclass(frozen=True)
class ExchangeFileClaimOwnerConflict:
    """A referenced ExchangeFile belongs to another retention root."""


ExchangeFileClaimError = (
    ExchangeFileClaimNotFound
    | ExchangeFileClaimWrongScope
    | ExchangeFileClaimExpired
    | ExchangeFileClaimUnavailable
    | ExchangeFileClaimOwnerConflict
)


class ExchangeFile(BaseModel):
    """ExchangeFile domain model."""

    id: str = Field(description="ExchangeFile ID")
    workspace_id: str = Field(description="Workspace ID")
    agent_id: str = Field(description="Agent ID")
    origin_type: ExchangeFileOrigin = Field(description="File creation origin")
    status: ExchangeFileStatus = Field(description="File lifecycle status")
    object_key: str = Field(description="Object storage key")
    filename: str = Field(description="Display filename")
    media_type: str = Field(description="MIME type")
    size_bytes: int = Field(description="File size")
    sha256: str = Field(description="Source bytes SHA-256 digest")
    provenance_kind: ExchangeFileProvenanceKind = Field(
        description="Typed file source provenance"
    )
    source_user_id: str | None = Field(description="Human uploader User ID")
    source_agent_id: str | None = Field(description="Source Agent ID")
    source_run_id: str | None = Field(description="Source AgentRun ID")
    source_tool_name: str | None = Field(description="Source tool name")
    source_provider: str | None = Field(description="Source provider name")
    source_exchange_file_id: str | None = Field(
        description="Source ExchangeFile ID for derived previews"
    )
    retention_root_session_id: str | None = Field(
        description="Root AgentSession that owns retention cleanup",
    )
    retention_bound_at: datetime.datetime | None = Field(
        description="Time the file was bound to its retention root",
    )
    preview_thumbnail_file_id: str | None = Field(
        default=None,
        description="Image preview thumbnail ExchangeFile ID",
    )
    preview_thumbnail_uri: str | None = Field(
        default=None,
        description="Image preview thumbnail file-location URI",
    )
    preview_title: str | None = Field(default=None, description="Preview title")
    preview_summary: str | None = Field(default=None, description="Preview summary")
    preview_thumbnail_media_type: str | None = Field(
        default=None,
        description="Preview thumbnail MIME type",
    )
    preview_thumbnail_width: int | None = Field(
        default=None,
        description="Preview thumbnail width",
    )
    preview_thumbnail_height: int | None = Field(
        default=None,
        description="Preview thumbnail height",
    )
    preview_generated_at: datetime.datetime | None = Field(
        default=None,
        description="Preview created time",
    )
    expires_at: datetime.datetime = Field(description="Expiration time")
    expired_at: datetime.datetime | None = Field(
        default=None,
        description="Expiration processing time",
    )
    blob_deleted_at: datetime.datetime | None = Field(
        default=None, description="Blob deletion time"
    )
    created_at: datetime.datetime = Field(description="Created time")

    @property
    def uri(self) -> str:
        """Return Exchange file-location URI."""
        return f"exchange://{self.object_key}"


class ExchangeFileCreate(BaseModel):
    """ExchangeFile create schema."""

    id: str = Field(description="ExchangeFile ID")
    workspace_id: str = Field(description="Workspace ID")
    agent_id: str = Field(description="Agent ID")
    origin_type: ExchangeFileOrigin = Field(description="File creation origin")
    filename: str = Field(description="Display filename")
    media_type: str = Field(description="MIME type")
    size_bytes: int = Field(description="File size")
    sha256: str = Field(description="Source bytes SHA-256 digest")
    provenance_kind: ExchangeFileProvenanceKind = Field(
        description="Typed file source provenance"
    )
    source_user_id: str | None = Field(description="Human uploader User ID")
    source_agent_id: str | None = Field(description="Source Agent ID")
    source_run_id: str | None = Field(description="Source AgentRun ID")
    source_tool_name: str | None = Field(description="Source tool name")
    source_provider: str | None = Field(description="Source provider name")
    source_exchange_file_id: str | None = Field(
        description="Source ExchangeFile ID for derived previews"
    )
    retention_root_session_id: str | None = Field(
        description="Root AgentSession that owns retention cleanup",
    )
    retention_bound_at: datetime.datetime | None = Field(
        description="Time the file was bound to its retention root",
    )
    expires_at: datetime.datetime = Field(description="Expiration time")
    preview_title: str | None = Field(default=None, description="Preview title")
    preview_summary: str | None = Field(default=None, description="Preview summary")
    preview_thumbnail_media_type: str | None = Field(
        default=None,
        description="Preview thumbnail MIME type",
    )
    preview_thumbnail_width: int | None = Field(
        default=None,
        description="Preview thumbnail width",
    )
    preview_thumbnail_height: int | None = Field(
        default=None,
        description="Preview thumbnail height",
    )
    preview_generated_at: datetime.datetime | None = Field(
        default=None,
        description="Preview created time",
    )
