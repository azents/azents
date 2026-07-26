"""Trusted S3-native staging for authorized managed Server-to-Runtime sources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from azcommon.infra.s3.service import (
    S3ObjectIdentity,
    S3Service,
    S3TransferObjectMetadata,
    S3VerifiedObject,
)
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorOpaqueObjectHandle,
)

from azents.runtime.transfer.server_to_runtime import (
    PreparedServerToRuntimeObject,
    ServerToRuntimeSourceMetadata,
)
from azents.services.artifact import ArtifactTransferSource
from azents.services.exchange_file import ExchangeFileTransferSource


class ManagedObjectCopier(Protocol):
    """Trusted S3 native-copy operation required by managed source staging."""

    async def copy_immutable(
        self,
        *,
        source: S3ObjectIdentity,
        destination: S3ObjectIdentity,
        expected_size: int,
        transfer_metadata: S3TransferObjectMetadata,
        multipart_copy_threshold: int,
        multipart_part_size: int,
    ) -> S3VerifiedObject:
        """Copy one verified immutable source object."""
        ...


@dataclass(frozen=True)
class ManagedServerToRuntimeSource:
    """One authorized workspace object staged with a server-side immutable copy."""

    metadata: ServerToRuntimeSourceMetadata
    source_identity: S3ObjectIdentity
    revalidate_authority: Callable[[], Awaitable[bool]]
    s3_service: ManagedObjectCopier
    bucket: str
    transfer_object_prefix: str
    multipart_copy_threshold: int
    multipart_part_size: int

    async def prepare(
        self,
        *,
        admitted_object_handle: CoordinatorOpaqueObjectHandle,
    ) -> PreparedServerToRuntimeObject:
        """Copy and verify the authorized source without reading its body."""
        sha256 = self.metadata.sha256
        if sha256 is None:
            raise ValueError("Managed transfer source SHA-256 is required")
        verified = await self.s3_service.copy_immutable(
            source=self.source_identity,
            destination=S3ObjectIdentity(
                bucket=self.bucket,
                key="/".join(
                    (
                        self.transfer_object_prefix.strip("/"),
                        admitted_object_handle.value,
                    )
                ),
            ),
            expected_size=self.metadata.size,
            transfer_metadata=S3TransferObjectMetadata(
                sha256=sha256,
                content_type=self.metadata.media_type,
            ),
            multipart_copy_threshold=self.multipart_copy_threshold,
            multipart_part_size=self.multipart_part_size,
        )
        if (
            verified.metadata.content_length != self.metadata.size
            or verified.sha256 != sha256
        ):
            raise ValueError("Managed transfer copy verification failed")
        return PreparedServerToRuntimeObject(
            object_handle=admitted_object_handle,
            size=verified.metadata.content_length,
            sha256=verified.sha256,
        )

    async def revalidate(self) -> bool:
        """Revalidate source authority and expiry before READY/dispatch."""
        if (
            self.metadata.expires_at is not None
            and self.metadata.expires_at
            <= datetime.now(self.metadata.expires_at.tzinfo)
        ):
            return False
        return await self.revalidate_authority()


def managed_source_from_exchange(
    source: ExchangeFileTransferSource,
    *,
    s3_service: S3Service,
    bucket: str,
    transfer_object_prefix: str,
    multipart_copy_threshold: int,
    multipart_part_size: int,
    revalidate_authority: Callable[[], Awaitable[bool]],
) -> ManagedServerToRuntimeSource:
    """Convert authorized Exchange metadata into the closed managed source."""
    file = source.file
    return ManagedServerToRuntimeSource(
        metadata=ServerToRuntimeSourceMetadata(
            canonical_uri=file.uri,
            source_kind="exchange",
            display_name=file.filename,
            media_type=file.media_type,
            size=file.size_bytes,
            sha256=file.sha256,
            expires_at=file.expires_at,
        ),
        source_identity=S3ObjectIdentity(bucket=bucket, key=file.object_key),
        revalidate_authority=revalidate_authority,
        s3_service=s3_service,
        bucket=bucket,
        transfer_object_prefix=transfer_object_prefix,
        multipart_copy_threshold=multipart_copy_threshold,
        multipart_part_size=multipart_part_size,
    )


def managed_source_from_artifact(
    source: ArtifactTransferSource,
    *,
    s3_service: S3Service,
    bucket: str,
    transfer_object_prefix: str,
    multipart_copy_threshold: int,
    multipart_part_size: int,
    revalidate_authority: Callable[[], Awaitable[bool]],
) -> ManagedServerToRuntimeSource:
    """Convert authorized Artifact metadata into the closed managed source."""
    artifact = source.artifact
    return ManagedServerToRuntimeSource(
        metadata=ServerToRuntimeSourceMetadata(
            canonical_uri=artifact.uri,
            source_kind="artifact",
            display_name=artifact.name,
            media_type=artifact.media_type,
            size=artifact.size_bytes,
            sha256=artifact.sha256,
            expires_at=artifact.expires_at,
        ),
        source_identity=S3ObjectIdentity(bucket=bucket, key=artifact.storage_key),
        revalidate_authority=revalidate_authority,
        s3_service=s3_service,
        bucket=bucket,
        transfer_object_prefix=transfer_object_prefix,
        multipart_copy_threshold=multipart_copy_threshold,
        multipart_part_size=multipart_part_size,
    )
