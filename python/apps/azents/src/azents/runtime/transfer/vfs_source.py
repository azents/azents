"""Strict incremental VFS Base64 staging for Server-to-Runtime transfers."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from azcommon.infra.s3.service import (
    S3CompletedPart,
    S3MultipartUpload,
    S3ObjectIdentity,
    S3TransferObjectMetadata,
    S3VerifiedObject,
)

from azents.core.vfs import VFS_FILE_MAX_BYTES, VfsFileEntry
from azents.runtime.transfer.server_to_runtime import (
    PreparedServerToRuntimeObject,
    ServerToRuntimePreparation,
    ServerToRuntimeSourceMetadata,
)


class VfsStagingStore(Protocol):
    """Bounded trusted multipart surface required for VFS staging."""

    async def create_multipart_upload(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3MultipartUpload: ...
    async def upload_part(
        self, *, upload: S3MultipartUpload, part_number: int, body: bytes
    ) -> S3CompletedPart: ...
    async def complete_multipart_upload(
        self,
        *,
        upload: S3MultipartUpload,
        completed_parts: tuple[S3CompletedPart, ...],
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject: ...
    async def abort_multipart_upload(self, *, upload: S3MultipartUpload) -> None: ...


@dataclass(frozen=True)
class VfsServerToRuntimeSource:
    """An already-authorized canonical VFS entry without eager body decoding."""

    entry: VfsFileEntry
    revalidate_authority: Callable[[], Awaitable[bool]]
    s3_service: VfsStagingStore
    bucket: str
    transfer_object_prefix: str
    decode_slice_chars: int = 16 * 1024

    def __post_init__(self) -> None:
        if self.entry.size_bytes > VFS_FILE_MAX_BYTES:
            raise ValueError("VFS source exceeds the product file limit")
        if self.decode_slice_chars <= 0 or self.decode_slice_chars % 4:
            raise ValueError("VFS decode slices must be positive Base64 quartets")

    @property
    def metadata(self) -> ServerToRuntimeSourceMetadata:
        return ServerToRuntimeSourceMetadata(
            canonical_uri=self.entry.canonical_uri,
            source_kind="azents",
            display_name=self.entry.canonical_uri.rsplit("/", 1)[-1],
            media_type=self.entry.media_type,
            size=self.entry.size_bytes,
            sha256=self.entry.content_hash,
            expires_at=None,
        )

    async def prepare(
        self, *, preparation: ServerToRuntimePreparation
    ) -> PreparedServerToRuntimeObject:
        """Decode, hash, stage, and verify the exact VFS entry incrementally."""
        if self.entry.size_bytes == 0:
            raise ValueError("Zero-byte VFS staging is not supported by multipart")
        upload = await self.s3_service.create_multipart_upload(
            destination=S3ObjectIdentity(
                bucket=self.bucket,
                key="/".join(
                    (
                        self.transfer_object_prefix.strip("/"),
                        preparation.admitted_object_handle.value,
                    )
                ),
            ),
            transfer_metadata=S3TransferObjectMetadata(
                sha256=self.entry.content_hash, content_type=self.entry.media_type
            ),
        )
        digest = hashlib.sha256()
        decoded_size = 0
        parts: list[S3CompletedPart] = []
        try:
            for index, offset in enumerate(
                range(0, len(self.entry.body_base64), self.decode_slice_chars), start=1
            ):
                encoded = self.entry.body_base64[
                    offset : offset + self.decode_slice_chars
                ]
                if len(encoded) % 4:
                    raise ValueError("VFS file body is not valid Base64")
                try:
                    chunk = base64.b64decode(encoded, validate=True)
                except binascii.Error as exc:
                    raise ValueError("VFS file body is not valid Base64") from exc
                decoded_size += len(chunk)
                if decoded_size > self.entry.size_bytes:
                    raise ValueError("VFS file size does not match the manifest")
                digest.update(chunk)
                if chunk:
                    parts.append(
                        await self.s3_service.upload_part(
                            upload=upload, part_number=index, body=chunk
                        )
                    )
            actual_sha256 = digest.hexdigest()
            if decoded_size != self.entry.size_bytes:
                raise ValueError("VFS file size does not match the manifest")
            if actual_sha256 != self.entry.content_hash:
                raise ValueError("VFS file content hash does not match the manifest")
            verified = await self.s3_service.complete_multipart_upload(
                upload=upload,
                completed_parts=tuple(parts),
                expected_size=decoded_size,
                expected_sha256=actual_sha256,
            )
            if (
                verified.metadata.content_length != decoded_size
                or verified.sha256 != actual_sha256
            ):
                raise ValueError("VFS staging verification failed")
            return PreparedServerToRuntimeObject(
                preparation.admitted_object_handle, decoded_size, actual_sha256
            )
        except asyncio.CancelledError:
            await self.s3_service.abort_multipart_upload(upload=upload)
            raise
        except Exception:
            await self.s3_service.abort_multipart_upload(upload=upload)
            raise

    async def revalidate(self) -> bool:
        return await self.revalidate_authority()
