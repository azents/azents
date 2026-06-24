"""Generalized file upload framework.

Extracts the presigned PUT → finalize → validate → postprocess → publish pipeline
into common `UploadService`. Category-specific logic (MIME, max size, postprocess
resize, etc.) is contained in `UploadHandler` Protocol implementations.

First handler is `handlers.avatar.AvatarUploadHandler` (Agent profile image).
Future chat attachments / session files / workspace icons only need new handlers.

Key structure:

- `uploads/{category}/{owner_id}/{uuid}-{hex}` — Temporary upload awaiting validation
  (presigned PUT target), 1-day Lifecycle GC
- `public/{category}/{owner_id}/...` — Public output published by handler
- `internal/{category}/{owner_id}/...` — Private result (future)

Security principles:

- Re-validate `uploads/{category}/{owner_id}/` prefix on finalize
  (prevent other-owner injection)
- Server re-validates actual bytes at finalize time
  (do not trust `Content-Length` header)
- Presigned URL TTL 10 minutes (minimized)
- Try deleting uploads/ file even on validation failure
  + Lifecycle 1-day provides backup cleanup
"""

import dataclasses
import datetime
import logging
import secrets
import uuid
from typing import ClassVar, Protocol

from azcommon.infra.s3.service import S3Service

from azents.services.uploads.schema import StoredImage

logger = logging.getLogger(__name__)

UPLOAD_URL_EXPIRES: datetime.timedelta = datetime.timedelta(minutes=10)


class UploadValidationError(Exception):
    """Upload input violates handler constraints (MIME, size, square, etc.)."""


@dataclasses.dataclass(frozen=True)
class UploadTicket:
    """Presigned PUT URL issuance response."""

    upload_key: str
    upload_url: str
    expires_at: datetime.datetime


class UploadHandler(Protocol):
    """Contract for category-specific upload logic.

    Handler is stateless (only ClassVar constants); S3 client / bucket are
    injected by `UploadService` at call time. Test fixtures become simpler, and
    handler instances only need to be assembled once at app startup.
    """

    category: ClassVar[str]
    allowed_mime_types: ClassVar[frozenset[str]]
    max_bytes: ClassVar[int]

    async def validate(self, body: bytes) -> None:
        """Strict validation of uploaded bytes. `UploadValidationError` on failure."""
        ...

    async def process_and_publish(
        self,
        body: bytes,
        owner_id: str,
        filename: str,
        s3: S3Service,
        bucket: str,
    ) -> StoredImage:
        """Publish final output from validated bytes and return `StoredImage`."""
        ...


@dataclasses.dataclass
class UploadService:
    """Presigned upload ticket issuance + finalize pipeline."""

    s3: S3Service
    bucket: str
    handlers: dict[str, UploadHandler]

    def _handler(self, category: str) -> UploadHandler:
        try:
            return self.handlers[category]
        except KeyError as err:
            raise UploadValidationError(f"unknown upload category: {category}") from err

    async def issue_upload_ticket(
        self,
        category: str,
        owner_id: str,
        content_type: str,
        content_length: int,
    ) -> UploadTicket:
        """Issue Presigned PUT URL. First-pass filter with client-advertised values."""
        handler = self._handler(category)
        if content_type not in handler.allowed_mime_types:
            logger.warning(
                "Upload ticket rejected: unsupported mime",
                extra={
                    "category": category,
                    "owner_id": owner_id,
                    "content_type": content_type,
                },
            )
            raise UploadValidationError(f"unsupported mime: {content_type}")
        if content_length <= 0 or content_length > handler.max_bytes:
            logger.warning(
                "Upload ticket rejected: content_length out of range",
                extra={
                    "category": category,
                    "owner_id": owner_id,
                    "content_length": content_length,
                    "max_bytes": handler.max_bytes,
                },
            )
            raise UploadValidationError("content_length out of range")

        upload_key = (
            f"uploads/{category}/{owner_id}/{uuid.uuid4()}-{secrets.token_hex(8)}"
        )
        upload_url = await self.s3.get_upload_url(
            bucket=self.bucket,
            key=upload_key,
            content_type=content_type,
            expires_in=UPLOAD_URL_EXPIRES,
        )
        logger.info(
            "Upload ticket issued",
            extra={
                "category": category,
                "owner_id": owner_id,
                "upload_key": upload_key,
                "content_type": content_type,
                "content_length": content_length,
            },
        )
        return UploadTicket(
            upload_key=upload_key,
            upload_url=upload_url,
            expires_at=datetime.datetime.now(datetime.timezone.utc)
            + UPLOAD_URL_EXPIRES,
        )

    async def finalize(
        self,
        category: str,
        owner_id: str,
        upload_key: str,
        filename: str,
    ) -> StoredImage:
        """Inspect uploaded file from S3 → validate → publish → delete uploads/.

        Reject when `upload_key` prefix does not match `uploads/{category}/{owner_id}/`
        — prevents finalize injection from another owner.
        """
        expected_prefix = f"uploads/{category}/{owner_id}/"
        if not upload_key.startswith(expected_prefix):
            logger.warning(
                "Finalize rejected: upload_key scope mismatch",
                extra={
                    "category": category,
                    "owner_id": owner_id,
                    "upload_key": upload_key,
                },
            )
            raise UploadValidationError("invalid upload_key (scope mismatch)")
        handler = self._handler(category)

        body = await self.s3.download_bytes(bucket=self.bucket, key=upload_key)
        if body is None:
            logger.warning(
                "Finalize rejected: upload not found or expired",
                extra={
                    "category": category,
                    "owner_id": owner_id,
                    "upload_key": upload_key,
                },
            )
            raise UploadValidationError("upload not found or expired")

        logger.info(
            "Finalize started",
            extra={
                "category": category,
                "owner_id": owner_id,
                "upload_key": upload_key,
                "body_bytes": len(body),
            },
        )
        try:
            try:
                await handler.validate(body)
            except UploadValidationError:
                logger.warning(
                    "Finalize validation failed",
                    extra={
                        "category": category,
                        "owner_id": owner_id,
                        "upload_key": upload_key,
                    },
                )
                raise
            result = await handler.process_and_publish(
                body=body,
                owner_id=owner_id,
                filename=filename,
                s3=self.s3,
                bucket=self.bucket,
            )
            logger.info(
                "Finalize published",
                extra={
                    "category": category,
                    "owner_id": owner_id,
                    "upload_key": upload_key,
                    "default_key": result.default.key,
                },
            )
            return result
        finally:
            # Clean uploads/ fragment regardless of success/failure.
            # Lifecycle backs up on failure.
            try:
                await self.s3.delete(bucket=self.bucket, key=upload_key)
            except Exception:
                logger.exception(
                    "Failed to cleanup uploads/ object (Lifecycle will retry)",
                    extra={
                        "category": category,
                        "owner_id": owner_id,
                        "upload_key": upload_key,
                    },
                )
