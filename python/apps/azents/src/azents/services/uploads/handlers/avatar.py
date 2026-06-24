"""Agent profile image upload handler.

First `UploadHandler` implementation. Avatar-specific constraints (MIME, max size,
forced square, Pillow resize small/medium/large WebP) are contained in this module.

Per P5 decision (discard original), `StoredImage.original` is always None.
Among small/medium/large, `large` (512px) shares same S3 object as `default` —
provides non-null fallback without duplicate upload.
"""

import datetime
import logging
import secrets
from io import BytesIO
from typing import ClassVar

from azcommon.infra.s3.service import S3Service
from PIL import Image

from azents.services.uploads import UploadValidationError
from azents.services.uploads.schema import (
    StoredImage,
    StoredImageFile,
    StoredImageThumbnails,
)

logger = logging.getLogger(__name__)


class AvatarUploadHandler:
    """Agent profile image handler.

    - MIME: JPEG / PNG / WebP
    - Maximum upload size: 5MB
    - Maximum dimensions: 4096 x 4096 (bomb prevention)
    - Allow only square images (cropped with react-easy-crop on web before upload)
    - Postprocess thumbnails: small (128) / medium (256) / large (512) WebP
    - `default` = large (shares same S3 key)
    """

    category: ClassVar[str] = "avatar"
    allowed_mime_types: ClassVar[frozenset[str]] = frozenset(
        {"image/jpeg", "image/png", "image/webp"}
    )
    max_bytes: ClassVar[int] = 5 * 1024 * 1024
    max_dimension: ClassVar[int] = 4096
    thumbnail_sizes: ClassVar[tuple[tuple[str, int], ...]] = (
        ("small", 128),
        ("medium", 256),
        ("large", 512),
    )
    output_mime: ClassVar[str] = "image/webp"

    async def validate(self, body: bytes) -> None:
        """Byte-level validation — decode / square / dimensions / size."""
        if len(body) > self.max_bytes:
            raise UploadValidationError(
                f"image too large (max {self.max_bytes // (1024 * 1024)}MB)"
            )

        try:
            img = Image.open(BytesIO(body))
            img.load()
        except Exception as err:
            raise UploadValidationError("invalid image bytes") from err

        if img.width != img.height:
            raise UploadValidationError("image must be square")
        if img.width > self.max_dimension or img.height > self.max_dimension:
            raise UploadValidationError(
                f"image too large (max {self.max_dimension}x{self.max_dimension})"
            )

    async def process_and_publish(
        self,
        body: bytes,
        owner_id: str,
        filename: str,
        s3: S3Service,
        bucket: str,
    ) -> StoredImage:
        """Create small/medium/large WebP thumbnails and upload them.

        New hex per upload — previous URL invalidates on reupload.
        `default` references same S3 object as `large` — fallback without duplication.
        """
        img = Image.open(BytesIO(body))
        img.load()
        # WebP saving requires RGB mode (alpha preservation is out of scope)
        img = img.convert("RGB")

        hex_id = secrets.token_hex(16)
        logger.info(
            "Avatar process_and_publish started",
            extra={
                "owner_id": owner_id,
                "hex_id": hex_id,
                "source_bytes": len(body),
            },
        )

        thumbnails_fields: dict[str, StoredImageFile] = {}
        large_file: StoredImageFile | None = None
        for name, size in self.thumbnail_sizes:
            resized = img.resize((size, size), Image.Resampling.LANCZOS)
            buf = BytesIO()
            resized.save(buf, format="WEBP", quality=85, method=6)
            body_bytes = buf.getvalue()
            key = f"public/avatar/{owner_id}/{name}/{hex_id}.webp"
            await s3.upload(
                bucket=bucket,
                key=key,
                body=body_bytes,
                content_type=self.output_mime,
            )
            entry = StoredImageFile(
                key=key,
                content_type=self.output_mime,
                size_bytes=len(body_bytes),
                width=size,
                height=size,
            )
            thumbnails_fields[name] = entry
            if name == "large":
                large_file = entry

        # large is always created, so share as default.
        # Changes are noticed immediately by KeyError.
        assert large_file is not None, "large thumbnail must be generated"

        logger.info(
            "Avatar process_and_publish completed",
            extra={
                "owner_id": owner_id,
                "hex_id": hex_id,
                "default_key": large_file.key,
                "thumbnail_count": len(thumbnails_fields),
            },
        )
        return StoredImage(
            filename=filename,
            default=large_file,
            thumbnails=StoredImageThumbnails(
                small=thumbnails_fields["small"],
                medium=thumbnails_fields["medium"],
                large=thumbnails_fields["large"],
            ),
            original=None,  # P5: discard original
            uploaded_at=datetime.datetime.now(datetime.timezone.utc),
        )

    async def delete_files(
        self,
        avatar: StoredImage,
        s3: S3Service,
        bucket: str,
    ) -> None:
        """Remove all S3 objects for published avatar. default and large share key,
        so deduplicate.
        """
        keys: set[str] = {avatar.default.key}
        if avatar.thumbnails.small is not None:
            keys.add(avatar.thumbnails.small.key)
        if avatar.thumbnails.medium is not None:
            keys.add(avatar.thumbnails.medium.key)
        if avatar.thumbnails.large is not None:
            keys.add(avatar.thumbnails.large.key)
        if avatar.original is not None:
            keys.add(avatar.original.key)
        logger.info(
            "Avatar delete_files started",
            extra={"key_count": len(keys), "default_key": avatar.default.key},
        )
        for key in keys:
            await s3.delete(bucket=bucket, key=key)
