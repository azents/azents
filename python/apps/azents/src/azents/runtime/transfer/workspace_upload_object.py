"""Direct object-storage ingress and immutable Workspace upload sources."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Protocol

from azcommon.infra.s3.service import (
    S3MultipartUpload,
    S3MultipartUploadPage,
    S3ObjectIdentity,
    S3ObjectMetadata,
    S3ObjectSummaryPage,
    S3PresignedRequest,
    S3TransferObjectMetadata,
    S3VerifiedObject,
)

from azents.runtime.transfer.workspace_upload import (
    WorkspaceUploadRecord,
)


class WorkspaceUploadObjectError(RuntimeError):
    """Raised when an object-storage upload cannot be finalized safely."""


@dataclass(frozen=True)
class WorkspaceUploadUploadTicket:
    """Short-lived browser PUT capability for one opaque ingress object."""

    method: str
    url: str
    expires_at: datetime
    headers: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.method != "PUT":
            raise ValueError("Workspace upload ticket method must be PUT")
        if not self.url or len(self.url) > 8_192:
            raise ValueError("Workspace upload ticket URL is invalid")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("Workspace upload ticket expiry must be timezone-aware")
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


@dataclass(frozen=True)
class WorkspaceUploadDownloadTicket:
    """Short-lived Runner GET capability for one immutable source object."""

    method: str
    url: str
    expires_at: datetime
    headers: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.method != "GET":
            raise ValueError("Workspace download ticket method must be GET")
        if not self.url or len(self.url) > 8_192:
            raise ValueError("Workspace download ticket URL is invalid")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("Workspace download ticket expiry must be timezone-aware")
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


@dataclass(frozen=True)
class WorkspaceUploadFinalizeEvidence:
    """Verified immutable source evidence returned by object finalization."""

    source_handle: str
    actual_size: int
    actual_sha256: str


@dataclass(frozen=True)
class WorkspaceUploadObjectHandles:
    """Live object handles retained by Workspace upload metadata authority."""

    ingress_handles: frozenset[str]
    source_handles: frozenset[str]


class WorkspaceUploadObjectStoreS3(Protocol):
    """S3 operations required by the direct object upload flow."""

    async def get_upload_request(
        self,
        *,
        identity: S3ObjectIdentity,
        content_type: str | None,
        checksum_sha256: str,
        expires_in: timedelta,
        now: datetime | None = None,
    ) -> S3PresignedRequest: ...

    async def get_download_request(
        self,
        *,
        identity: S3ObjectIdentity,
        expires_in: timedelta,
        now: datetime | None = None,
    ) -> S3PresignedRequest: ...

    async def head_with_checksum(
        self,
        identity: S3ObjectIdentity,
    ) -> S3ObjectMetadata | None: ...

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

    async def verify_transfer_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject: ...

    async def delete(self, bucket: str, key: str) -> None: ...

    async def list_object_summaries_page(
        self,
        *,
        bucket: str,
        prefix: str,
        maximum_keys: int,
        continuation_token: str | None,
    ) -> S3ObjectSummaryPage: ...

    async def list_multipart_uploads_page(
        self,
        *,
        bucket: str,
        prefix: str,
        maximum_uploads: int,
        key_marker: str | None,
        upload_id_marker: str | None,
    ) -> S3MultipartUploadPage: ...

    async def abort_multipart_upload(self, *, upload: S3MultipartUpload) -> None: ...


class WorkspaceUploadObjectStore:
    """Own direct object tickets, immutable source snapshots, and cleanup."""

    def __init__(
        self,
        *,
        s3_service: WorkspaceUploadObjectStoreS3,
        bucket: str,
        ingress_object_prefix: str,
        source_object_prefix: str,
        ticket_ttl: timedelta,
        multipart_copy_threshold: int,
        multipart_part_size: int,
        clock: Callable[[], datetime],
    ) -> None:
        if not bucket:
            raise ValueError("Workspace upload object bucket is required")
        if not ingress_object_prefix.strip("/"):
            raise ValueError("Workspace upload ingress prefix is required")
        if not source_object_prefix.strip("/"):
            raise ValueError("Workspace upload source prefix is required")
        if ticket_ttl <= timedelta():
            raise ValueError("Workspace upload ticket TTL must be positive")
        if multipart_copy_threshold <= 0 or multipart_part_size <= 0:
            raise ValueError("Workspace upload copy bounds must be positive")
        self.s3_service = s3_service
        self.bucket = bucket
        self.ingress_object_prefix = ingress_object_prefix.strip("/")
        self.source_object_prefix = source_object_prefix.strip("/")
        self.ticket_ttl = ticket_ttl
        self.multipart_copy_threshold = multipart_copy_threshold
        self.multipart_part_size = multipart_part_size
        self.clock = clock

    async def issue_upload_ticket(
        self,
        record: WorkspaceUploadRecord,
    ) -> WorkspaceUploadUploadTicket:
        """Issue a checksum-bound PUT ticket without persisting its URL."""
        ingress_handle = record.ingress_handle
        expected_sha256 = record.admission.expected_sha256
        if ingress_handle is None or expected_sha256 is None:
            raise WorkspaceUploadObjectError(
                "Workspace upload ingress authority is unavailable"
            )
        expires_in = min(self.ticket_ttl, record.expires_at - self.clock())
        if expires_in <= timedelta():
            raise WorkspaceUploadObjectError("Workspace upload ticket has expired")
        request = await self.s3_service.get_upload_request(
            identity=self.ingress_identity(ingress_handle),
            content_type=record.admission.media_type,
            checksum_sha256=expected_sha256,
            expires_in=expires_in,
            now=self.clock(),
        )
        return WorkspaceUploadUploadTicket(
            method=request.method,
            url=request.url,
            expires_at=request.expires_at,
            headers=request.headers,
        )

    async def issue_download_ticket(
        self,
        *,
        source_handle: str,
        deadline_at: datetime,
    ) -> WorkspaceUploadDownloadTicket:
        """Issue one short-lived GET ticket for a verified immutable source."""
        expires_in = deadline_at - self.clock()
        if expires_in <= timedelta():
            raise WorkspaceUploadObjectError("Workspace download deadline has expired")
        request = await self.s3_service.get_download_request(
            identity=self.source_identity(source_handle),
            expires_in=expires_in,
            now=self.clock(),
        )
        return WorkspaceUploadDownloadTicket(
            method=request.method,
            url=request.url,
            expires_at=request.expires_at,
            headers=request.headers,
        )

    async def finalize(
        self,
        record: WorkspaceUploadRecord,
        *,
        source_handle: str,
    ) -> WorkspaceUploadFinalizeEvidence:
        """Verify the browser object and snapshot it to an immutable source key."""
        ingress_handle = record.ingress_handle
        expected_sha256 = record.admission.expected_sha256
        if ingress_handle is None or expected_sha256 is None:
            raise WorkspaceUploadObjectError(
                "Workspace upload finalize authority is unavailable"
            )
        ingress = await self.s3_service.head_with_checksum(
            self.ingress_identity(ingress_handle)
        )
        if ingress is None:
            raise FileNotFoundError("Workspace upload ingress object is missing")
        if ingress.content_length != record.admission.expected_size:
            raise WorkspaceUploadObjectError(
                "Workspace upload ingress size does not match the manifest"
            )
        if record.admission.media_type is not None and (
            ingress.content_type != record.admission.media_type
        ):
            raise WorkspaceUploadObjectError(
                "Workspace upload ingress content type does not match the manifest"
            )
        if ingress.checksum_sha256 is None:
            raise WorkspaceUploadObjectError(
                "Workspace upload ingress checksum evidence is unavailable"
            )
        if not _checksum_matches(ingress.checksum_sha256, expected_sha256):
            raise WorkspaceUploadObjectError(
                "Workspace upload ingress checksum does not match the manifest"
            )
        verified = await self.s3_service.copy_immutable(
            source=ingress.identity,
            destination=self.source_identity(source_handle),
            expected_size=record.admission.expected_size,
            transfer_metadata=S3TransferObjectMetadata(
                sha256=expected_sha256,
                content_type=record.admission.media_type,
            ),
            multipart_copy_threshold=self.multipart_copy_threshold,
            multipart_part_size=self.multipart_part_size,
        )
        if (
            verified.metadata.content_length != record.admission.expected_size
            or verified.sha256 != expected_sha256
        ):
            raise WorkspaceUploadObjectError(
                "Workspace upload immutable source verification failed"
            )
        return WorkspaceUploadFinalizeEvidence(
            source_handle=source_handle,
            actual_size=verified.metadata.content_length,
            actual_sha256=verified.sha256,
        )

    async def verify_source_object(
        self,
        *,
        source_handle: str,
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject:
        """Re-verify one immutable source immediately before Runtime delivery."""
        return await self.s3_service.verify_transfer_object(
            identity=self.source_identity(source_handle),
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )

    async def delete_ingress_object(self, handle: str) -> None:
        """Delete one exact browser-ingress object owned by an upload."""
        await self.s3_service.delete(
            self.bucket,
            self.ingress_identity(handle).key,
        )

    async def delete_source_object(self, handle: str) -> None:
        """Delete one exact immutable or incomplete snapshot object."""
        await self.s3_service.delete(
            self.bucket,
            self.source_identity(handle).key,
        )

    def ingress_identity(self, handle: str) -> S3ObjectIdentity:
        """Resolve one opaque ingress handle to its private object identity."""
        _validate_handle(handle)
        return S3ObjectIdentity(
            bucket=self.bucket,
            key=f"{self.ingress_object_prefix}/{handle}",
        )

    def source_identity(self, handle: str) -> S3ObjectIdentity:
        """Resolve one opaque immutable-source handle to its private identity."""
        _validate_handle(handle)
        return S3ObjectIdentity(
            bucket=self.bucket,
            key=f"{self.source_object_prefix}/{handle}",
        )


@dataclass(frozen=True)
class WorkspaceUploadObjectOrphanRepairResult:
    """Bounded evidence from one ingress/source orphan repair pass."""

    listed_objects: int
    deleted_objects: int
    listed_multipart_uploads: int
    aborted_multipart_uploads: int
    failed_cleanups: int
    skipped_storage_entries: int

    @property
    def observed(self) -> int:
        """Return the number of storage entries observed."""
        return (
            self.listed_objects
            + self.listed_multipart_uploads
            + self.skipped_storage_entries
        )


class WorkspaceUploadObjectOrphanRepair:
    """Remove aged ingress/source objects and multipart residue."""

    def __init__(
        self,
        *,
        object_store: WorkspaceUploadObjectStore,
        live_object_handles: Callable[[], Awaitable[WorkspaceUploadObjectHandles]],
    ) -> None:
        self.object_store = object_store
        self.live_object_handles = live_object_handles
        self._object_cursors: dict[str, str | None] = {
            f"{object_store.ingress_object_prefix}/": None,
            f"{object_store.source_object_prefix}/": None,
        }
        self._multipart_key_marker: str | None = None
        self._multipart_upload_id_marker: str | None = None

    async def repair_orphans(
        self,
        *,
        now: datetime,
        maximum_age: timedelta,
        page_size: int,
    ) -> WorkspaceUploadObjectOrphanRepairResult:
        """Delete only stale objects under the two owned prefixes."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Workspace upload orphan repair clock must be aware")
        if maximum_age <= timedelta():
            raise ValueError("Workspace upload orphan repair age must be positive")
        if page_size <= 0 or page_size > 1_000:
            raise ValueError("Workspace upload orphan repair page size is invalid")
        cutoff = now - maximum_age
        live_handles = await self.live_object_handles()
        prefixes = tuple(self._object_cursors)
        listed_objects = deleted_objects = failed_cleanups = skipped = 0
        for prefix in prefixes:
            page = await self.object_store.s3_service.list_object_summaries_page(
                bucket=self.object_store.bucket,
                prefix=prefix,
                maximum_keys=page_size,
                continuation_token=self._object_cursors[prefix],
            )
            listed_objects += len(page.objects)
            skipped += page.skipped_entries
            protected = (
                live_handles.ingress_handles
                if prefix == f"{self.object_store.ingress_object_prefix}/"
                else live_handles.source_handles
            )
            for item in page.objects:
                if item.last_modified_at > cutoff:
                    continue
                handle = _object_handle(item.identity.key, prefix)
                if handle is None or handle in protected:
                    skipped += 1
                    continue
                try:
                    await self.object_store.s3_service.delete(
                        item.identity.bucket,
                        item.identity.key,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    failed_cleanups += 1
                else:
                    deleted_objects += 1
            self._object_cursors[prefix] = page.next_continuation_token
        multipart_page = await self.object_store.s3_service.list_multipart_uploads_page(
            bucket=self.object_store.bucket,
            prefix=f"{self.object_store.source_object_prefix}/",
            maximum_uploads=page_size,
            key_marker=self._multipart_key_marker,
            upload_id_marker=self._multipart_upload_id_marker,
        )
        listed_multipart_uploads = len(multipart_page.uploads)
        skipped += multipart_page.skipped_entries
        aborted_multipart_uploads = 0
        for item in multipart_page.uploads:
            if item.initiated_at > cutoff:
                continue
            handle = _object_handle(
                item.upload.identity.key,
                f"{self.object_store.source_object_prefix}/",
            )
            if handle is None or handle in live_handles.source_handles:
                skipped += 1
                continue
            try:
                await self.object_store.s3_service.abort_multipart_upload(
                    upload=item.upload
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                failed_cleanups += 1
            else:
                aborted_multipart_uploads += 1
        self._multipart_key_marker = multipart_page.next_key_marker
        self._multipart_upload_id_marker = multipart_page.next_upload_id_marker
        return WorkspaceUploadObjectOrphanRepairResult(
            listed_objects=listed_objects,
            deleted_objects=deleted_objects,
            listed_multipart_uploads=listed_multipart_uploads,
            aborted_multipart_uploads=aborted_multipart_uploads,
            failed_cleanups=failed_cleanups,
            skipped_storage_entries=skipped,
        )


def _object_handle(key: str, prefix: str) -> str | None:
    """Extract one direct-object handle from an owned prefix."""
    if not key.startswith(prefix):
        return None
    handle = key[len(prefix) :]
    if not handle or "/" in handle:
        return None
    return handle


def _validate_handle(handle: str) -> None:
    if (
        not handle
        or len(handle) > 128
        or any(character not in "0123456789abcdef-" for character in handle)
    ):
        raise ValueError("Workspace upload object handle is invalid")


def _checksum_matches(value: str, expected_sha256: str) -> bool:
    if value == expected_sha256:
        return True
    try:
        return base64.b64decode(value, validate=True).hex() == expected_sha256
    except ValueError, UnicodeEncodeError:
        return False
