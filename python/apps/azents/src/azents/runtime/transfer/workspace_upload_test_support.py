"""Shared in-memory object-storage fixtures for Workspace upload tests."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

from azcommon.infra.s3.service import (
    S3ListedMultipartUpload,
    S3ListedObject,
    S3MultipartUpload,
    S3MultipartUploadPage,
    S3ObjectIdentity,
    S3ObjectMetadata,
    S3ObjectSummaryPage,
    S3PresignedRequest,
    S3TransferObjectMetadata,
    S3VerifiedObject,
)


@dataclass
class _Object:
    body: bytes
    content_type: str | None
    sha256: str
    modified_at: datetime


class _S3:
    """Small deterministic S3 protocol double with direct-object semantics."""

    def __init__(self, *, now: datetime | None = None) -> None:
        self.now = now or datetime(2026, 9, 17, tzinfo=UTC)
        self.objects: dict[str, _Object] = {}
        self.deleted: list[S3ObjectIdentity] = []
        self.copied: list[tuple[S3ObjectIdentity, S3ObjectIdentity]] = []
        self.upload_requests: list[S3PresignedRequest] = []
        self.download_requests: list[S3PresignedRequest] = []
        self.multipart_uploads: list[tuple[S3MultipartUpload, datetime]] = []
        self.aborted: list[S3MultipartUpload] = []
        self.transfer_sha256_override: str | None = None

    def seed(
        self,
        identity: S3ObjectIdentity,
        body: bytes,
        *,
        content_type: str | None = None,
        sha256: str | None = None,
        modified_at: datetime | None = None,
    ) -> None:
        """Publish one object as if a browser or provider had uploaded it."""
        self.objects[identity.key] = _Object(
            body=body,
            content_type=content_type,
            sha256=sha256 or hashlib.sha256(body).hexdigest(),
            modified_at=modified_at or self.now,
        )

    async def get_upload_request(
        self,
        *,
        identity: S3ObjectIdentity,
        content_type: str | None,
        checksum_sha256: str,
        expires_in: timedelta,
        now: datetime | None = None,
    ) -> S3PresignedRequest:
        """Return one transient checksum-bound PUT capability."""
        current = now or self.now
        headers: dict[str, str] = {
            "x-amz-checksum-sha256": base64.b64encode(
                bytes.fromhex(checksum_sha256)
            ).decode("ascii")
        }
        if content_type is not None:
            headers["content-type"] = content_type
        request = S3PresignedRequest(
            method="PUT",
            url=f"https://objects.test/{identity.key}",
            expires_at=current + expires_in,
            headers=MappingProxyType(headers),
        )
        self.upload_requests.append(request)
        return request

    async def get_download_request(
        self,
        *,
        identity: S3ObjectIdentity,
        expires_in: timedelta,
        now: datetime | None = None,
    ) -> S3PresignedRequest:
        """Return one transient exact-source GET capability."""
        current = now or self.now
        request = S3PresignedRequest(
            method="GET",
            url=f"https://objects.test/{identity.key}",
            expires_at=current + expires_in,
            headers=MappingProxyType({}),
        )
        self.download_requests.append(request)
        return request

    async def head(self, identity: S3ObjectIdentity) -> S3ObjectMetadata | None:
        """Return metadata without exposing object bytes."""
        item = self.objects.get(identity.key)
        if item is None:
            return None
        return S3ObjectMetadata(
            identity=identity,
            content_length=len(item.body),
            content_type=item.content_type,
            etag=f'"{item.sha256}"',
            checksum_sha256=base64.b64encode(bytes.fromhex(item.sha256)).decode(
                "ascii"
            ),
            user_metadata={"sha256": item.sha256},
            last_modified_at=item.modified_at,
        )

    async def head_with_checksum(
        self,
        identity: S3ObjectIdentity,
    ) -> S3ObjectMetadata | None:
        """Return checksum-aware metadata without exposing object bytes."""
        return await self.head(identity)

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
        """Copy one exact source into a new immutable object."""
        del multipart_copy_threshold, multipart_part_size
        item = self.objects.get(source.key)
        if item is None:
            raise FileNotFoundError(source.key)
        if len(item.body) != expected_size:
            raise ValueError("source size does not match expected_size")
        if destination.key in self.objects:
            raise FileExistsError(destination.key)
        self.seed(
            destination,
            item.body,
            content_type=transfer_metadata.content_type,
            sha256=transfer_metadata.sha256,
        )
        self.copied.append((source, destination))
        metadata = await self.head(destination)
        assert metadata is not None
        return S3VerifiedObject(metadata=metadata, sha256=transfer_metadata.sha256)

    async def verify_transfer_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject:
        """Verify exact size and transfer-owned digest metadata."""
        metadata = await self.head(identity)
        if metadata is None:
            raise FileNotFoundError(identity.key)
        if metadata.content_length != expected_size:
            raise ValueError("object size does not match expected_size")
        if metadata.user_metadata.get("sha256") != expected_sha256:
            raise ValueError("object SHA-256 metadata does not match expected_sha256")
        return S3VerifiedObject(
            metadata=metadata,
            sha256=self.transfer_sha256_override or expected_sha256,
        )

    async def delete(self, bucket: str, key: str) -> None:
        """Delete one exact object identity idempotently."""
        identity = S3ObjectIdentity(bucket=bucket, key=key)
        self.deleted.append(identity)
        self.objects.pop(key, None)

    async def list_object_summaries_page(
        self,
        *,
        bucket: str,
        prefix: str,
        maximum_keys: int,
        continuation_token: str | None,
    ) -> S3ObjectSummaryPage:
        """List one bounded page of object age evidence."""
        del continuation_token
        keys = sorted(key for key in self.objects if key.startswith(prefix))
        items = tuple(
            S3ListedObject(
                identity=S3ObjectIdentity(bucket=bucket, key=key),
                last_modified_at=self.objects[key].modified_at,
            )
            for key in keys[:maximum_keys]
        )
        return S3ObjectSummaryPage(
            objects=items,
            next_continuation_token=None,
            skipped_entries=0,
        )

    async def list_multipart_uploads_page(
        self,
        *,
        bucket: str,
        prefix: str,
        maximum_uploads: int,
        key_marker: str | None,
        upload_id_marker: str | None,
    ) -> S3MultipartUploadPage:
        """List one bounded page of incomplete multipart uploads."""
        del key_marker, upload_id_marker
        items = tuple(
            S3ListedMultipartUpload(upload=item, initiated_at=initiated_at)
            for item, initiated_at in self.multipart_uploads
            if item.identity.bucket == bucket and item.identity.key.startswith(prefix)
        )
        items = items[:maximum_uploads]
        return S3MultipartUploadPage(
            uploads=items,
            next_key_marker=None,
            next_upload_id_marker=None,
            skipped_entries=0,
        )

    async def abort_multipart_upload(self, *, upload: S3MultipartUpload) -> None:
        """Abort one exact multipart upload."""
        self.aborted.append(upload)
        self.multipart_uploads = [
            item for item in self.multipart_uploads if item[0] != upload
        ]
