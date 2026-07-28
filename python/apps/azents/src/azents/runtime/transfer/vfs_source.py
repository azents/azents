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
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorOpaqueObjectHandle,
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
    async def create_empty_immutable(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3VerifiedObject: ...
    async def delete(self, bucket: str, key: str) -> None: ...


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
        destination = S3ObjectIdentity(
            bucket=self.bucket,
            key="/".join(
                (
                    self.transfer_object_prefix.strip("/"),
                    preparation.admitted_object_handle.value,
                )
            ),
        )
        if self.entry.size_bytes == 0:
            return await self._prepare_empty(
                preparation=preparation,
                destination=destination,
            )
        upload = await self.s3_service.create_multipart_upload(
            destination=destination,
            transfer_metadata=S3TransferObjectMetadata(
                sha256=self.entry.content_hash, content_type=self.entry.media_type
            ),
        )
        digest = hashlib.sha256()
        decoded_size = 0
        parts: list[S3CompletedPart] = []
        completed = False
        try:
            await preparation.register_cleanup(
                preparation_object_handle=preparation.admitted_object_handle,
                multipart_cleanup_handle=CoordinatorOpaqueObjectHandle(
                    upload.upload_id
                ),
            )
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
            completed = True
            await preparation.promote_cleanup(
                preparation_object_handle=preparation.admitted_object_handle,
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
            await self._cleanup_preparation(
                preparation=preparation,
                upload=upload,
                destination=destination,
                completed=completed,
            )
            raise
        except Exception:
            await self._cleanup_preparation(
                preparation=preparation,
                upload=upload,
                destination=destination,
                completed=completed,
            )
            raise

    async def _prepare_empty(
        self,
        *,
        preparation: ServerToRuntimePreparation,
        destination: S3ObjectIdentity,
    ) -> PreparedServerToRuntimeObject:
        """Create and verify the immutable empty object without multipart work."""
        empty_sha256 = hashlib.sha256(b"").hexdigest()
        if self.entry.body_base64 or self.entry.content_hash != empty_sha256:
            raise ValueError("Zero-byte VFS file does not match the manifest")
        await preparation.promote_cleanup(
            preparation_object_handle=preparation.admitted_object_handle,
        )
        verified = await self.s3_service.create_empty_immutable(
            destination=destination,
            transfer_metadata=S3TransferObjectMetadata(
                sha256=empty_sha256,
                content_type=self.entry.media_type,
            ),
        )
        if verified.metadata.content_length != 0 or verified.sha256 != empty_sha256:
            raise ValueError("VFS empty staging verification failed")
        return PreparedServerToRuntimeObject(
            preparation.admitted_object_handle,
            0,
            empty_sha256,
        )

    async def _cleanup_preparation(
        self,
        *,
        preparation: ServerToRuntimePreparation,
        upload: S3MultipartUpload,
        destination: S3ObjectIdentity,
        completed: bool,
    ) -> None:
        """Clean exact local preparation work and clear its durable evidence."""
        if completed:
            await self.s3_service.delete(destination.bucket, destination.key)
        else:
            await self.s3_service.abort_multipart_upload(upload=upload)
        await preparation.clear_cleanup()

    async def revalidate(self) -> bool:
        return await self.revalidate_authority()
