"""Tests for incremental VFS Server-to-Runtime staging."""

import base64
import hashlib
from types import SimpleNamespace
from typing import cast

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
    CoordinatorClearPreparationCleanupRequest,
    CoordinatorOpaqueObjectHandle,
    CoordinatorPromotePreparationCleanupRequest,
    CoordinatorRegisterPreparationCleanupRequest,
    CoordinatorTransferStatus,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity

from azents.core.vfs import VFS_FILE_MAX_BYTES, VfsFileEntry
from azents.runtime.transfer.server_to_runtime import ServerToRuntimePreparation
from azents.runtime.transfer.vfs_source import VfsServerToRuntimeSource


class Store:
    def __init__(self, events: list[str] | None = None) -> None:
        self.aborted = False
        self.parts: list[bytes] = []
        self.identity = S3ObjectIdentity("bucket", "transfer/admitted")
        self.multipart_creations = 0
        self.empty_calls: list[dict[str, object]] = []
        self.deleted: list[tuple[str, str]] = []
        self.events = events

    async def create_multipart_upload(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3MultipartUpload:
        self.multipart_creations += 1
        if self.events is not None:
            self.events.append("create")
        self.identity = destination
        return S3MultipartUpload(destination, "upload")

    async def upload_part(
        self, *, upload: S3MultipartUpload, part_number: int, body: bytes
    ) -> S3CompletedPart:
        if self.events is not None:
            self.events.append("part")
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

    async def create_empty_immutable(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3VerifiedObject:
        self.empty_calls.append(
            {
                "destination": destination,
                "transfer_metadata": transfer_metadata,
            }
        )
        return S3VerifiedObject(
            S3ObjectMetadata(
                destination, 0, transfer_metadata.content_type, "etag", None, {}, None
            ),
            transfer_metadata.sha256,
        )

    async def delete(self, bucket: str, key: str) -> None:
        self.deleted.append((bucket, key))


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
    events: list[str] = []
    store = Store(events)
    cleanup = CleanupCoordinator(events)
    source = VfsServerToRuntimeSource(
        entry, _true, store, "bucket", "transfer", 16 * 1024
    )
    prepared = await source.prepare(preparation=_preparation(cleanup))
    assert prepared.size == VFS_FILE_MAX_BYTES
    assert hashlib.sha256(b"".join(store.parts)).hexdigest() == entry.content_hash
    assert [name for name, _ in cleanup.calls] == ["register", "promote"]
    registration = cleanup.calls[0][1]
    assert isinstance(registration, CoordinatorRegisterPreparationCleanupRequest)
    assert registration.preparation_object_handle.value == "admitted"
    assert registration.multipart_cleanup_handle.value == "upload"
    assert events.index("register") < events.index("part")


@pytest.mark.asyncio
async def test_vfs_invalid_base64_aborts_without_ready_object() -> None:
    entry = _entry(b"abc", encoded="not-base64!")
    store = Store()
    cleanup = CleanupCoordinator()
    source = VfsServerToRuntimeSource(
        entry, _true, store, "bucket", "transfer", 16 * 1024
    )
    with pytest.raises(ValueError, match="Base64"):
        await source.prepare(preparation=_preparation(cleanup))
    assert store.aborted
    assert [name for name, _ in cleanup.calls] == ["register", "clear"]


@pytest.mark.asyncio
async def test_vfs_zero_byte_source_uses_verified_empty_object_without_multipart() -> (
    None
):
    entry = _entry(b"")
    store = Store()
    cleanup = CleanupCoordinator()
    source = VfsServerToRuntimeSource(
        entry, _true, store, "bucket", "transfer", 16 * 1024
    )

    prepared = await source.prepare(preparation=_preparation(cleanup))

    assert prepared.size == 0
    assert prepared.sha256 == hashlib.sha256(b"").hexdigest()
    assert store.multipart_creations == 0
    assert store.parts == []
    assert len(store.empty_calls) == 1
    assert [name for name, _ in cleanup.calls] == ["promote"]


async def _true() -> bool:
    return True


def _preparation(
    cleanup: "CleanupCoordinator | None" = None,
) -> ServerToRuntimePreparation:
    return ServerToRuntimePreparation(
        identity=CoordinatorTransferIdentity(
            transfer_id="transfer",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            direction="download",
            operation_id="operation",
            session_id="session",
            agent_id="agent",
        ),
        admitted_object_handle=CoordinatorOpaqueObjectHandle("admitted"),
        coordinator=cleanup or CleanupCoordinator(),
        revision=1,
    )


class CleanupCoordinator:
    def __init__(self, events: list[str] | None = None) -> None:
        self.calls: list[tuple[str, object]] = []
        self.events = events

    async def register_preparation_cleanup(
        self,
        request: CoordinatorRegisterPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("register", request))
        if self.events is not None:
            self.events.append("register")
        return cast(
            CoordinatorTransferStatus,
            SimpleNamespace(revision=request.expected_revision + 1),
        )

    async def promote_preparation_cleanup(
        self,
        request: CoordinatorPromotePreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("promote", request))
        return cast(
            CoordinatorTransferStatus,
            SimpleNamespace(revision=request.expected_revision + 1),
        )

    async def clear_preparation_cleanup(
        self,
        request: CoordinatorClearPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("clear", request))
        return cast(
            CoordinatorTransferStatus,
            SimpleNamespace(revision=request.expected_revision + 1),
        )
