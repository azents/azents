"""Tests for deferred provider Server-to-Runtime source staging."""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

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
    CoordinatorAdmitTransferRequest,
    CoordinatorAdmitTransferResult,
    CoordinatorCancelTransferRequest,
    CoordinatorCleanupStatus,
    CoordinatorClearPreparationCleanupRequest,
    CoordinatorDispatchStatus,
    CoordinatorDispatchTransferRequest,
    CoordinatorExpectedManifest,
    CoordinatorGetTransferStatusRequest,
    CoordinatorMarkTransferReadyRequest,
    CoordinatorOpaqueObjectHandle,
    CoordinatorPreparationCleanupState,
    CoordinatorPromotePreparationCleanupRequest,
    CoordinatorRegisterPreparationCleanupRequest,
    CoordinatorTransferDirection,
    CoordinatorTransferPhase,
    CoordinatorTransferStatus,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity

from azents.runtime.transfer.provider_source import (
    DeferredProviderServerToRuntimeSource,
)
from azents.runtime.transfer.server_to_runtime import (
    ServerToRuntimePreparation,
    ServerToRuntimeSourceMetadata,
    ServerToRuntimeTarget,
    ServerToRuntimeTransferError,
    ServerToRuntimeTransferRequest,
    ServerToRuntimeTransferService,
)

_NOW = datetime(2026, 7, 26, tzinfo=UTC)


class CleanupCoordinator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def register_preparation_cleanup(
        self,
        request: CoordinatorRegisterPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("register", request))
        return _status(request.identity, request.expected_revision + 1)

    async def promote_preparation_cleanup(
        self,
        request: CoordinatorPromotePreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("promote", request))
        return _status(request.identity, request.expected_revision + 1)

    async def clear_preparation_cleanup(
        self,
        request: CoordinatorClearPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("clear", request))
        return _status(request.identity, request.expected_revision + 1)


class Store:
    def __init__(self) -> None:
        self.aborted = False
        self.completed = False
        self.parts: list[bytes] = []
        self.copy_calls: list[dict[str, object]] = []
        self.deleted: list[tuple[str, str]] = []
        self.preparation_identity: S3ObjectIdentity | None = None

    async def create_preparation_multipart_upload(
        self,
        *,
        destination: S3ObjectIdentity,
        content_type: str | None,
    ) -> S3MultipartUpload:
        self.preparation_identity = destination
        return S3MultipartUpload(destination, "preparation-upload")

    async def upload_part(
        self,
        *,
        upload: S3MultipartUpload,
        part_number: int,
        body: bytes,
    ) -> S3CompletedPart:
        self.parts.append(body)
        return S3CompletedPart(part_number, f"etag-{part_number}")

    async def complete_preparation_multipart_upload(
        self,
        *,
        upload: S3MultipartUpload,
        completed_parts: tuple[S3CompletedPart, ...],
        expected_size: int,
    ) -> S3ObjectMetadata:
        self.completed = True
        return S3ObjectMetadata(
            identity=upload.identity,
            content_length=expected_size,
            content_type=None,
            etag="preparation-etag",
            checksum_sha256=None,
            user_metadata={},
            last_modified_at=None,
        )

    async def abort_multipart_upload(self, *, upload: S3MultipartUpload) -> None:
        self.aborted = True

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
        self.copy_calls.append(
            {
                "source": source,
                "destination": destination,
                "expected_size": expected_size,
                "transfer_metadata": transfer_metadata,
            }
        )
        return S3VerifiedObject(
            metadata=S3ObjectMetadata(
                identity=destination,
                content_length=expected_size,
                content_type=transfer_metadata.content_type,
                etag="canonical-etag",
                checksum_sha256=None,
                user_metadata={},
                last_modified_at=None,
            ),
            sha256=transfer_metadata.sha256,
        )

    async def delete(self, bucket: str, key: str) -> None:
        self.deleted.append((bucket, key))


