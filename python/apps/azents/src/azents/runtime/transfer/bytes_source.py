"""Trusted in-memory byte staging for Server-to-Runtime transfers."""

from __future__ import annotations

import asyncio
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

from azents.runtime.transfer.server_to_runtime import (
    PreparedServerToRuntimeObject,
    ServerToRuntimePreparation,
    ServerToRuntimeSourceMetadata,
)


class BytesStagingStore(Protocol):
    """Trusted multipart surface required for byte-source staging."""

    async def create_multipart_upload(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3MultipartUpload: ...

    async def upload_part(
        self,
        *,
        upload: S3MultipartUpload,
        part_number: int,
        body: bytes,
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
class BytesServerToRuntimeSource:
    """One authority-bound in-memory byte source."""

    body: bytes
    canonical_uri: str
    source_kind: str
    display_name: str
    media_type: str
    revalidate_authority: Callable[[], Awaitable[bool]]
    s3_service: BytesStagingStore
    bucket: str
    transfer_object_prefix: str
    part_size: int

    def __post_init__(self) -> None:
        """Validate immutable byte-source configuration."""
        if self.part_size <= 0:
            raise ValueError("Byte-source staging part size must be positive")
        if not self.canonical_uri or not self.source_kind or not self.display_name:
            raise ValueError("Byte-source metadata is required")

    @property
    def metadata(self) -> ServerToRuntimeSourceMetadata:
        """Return complete immutable source metadata."""
        return ServerToRuntimeSourceMetadata(
            canonical_uri=self.canonical_uri,
            source_kind=self.source_kind,
            display_name=self.display_name,
            media_type=self.media_type,
            size=len(self.body),
            sha256=hashlib.sha256(self.body).hexdigest(),
            expires_at=None,
        )

    async def prepare(
        self,
        *,
        preparation: ServerToRuntimePreparation,
    ) -> PreparedServerToRuntimeObject:
        """Stage and verify the exact bytes in the admitted transfer object."""
        destination = S3ObjectIdentity(
            bucket=self.bucket,
            key="/".join(
                (
                    self.transfer_object_prefix.strip("/"),
                    preparation.admitted_object_handle.value,
                )
            ),
        )
        metadata = self.metadata
        assert metadata.sha256 is not None
        transfer_metadata = S3TransferObjectMetadata(
            sha256=metadata.sha256,
            content_type=metadata.media_type,
        )
        if not self.body:
            await preparation.promote_cleanup(
                preparation_object_handle=preparation.admitted_object_handle,
            )
            verified = await self.s3_service.create_empty_immutable(
                destination=destination,
                transfer_metadata=transfer_metadata,
            )
            return _validated_prepared(
                preparation.admitted_object_handle,
                verified,
                size=0,
                sha256=metadata.sha256,
            )

        upload = await self.s3_service.create_multipart_upload(
            destination=destination,
            transfer_metadata=transfer_metadata,
        )
        completed = False
        parts: list[S3CompletedPart] = []
        try:
            await preparation.register_cleanup(
                preparation_object_handle=preparation.admitted_object_handle,
                multipart_cleanup_handle=CoordinatorOpaqueObjectHandle(
                    upload.upload_id
                ),
            )
            for part_number, offset in enumerate(
                range(0, len(self.body), self.part_size),
                start=1,
            ):
                parts.append(
                    await self.s3_service.upload_part(
                        upload=upload,
                        part_number=part_number,
                        body=self.body[offset : offset + self.part_size],
                    )
                )
            verified = await self.s3_service.complete_multipart_upload(
                upload=upload,
                completed_parts=tuple(parts),
                expected_size=len(self.body),
                expected_sha256=metadata.sha256,
            )
            completed = True
            await preparation.promote_cleanup(
                preparation_object_handle=preparation.admitted_object_handle,
            )
            return _validated_prepared(
                preparation.admitted_object_handle,
                verified,
                size=len(self.body),
                sha256=metadata.sha256,
            )
        except asyncio.CancelledError:
            await self._cleanup(
                preparation=preparation,
                upload=upload,
                destination=destination,
                completed=completed,
            )
            raise
        except Exception:
            await self._cleanup(
                preparation=preparation,
                upload=upload,
                destination=destination,
                completed=completed,
            )
            raise

    async def _cleanup(
        self,
        *,
        preparation: ServerToRuntimePreparation,
        upload: S3MultipartUpload,
        destination: S3ObjectIdentity,
        completed: bool,
    ) -> None:
        """Clean the exact failed staging preparation."""
        if completed:
            await self.s3_service.delete(destination.bucket, destination.key)
        else:
            await self.s3_service.abort_multipart_upload(upload=upload)
        await preparation.clear_cleanup()

    async def revalidate(self) -> bool:
        """Revalidate current Session resource authority before dispatch."""
        return await self.revalidate_authority()


def _validated_prepared(
    object_handle: CoordinatorOpaqueObjectHandle,
    verified: S3VerifiedObject,
    *,
    size: int,
    sha256: str,
) -> PreparedServerToRuntimeObject:
    """Validate storage verification and build the prepared object result."""
    if verified.metadata.content_length != size or verified.sha256 != sha256:
        raise ValueError("Byte-source staging verification failed")
    return PreparedServerToRuntimeObject(
        object_handle=object_handle,
        size=size,
        sha256=sha256,
    )
