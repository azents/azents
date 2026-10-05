"""Common schema for uploaded images.

Two internal/external layers:

- Internal (`StoredImage*`): For JSONB storage. Includes S3 key + metadata.
  Repository converts dict ↔ Pydantic with
  `TypeAdapter.validate_python` / `model_dump(mode="json")`.
- External (`UploadedImage`, `ImageFile`, `ImageThumbnails`): service output /
  API response common. Includes only resolved URL and hides S3 key.
  Future handlers such as agent avatar /
  workspace icon / chat attachments all reuse this schema.

Azents upload schema follows this pattern —
Declarative thumbnail tier + always-available `default` fallback.
"""

import datetime

from pydantic import BaseModel, Field


class StoredImageFile(BaseModel):
    """Single image entry for JSONB storage — includes S3 key."""

    key: str = Field(description="S3 object key")
    content_type: str = Field(description="MIME type")
    size_bytes: int = Field(description="Byte size")
    width: int | None = Field(default=None, description="Width pixels (when image)")
    height: int | None = Field(default=None, description="Height pixels (when image)")


class StoredImageThumbnails(BaseModel):
    """3-tier declarative thumbnails. Each tier is Optional for async resize.

    avatar is processed sync, so all tiers are populated, but future async handler
    (#2876 Temporal) may have some tiers as None until resize completes.
    """

    small: StoredImageFile | None = None
    medium: StoredImageFile | None = None
    large: StoredImageFile | None = None


class StoredImage(BaseModel):
    """Uploaded image schema stored in JSONB.

    Repository parses row dict as this type with `TypeAdapter[StoredImage]`,
    then records to DB with `model_dump(mode="json")`. Domain models
    (`Agent.avatar`, etc.)
    also contain this type directly.

    - `default` is always non-null — handler fills it at publish time so UI
      can fall back even when tier is None.
    - Each `thumbnails` tier is Optional (for async resize).
    - `original` is filled only by handlers preserving original. avatar is
      always None per P5 decision (discard original).
    """

    filename: str = Field(description="Original upload filename")
    default: StoredImageFile = Field(description="Always non-null fallback image")
    thumbnails: StoredImageThumbnails = Field(default_factory=StoredImageThumbnails)
    original: StoredImageFile | None = Field(default=None)
    uploaded_at: datetime.datetime = Field(
        description="Upload completion time (tz-aware)"
    )


class ImageFile(BaseModel):
    """Single image for API response — resolved URL + resolution."""

    url: str = Field(description="CDN URL or 1-hour presigned GET URL")
    width: int = Field(description="Width pixels")
    height: int = Field(description="Height pixels")


class ImageThumbnails(BaseModel):
    """3-tier thumbnails for API response."""

    small: ImageFile | None = None
    medium: ImageFile | None = None
    large: ImageFile | None = None


class UploadedImage(BaseModel):
    """Common response schema for uploaded image + thumbnails.

    agent avatar, workspace icon, chat attachment preview, etc. all reuse this type.
    `default` is always non-null, so UI can safely render image with
    `default.url` even when all `thumbnails` are None.
    """

    filename: str = Field(description="Original upload filename")
    default: ImageFile = Field(description="Always non-null fallback image")
    thumbnails: ImageThumbnails = Field(description="Declarative 3-tier thumbnails")
    uploaded_at: datetime.datetime = Field(
        description="Upload completion time (ISO 8601, tz-aware)"
    )