class Stream:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks = chunks
        self.opened = 0
        self.closed = 0

    @asynccontextmanager
    async def __call__(
        self,
        *,
        maximum_chunk_size: int,
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        self.opened += 1

        async def iterator() -> AsyncIterator[bytes]:
            for chunk in self.chunks:
                assert len(chunk) <= maximum_chunk_size
                yield chunk

        try:
            yield iterator()
        finally:
            self.closed += 1


class BlockingStream(Stream):
    def __init__(self) -> None:
        super().__init__(())
        self.read_started = asyncio.Event()

    @asynccontextmanager
    async def __call__(
        self,
        *,
        maximum_chunk_size: int,
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        self.opened += 1

        async def iterator() -> AsyncIterator[bytes]:
            self.read_started.set()
            await asyncio.Future[None]()
            yield b"unreachable"

        try:
            yield iterator()
        finally:
            self.closed += 1


def _source(
    *,
    body: bytes,
    stream: Stream | None = None,
    declared_size: int | None = None,
    maximum_size: int | None = None,
) -> tuple[DeferredProviderServerToRuntimeSource, Store, Stream]:
    source_stream = stream or Stream((body,))
    store = Store()
    return (
        DeferredProviderServerToRuntimeSource(
            metadata=ServerToRuntimeSourceMetadata(
                canonical_uri="slack://opaque",
                source_kind="provider",
                display_name="provider.bin",
                media_type="application/octet-stream",
                size=len(body) if declared_size is None else declared_size,
                sha256=None,
                expires_at=None,
            ),
            open_stream=source_stream,
            revalidate_authority=_true,
            s3_service=store,
            bucket="workspace",
            transfer_object_prefix="runtime-transfer",
            preparation_id_source=lambda: "temporary",
            maximum_size=len(body) if maximum_size is None else maximum_size,
            stream_chunk_size=4,
            multipart_part_size=4,
            multipart_copy_threshold=4,
            multipart_copy_part_size=4,
        ),
        store,
        source_stream,
    )


def _preparation(
    cleanup: CleanupCoordinator,
) -> ServerToRuntimePreparation:
    identity = CoordinatorTransferIdentity(
        transfer_id="transfer",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        direction=CoordinatorTransferDirection.DOWNLOAD.value,
        operation_id="operation",
        session_id="session",
        agent_id="agent",
    )
    return ServerToRuntimePreparation(
        identity=identity,
        admitted_object_handle=CoordinatorOpaqueObjectHandle("admitted"),
        coordinator=cleanup,
        revision=1,
    )


@pytest.mark.asyncio
async def test_provider_stages_bounded_stream_then_promotes_to_canonical_object() -> (
    None
):
    body = b"provider-body"
    source, store, stream = _source(
        body=body,
        stream=Stream((b"prov", b"ider", b"-bod", b"y")),
    )
    cleanup = CleanupCoordinator()
    preparation = _preparation(cleanup)

    prepared = await source.prepare(preparation=preparation)

    assert prepared.size == len(body)
    assert prepared.sha256 == hashlib.sha256(body).hexdigest()
    assert stream.opened == stream.closed == 1
    assert b"".join(store.parts) == body
    assert [name for name, _ in cleanup.calls] == ["register", "promote", "clear"]
    assert preparation.revision == 4
    assert len(store.copy_calls) == 1
    copy = store.copy_calls[0]
    assert copy["source"] == S3ObjectIdentity(
        "workspace",
        "runtime-transfer/admitted-preparation-temporary",
    )
    assert copy["destination"] == S3ObjectIdentity(
        "workspace",
        "runtime-transfer/admitted",
    )
    assert store.deleted == [
        ("workspace", "runtime-transfer/admitted-preparation-temporary")
    ]


@pytest.mark.asyncio
async def test_provider_size_mismatch_aborts_and_clears_registered_cleanup() -> None:
    source, store, stream = _source(body=b"four", declared_size=3, maximum_size=4)
    cleanup = CleanupCoordinator()

    with pytest.raises(ValueError, match="size"):
        await source.prepare(preparation=_preparation(cleanup))

    assert stream.opened == stream.closed == 1
    assert store.aborted
    assert not store.copy_calls
    assert [name for name, _ in cleanup.calls] == ["register", "clear"]


@pytest.mark.asyncio
async def test_provider_cancellation_closes_response_and_aborts_registered_upload() -> (
    None
):
    stream = BlockingStream()
    source, store, _ = _source(body=b"body", stream=stream)
    cleanup = CleanupCoordinator()
    task = asyncio.create_task(source.prepare(preparation=_preparation(cleanup)))
    await stream.read_started.wait()

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.opened == stream.closed == 1
    assert store.aborted
    assert [name for name, _ in cleanup.calls] == ["register", "clear"]


class AdmissionRejectedCoordinator:
    async def admit_transfer(
        self,
        request: CoordinatorAdmitTransferRequest,
    ) -> CoordinatorAdmitTransferResult:
        raise ServerToRuntimeTransferError("Admission rejected")

    async def mark_transfer_ready(
        self,
        request: CoordinatorMarkTransferReadyRequest,
    ) -> CoordinatorTransferStatus:
        raise AssertionError(f"Unexpected ready call: {request}")

    async def dispatch_transfer(
        self,
        request: CoordinatorDispatchTransferRequest,
    ) -> CoordinatorTransferStatus:
        raise AssertionError(f"Unexpected dispatch call: {request}")

    async def get_transfer_status(
        self,
        request: CoordinatorGetTransferStatusRequest,
    ) -> CoordinatorTransferStatus:
        raise AssertionError(f"Unexpected status call: {request}")

    async def cancel_transfer(
        self,
        request: CoordinatorCancelTransferRequest,
    ) -> CoordinatorTransferStatus:
        raise AssertionError(f"Unexpected cancellation call: {request}")

    async def register_preparation_cleanup(
        self,
        request: CoordinatorRegisterPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        raise AssertionError(f"Unexpected cleanup registration: {request}")

    async def promote_preparation_cleanup(
        self,
        request: CoordinatorPromotePreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        raise AssertionError(f"Unexpected cleanup promotion: {request}")

    async def clear_preparation_cleanup(
        self,
        request: CoordinatorClearPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        raise AssertionError(f"Unexpected cleanup clear: {request}")


@pytest.mark.asyncio
async def test_provider_stream_does_not_open_when_admission_rejects() -> None:
    source, store, stream = _source(body=b"body")
    service = ServerToRuntimeTransferService(
        coordinator=AdmissionRejectedCoordinator(),
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
    )

    with pytest.raises(ServerToRuntimeTransferError, match="Admission"):
        await service.transfer(
            ServerToRuntimeTransferRequest(
                source=source,
                target=ServerToRuntimeTarget("runtime", 1),
                agent_id="agent",
                session_id="session",
                operation_id="operation",
                destination="/workspace/provider.bin",
                overwrite=False,
                product_maximum_size=4,
                provider_maximum_size=4,
                deadline_at=_NOW + timedelta(minutes=1),
            )
        )

    assert stream.opened == 0
    assert store.preparation_identity is None


def _status(
    identity: CoordinatorTransferIdentity,
    revision: int,
) -> CoordinatorTransferStatus:
    return CoordinatorTransferStatus(
        identity=identity,
        phase=CoordinatorTransferPhase.PREPARING,
        revision=revision,
        accepted_runner_generation=None,
        dispatch_id=None,
        dispatch_status=CoordinatorDispatchStatus.NOT_BOUND,
        expected_manifest=CoordinatorExpectedManifest(size=1, sha256=None),
        actual_manifest=None,
        deadline_at=_NOW + timedelta(minutes=1),
        logical_expires_at=_NOW + timedelta(minutes=1),
        outcome=None,
        failure=None,
        cleanup_status=CoordinatorCleanupStatus.NOT_REQUIRED,
        cancellation_requested=False,
        preparation_cleanup_state=CoordinatorPreparationCleanupState.NOT_REQUIRED,
    )


async def _true() -> bool:
    return True
