"""ExchangeFile repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import ExchangeFileOrigin, ExchangeFileStatus


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
    created_by_user_id: str = Field(description="Creator user ID")
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
    created_by_user_id: str = Field(description="Creator user ID")
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
