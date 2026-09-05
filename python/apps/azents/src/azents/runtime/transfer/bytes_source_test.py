"""Tests for trusted in-memory Server-to-Runtime source staging."""

import datetime
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
    CoordinatorCleanupStatus,
    CoordinatorClearPreparationCleanupRequest,
    CoordinatorDispatchStatus,
    CoordinatorExpectedManifest,
    CoordinatorObjectManifest,
    CoordinatorOpaqueObjectHandle,
    CoordinatorPreparationCleanupState,
    CoordinatorPromotePreparationCleanupRequest,
    CoordinatorRegisterPreparationCleanupRequest,
    CoordinatorTransferPhase,
    CoordinatorTransferStatus,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity

from azents.runtime.transfer.bytes_source import BytesServerToRuntimeSource
from azents.runtime.transfer.server_to_runtime import ServerToRuntimePreparation

_NOW = datetime.datetime(2026, 9, 5, tzinfo=datetime.UTC)


class _StagingStore:
    """Record multipart staging and optionally fail one upload part."""

    def __init__(self, *, fail_part: int | None = None) -> None:
        self.fail_part = fail_part
        self.uploaded_parts: list[bytes] = []
        self.aborted: list[S3MultipartUpload] = []
        self.deleted: list[S3ObjectIdentity] = []
        self.empty_destinations: list[S3ObjectIdentity] = []

    async def create_multipart_upload(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3MultipartUpload:
        del transfer_metadata
        return S3MultipartUpload(identity=destination, upload_id="upload-1")

    async def upload_part(
        self,
        *,
        upload: S3MultipartUpload,
        part_number: int,
        body: bytes,
    ) -> S3CompletedPart:
        del upload
        if part_number == self.fail_part:
            raise OSError("forced multipart failure")
        self.uploaded_parts.append(body)
        return S3CompletedPart(part_number=part_number, etag=f"etag-{part_number}")

    async def complete_multipart_upload(
        self,
        *,
        upload: S3MultipartUpload,
        completed_parts: tuple[S3CompletedPart, ...],
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject:
        del completed_parts
        return _verified(
            upload.identity,
            size=expected_size,
            sha256=expected_sha256,
        )

    async def abort_multipart_upload(self, *, upload: S3MultipartUpload) -> None:
        self.aborted.append(upload)

    async def create_empty_immutable(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3VerifiedObject:
        self.empty_destinations.append(destination)
        return _verified(destination, size=0, sha256=transfer_metadata.sha256)

    async def delete(self, bucket: str, key: str) -> None:
        self.deleted.append(S3ObjectIdentity(bucket=bucket, key=key))


class _CleanupCoordinator:
    """Return revision-fenced status and record cleanup transitions."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def register_preparation_cleanup(
        self,
        request: CoordinatorRegisterPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append("register")
        return _status(request.identity, request.expected_revision + 1)

    async def promote_preparation_cleanup(
        self,
        request: CoordinatorPromotePreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append("promote")
        return _status(request.identity, request.expected_revision + 1)

    async def clear_preparation_cleanup(
        self,
        request: CoordinatorClearPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append("clear")
        return _status(request.identity, request.expected_revision + 1)


async def _true() -> bool:
    return True


def _source(
    body: bytes,
    *,
    store: _StagingStore,
    part_size: int = 2,
) -> BytesServerToRuntimeSource:
    return BytesServerToRuntimeSource(
        body=body,
        canonical_uri="tool-output://run-1/call-1/0",
        source_kind="tool_output_text",
        display_name="output.txt",
        media_type="text/plain",
        revalidate_authority=_true,
        s3_service=store,
        bucket="workspace",
        transfer_object_prefix="runtime-transfer",
        part_size=part_size,
    )


def _preparation(
    coordinator: _CleanupCoordinator,
) -> ServerToRuntimePreparation:
    return ServerToRuntimePreparation(
        identity=CoordinatorTransferIdentity(
            transfer_id="transfer-1",
            attempt_id="attempt-1",
            runtime_id="runtime-1",
            desired_generation=1,
            direction="download",
            operation_id="run-1",
            session_id="session-1",
            agent_id="agent-1",
        ),
        admitted_object_handle=CoordinatorOpaqueObjectHandle("admitted-1"),
        coordinator=coordinator,
        revision=1,
    )


def _verified(
    identity: S3ObjectIdentity,
    *,
    size: int,
    sha256: str,
) -> S3VerifiedObject:
    return S3VerifiedObject(
        metadata=S3ObjectMetadata(
            identity=identity,
            content_length=size,
            content_type="text/plain",
            etag="etag",
            checksum_sha256=None,
            user_metadata={},
            last_modified_at=None,
        ),
        sha256=sha256,
    )


def _status(
    identity: CoordinatorTransferIdentity,
    revision: int,
) -> CoordinatorTransferStatus:
    digest = hashlib.sha256(b"abcdef").hexdigest()
    return CoordinatorTransferStatus(
        identity=identity,
        phase=CoordinatorTransferPhase.PREPARING,
        revision=revision,
        accepted_runner_generation=None,
        dispatch_id=None,
        dispatch_status=CoordinatorDispatchStatus.NOT_BOUND,
        expected_manifest=CoordinatorExpectedManifest(size=6, sha256=digest),
        actual_manifest=CoordinatorObjectManifest(size=6, sha256=digest),
        deadline_at=_NOW + datetime.timedelta(minutes=1),
        logical_expires_at=_NOW + datetime.timedelta(minutes=1),
        outcome=None,
        failure=None,
        cleanup_status=CoordinatorCleanupStatus.NOT_REQUIRED,
        cancellation_requested=False,
        preparation_cleanup_state=CoordinatorPreparationCleanupState.NOT_REQUIRED,
    )


async def test_multipart_prepare_stages_exact_chunks_and_hash() -> None:
    """Upload exact bounded chunks and promote verified cleanup authority."""
    store = _StagingStore()
    coordinator = _CleanupCoordinator()
    source = _source(b"abcdef", store=store)

    prepared = await source.prepare(preparation=_preparation(coordinator))

    assert store.uploaded_parts == [b"ab", b"cd", b"ef"]
    assert prepared.object_handle == CoordinatorOpaqueObjectHandle("admitted-1")
    assert prepared.size == 6
    assert prepared.sha256 == hashlib.sha256(b"abcdef").hexdigest()
    assert coordinator.calls == ["register", "promote"]
    assert store.aborted == []
    assert store.deleted == []


async def test_multipart_failure_aborts_owned_upload_and_clears_cleanup() -> None:
    """Compensate the exact multipart upload after staging fails."""
    store = _StagingStore(fail_part=2)
    coordinator = _CleanupCoordinator()
    source = _source(b"abcdef", store=store)

    with pytest.raises(OSError, match="forced multipart failure"):
        await source.prepare(preparation=_preparation(coordinator))

    assert len(store.aborted) == 1
    assert store.deleted == []
    assert coordinator.calls == ["register", "clear"]


async def test_empty_body_creates_verified_immutable_object() -> None:
    """Stage empty output without creating a multipart upload."""
    store = _StagingStore()
    coordinator = _CleanupCoordinator()
    source = _source(b"", store=store)

    prepared = await source.prepare(preparation=_preparation(coordinator))

    assert prepared.size == 0
    assert prepared.sha256 == hashlib.sha256(b"").hexdigest()
    assert store.empty_destinations == [
        S3ObjectIdentity(
            bucket="workspace",
            key="runtime-transfer/admitted-1",
        )
    ]
    assert store.uploaded_parts == []
    assert coordinator.calls == ["promote"]
