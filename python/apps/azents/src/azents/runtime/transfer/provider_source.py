"""Deferred provider-stream staging for Server-to-Runtime transfers."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from azcommon.infra.s3.service import (
    S3CompletedPart,
    S3MultipartUpload,
    S3ObjectIdentity,
    S3ObjectMetadata,
    S3TransferObjectMetadata,
    S3VerifiedObject,
)
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorOpaqueObjectHandle,
)

from azents.runtime.transfer.server_to_runtime import (
    PreparedServerToRuntimeObject,
    ServerToRuntimePreparation,
    ServerToRuntimeSourceMetadata,
)


class ProviderByteStreamOpener(Protocol):
    """Open one bounded provider response after transfer admission."""

    def __call__(
        self,
        *,
        maximum_chunk_size: int,
    ) -> AbstractAsyncContextManager[AsyncIterator[bytes]]:
        """Open an owned response stream that closes on every caller exit."""
        ...


class ProviderStagingStore(Protocol):
    """Trusted S3 operations for digest-unknown provider source staging."""

    async def create_preparation_multipart_upload(
        self,
        *,
        destination: S3ObjectIdentity,
        content_type: str | None,
    ) -> S3MultipartUpload: ...

    async def upload_part(
        self,
        *,
        upload: S3MultipartUpload,
        part_number: int,
        body: bytes,
    ) -> S3CompletedPart: ...

    async def complete_preparation_multipart_upload(
        self,
        *,
        upload: S3MultipartUpload,
        completed_parts: tuple[S3CompletedPart, ...],
        expected_size: int,
    ) -> S3ObjectMetadata: ...

    async def abort_multipart_upload(self, *, upload: S3MultipartUpload) -> None: ...

    async def copy_immutable(
        self,
        *,
        source: S3ObjectIdentity,
        destination: S3ObjectIdentity,
        expected_size: int,
        transfer_metadata: S3TransferObjectMetadata,
        multipart_copy_threshold: int,
        multipart_part_size: int,
    ) -> S3VerifiedObject: ...

    async def delete(self, bucket: str, key: str) -> None: ...


@dataclass(frozen=True)
class DeferredProviderServerToRuntimeSource:
    """One declared-size provider file whose response opens only after admission."""

    metadata: ServerToRuntimeSourceMetadata
    open_stream: ProviderByteStreamOpener
    revalidate_authority: Callable[[], Awaitable[bool]]
    s3_service: ProviderStagingStore
    bucket: str
    transfer_object_prefix: str
    preparation_id_source: Callable[[], str]
    maximum_size: int
    stream_chunk_size: int
    multipart_part_size: int
    multipart_copy_threshold: int
    multipart_copy_part_size: int

    def __post_init__(self) -> None:
        """Validate bounded provider streaming configuration."""
        if not self.bucket:
            raise ValueError("Provider staging bucket is required")
        if not self.transfer_object_prefix.strip("/"):
            raise ValueError("Provider transfer object prefix is required")
        if self.maximum_size < 0:
            raise ValueError("Provider maximum size must not be negative")
        if self.metadata.size > self.maximum_size:
            raise ValueError("Provider source exceeds its configured maximum size")
        if (
            min(
                self.stream_chunk_size,
                self.multipart_part_size,
                self.multipart_copy_threshold,
                self.multipart_copy_part_size,
            )
            <= 0
        ):
            raise ValueError("Provider staging byte bounds must be positive")
        if self.stream_chunk_size > self.multipart_part_size:
            raise ValueError(
                "Provider stream chunks must not exceed multipart part size"
            )

    async def prepare(
        self,
        *,
        preparation: ServerToRuntimePreparation,
    ) -> PreparedServerToRuntimeObject:
        """Stage, verify, promote, and remove one deferred provider body."""
        if self.metadata.size == 0:
            raise ValueError("Zero-byte provider staging is not supported by multipart")
        preparation_handle = self._preparation_handle(preparation)
        preparation_identity = self._object_identity(preparation_handle)
        upload = await self.s3_service.create_preparation_multipart_upload(
            destination=preparation_identity,
            content_type=self.metadata.media_type,
        )
        try:
            await preparation.register_cleanup(
                preparation_object_handle=preparation_handle,
                multipart_cleanup_handle=CoordinatorOpaqueObjectHandle(
                    upload.upload_id
                ),
            )
        except asyncio.CancelledError:
            await self.s3_service.abort_multipart_upload(upload=upload)
            raise
        except Exception:
            await self.s3_service.abort_multipart_upload(upload=upload)
            raise

        completed = False
        try:
            actual_size, actual_sha256, parts = await self._stream_parts(upload)
            if actual_size != self.metadata.size:
                raise ValueError("Provider stream size does not match the manifest")
            if (
                self.metadata.sha256 is not None
                and actual_sha256 != self.metadata.sha256
            ):
                raise ValueError("Provider stream hash does not match the manifest")
            completed_metadata = (
                await self.s3_service.complete_preparation_multipart_upload(
                    upload=upload,
                    completed_parts=parts,
                    expected_size=actual_size,
                )
            )
            if completed_metadata.content_length != actual_size:
                raise ValueError("Provider preparation object size verification failed")
            completed = True
            await preparation.promote_cleanup(
                preparation_object_handle=preparation_handle,
            )
            await preparation.promote_cleanup(
                preparation_object_handle=preparation.admitted_object_handle,
            )
            verified = await self.s3_service.copy_immutable(
                source=preparation_identity,
                destination=self._object_identity(preparation.admitted_object_handle),
                expected_size=actual_size,
                transfer_metadata=S3TransferObjectMetadata(
                    sha256=actual_sha256,
                    content_type=self.metadata.media_type,
                ),
                multipart_copy_threshold=self.multipart_copy_threshold,
                multipart_part_size=self.multipart_copy_part_size,
            )
            if (
                verified.metadata.content_length != actual_size
                or verified.sha256 != actual_sha256
            ):
                raise ValueError("Provider transfer copy verification failed")
            await self.s3_service.delete(
                preparation_identity.bucket,
                preparation_identity.key,
            )
            return PreparedServerToRuntimeObject(
                object_handle=preparation.admitted_object_handle,
                size=actual_size,
                sha256=actual_sha256,
            )
        except asyncio.CancelledError:
            await self._cleanup_preparation(
                preparation=preparation,
                upload=upload,
                preparation_identity=preparation_identity,
                completed=completed,
            )
            raise
        except Exception:
            await self._cleanup_preparation(
                preparation=preparation,
                upload=upload,
                preparation_identity=preparation_identity,
                completed=completed,
            )
            raise

    async def _stream_parts(
        self,
        upload: S3MultipartUpload,
    ) -> tuple[int, str, tuple[S3CompletedPart, ...]]:
        """Read bounded chunks into bounded multipart parts and a digest."""
        digest = hashlib.sha256()
        actual_size = 0
        part_number = 1
        pending = bytearray()
        parts: list[S3CompletedPart] = []
        async with self.open_stream(
            maximum_chunk_size=self.stream_chunk_size
        ) as chunks:
            async for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise ValueError("Provider stream yielded a non-bytes chunk")
                if len(chunk) > self.stream_chunk_size:
                    raise ValueError("Provider stream chunk exceeds its bound")
                actual_size += len(chunk)
                if actual_size > min(self.metadata.size, self.maximum_size):
                    raise ValueError("Provider stream exceeds its declared size")
                digest.update(chunk)
                pending.extend(chunk)
                while len(pending) >= self.multipart_part_size:
                    body = bytes(pending[: self.multipart_part_size])
                    del pending[: self.multipart_part_size]
                    parts.append(
                        await self.s3_service.upload_part(
                            upload=upload,
                            part_number=part_number,
                            body=body,
                        )
                    )
                    part_number += 1
        if pending:
            parts.append(
                await self.s3_service.upload_part(
                    upload=upload,
                    part_number=part_number,
                    body=bytes(pending),
                )
            )
        return actual_size, digest.hexdigest(), tuple(parts)

    async def _cleanup_preparation(
        self,
        *,
        preparation: ServerToRuntimePreparation,
        upload: S3MultipartUpload,
        preparation_identity: S3ObjectIdentity,
        completed: bool,
    ) -> None:
        """Clean exact owned preparation work and clear durable evidence."""
        if completed:
            await self.s3_service.delete(
                preparation_identity.bucket,
                preparation_identity.key,
            )
        else:
            await self.s3_service.abort_multipart_upload(upload=upload)
        await preparation.clear_cleanup()

    def _preparation_handle(
        self,
        preparation: ServerToRuntimePreparation,
    ) -> CoordinatorOpaqueObjectHandle:
        """Derive one opaque temporary-object handle from the admitted attempt."""
        suffix = self.preparation_id_source()
        if not suffix:
            raise ValueError("Provider preparation identifier is required")
        return CoordinatorOpaqueObjectHandle(
            f"{preparation.admitted_object_handle.value}-preparation-{suffix}"
        )

    def _object_identity(
        self,
        object_handle: CoordinatorOpaqueObjectHandle,
    ) -> S3ObjectIdentity:
        """Resolve one trusted opaque handle under the configured transfer prefix."""
        return S3ObjectIdentity(
            bucket=self.bucket,
            key="/".join(
                (
                    self.transfer_object_prefix.strip("/"),
                    object_handle.value,
                )
            ),
        )

    async def revalidate(self) -> bool:
        """Revalidate provider feature authority after snapshot preparation."""
        return await self.revalidate_authority()
