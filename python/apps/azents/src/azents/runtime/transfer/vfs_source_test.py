"""Tests for incremental VFS Server-to-Runtime staging."""

import base64
import hashlib

import pytest
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

from azents.core.vfs import VFS_FILE_MAX_BYTES, VfsFileEntry
from azents.runtime.transfer.vfs_source import VfsServerToRuntimeSource


class Store:
    def __init__(self) -> None:
        self.aborted = False
        self.parts: list[bytes] = []
        self.identity = S3ObjectIdentity("bucket", "transfer/admitted")

    async def create_multipart_upload(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3MultipartUpload:
        self.identity = destination
        return S3MultipartUpload(destination, "upload")

    async def upload_part(
        self, *, upload: S3MultipartUpload, part_number: int, body: bytes
    ) -> S3CompletedPart:
        self.parts.append(body)
        return S3CompletedPart(part_number, f"etag-{part_number}")

    async def complete_multipart_upload(
        self,
        *,
        upload: S3MultipartUpload,
        completed_parts: tuple[S3CompletedPart, ...],
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject:
        return S3VerifiedObject(
            S3ObjectMetadata(
                self.identity, expected_size, None, "etag", None, {}, None
            ),
            expected_sha256,
        )

    async def abort_multipart_upload(self, *, upload: S3MultipartUpload) -> None:
        self.aborted = True


def _entry(
    body: bytes,
    *,
    encoded: str | None = None,
    size: int | None = None,
    sha256: str | None = None,
) -> VfsFileEntry:
    return VfsFileEntry(
        canonical_uri="azents://skills/a",
        source_id="source",
        source_revision_id="revision",
        content_hash=sha256 or hashlib.sha256(body).hexdigest(),
        size_bytes=len(body) if size is None else size,
        media_type="application/octet-stream",
        body_base64=encoded or base64.b64encode(body).decode(),
    )


@pytest.mark.asyncio
async def test_vfs_stages_accepted_two_mebibyte_boundary_without_decode_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"x" * VFS_FILE_MAX_BYTES
    entry = _entry(body)
    monkeypatch.setattr(
        VfsFileEntry,
        "decode_body",
        lambda self: (_ for _ in ()).throw(AssertionError("eager decode")),
    )
    store = Store()
    source = VfsServerToRuntimeSource(
        entry, _true, store, "bucket", "transfer", 16 * 1024
    )
    prepared = await source.prepare(
        admitted_object_handle=CoordinatorOpaqueObjectHandle("admitted")
    )
    assert prepared.size == VFS_FILE_MAX_BYTES
    assert hashlib.sha256(b"".join(store.parts)).hexdigest() == entry.content_hash


@pytest.mark.asyncio
async def test_vfs_invalid_base64_aborts_without_ready_object() -> None:
    entry = _entry(b"abc", encoded="not-base64!")
    store = Store()
    source = VfsServerToRuntimeSource(
        entry, _true, store, "bucket", "transfer", 16 * 1024
    )
    with pytest.raises(ValueError, match="Base64"):
        await source.prepare(
            admitted_object_handle=CoordinatorOpaqueObjectHandle("admitted")
        )
    assert store.aborted


async def _true() -> bool:
    return True
