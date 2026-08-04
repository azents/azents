"""Bounded Runner download transfer servicer tests."""

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportPrivateUsage=false
# ruff: noqa: E501

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import grpc
import pytest
from azcommon.infra.s3.service import (
    S3CompletedPart,
    S3MultipartUpload,
    S3ObjectIdentity,
    S3ObjectMetadata,
    S3TransferObjectMetadata,
    S3VerifiedObject,
)
from azents_runtime_control.proto import runtime_runner_transfer_pb2 as pb
from azents_runtime_control.transfer import (
    MAX_TRANSFER_CHUNK_BYTES,
    MULTIPART_PART_BYTES,
)

import azents.runtime.control_protocol.grpc.runner_transfer_server as transfer_server_module
from azents.core.runtime_runner_credential import (
    RuntimeRunnerCredential,
    RuntimeRunnerCredentialInvalid,
)
from azents.runtime.control_protocol.grpc.runner_transfer_server import (
    RuntimeRunnerTransferGrpcServicer,
    _RoundRobinChunkScheduler,
    _StreamLeaseKeeper,
    _StreamTermination,
)
from azents.runtime.coordination.data import RuntimeConnectionKind
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.runtime.transfer.coordinator import RuntimeTransferCoordinator
from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCancellationReason,
    RuntimeTransferCleanupStatus,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferFailure,
    RuntimeTransferObject,
    RuntimeTransferOutcome,
    RuntimeTransferPhase,
    RuntimeTransferRecord,
)
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore
from azents.testing.grpc import (
    FakeGrpcContext,
    GrpcMetadata,
)

_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
_DIGEST = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _Abort(RuntimeError):
    def __init__(self, code: grpc.StatusCode) -> None:
        self.code = code


class _Context[RequestT, ResponseT](FakeGrpcContext[RequestT, ResponseT]):
    def __init__(self, *, token: str | None = "token") -> None:
        super().__init__(
            metadata=(() if token is None else (("authorization", f"Bearer {token}"),))
        )
        self.token = token
        self.is_cancelled = False

    async def abort(
        self,
        code: grpc.StatusCode,
        details: str = "",
        trailing_metadata: GrpcMetadata = (),
    ) -> NoReturn:
        del details, trailing_metadata
        raise _Abort(code)

    def cancelled(self) -> bool:
        return self.is_cancelled


def _verified_object(
    identity: S3ObjectIdentity,
    *,
    size: int,
    sha256: str,
) -> S3VerifiedObject:
    return S3VerifiedObject(
        metadata=S3ObjectMetadata(
            identity=identity,
            content_length=size,
            content_type=None,
            etag=None,
            checksum_sha256=sha256,
            user_metadata={},
            last_modified_at=None,
        ),
        sha256=sha256,
    )


@pytest.mark.asyncio
async def test_round_robin_chunk_scheduler_rotates_waiting_files() -> None:
    """A file returns behind another waiting file before its next chunk turn."""
    scheduler = _RoundRobinChunkScheduler(maximum_in_flight=1)

    await scheduler.acquire("first")
    second_turn = asyncio.create_task(scheduler.acquire("second"))
    await asyncio.sleep(0)

    await scheduler.release("first", requeue=True)
    await second_turn
    await scheduler.release("second", requeue=False)

    await scheduler.acquire("first")
    await scheduler.release("first", requeue=False)
    await scheduler.unregister("first")
    await scheduler.unregister("second")


class _Authenticator:
    def __init__(
        self,
        *,
        desired_generation: int = 1,
        authorized: bool = True,
    ) -> None:
        self.credential = RuntimeRunnerCredential(
            "credential-1",
            "runtime-1",
            desired_generation,
        )
        self.authorized = authorized

    async def authenticate_runner(self, secret: str) -> RuntimeRunnerCredential:
        if secret != "token":
            raise RuntimeRunnerCredentialInvalid("invalid")
        return self.credential

    async def authorize_runner(self, credential: RuntimeRunnerCredential) -> bool:
        return self.authorized and credential == self.credential


class _ObjectStore:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.verify_calls = 0
        self.closed = False
        self.multipart_creates = 0
        self.preparation_multipart_creates = 0
        self.preparation_completes = 0
        self.copy_calls: list[tuple[S3ObjectIdentity, S3ObjectIdentity]] = []
        self.uploaded_parts: list[tuple[int, bytes]] = []
        self.completed_parts: tuple[S3CompletedPart, ...] | None = None
        self.abort_calls = 0
        self.delete_calls = 0
        self.empty_creates = 0
        self.abort_error = False
        self.complete_error = False
        self.verify_error = False

    async def verify_transfer_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject:
        self.verify_calls += 1
        if self.verify_error:
            raise RuntimeError("verify failed")
        return _verified_object(
            identity,
            size=expected_size,
            sha256=expected_sha256,
        )

    @asynccontextmanager
    async def iter_chunks(
        self,
        identity: S3ObjectIdentity,
        *,
        maximum_chunk_size: int,
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        del identity

        async def _chunks() -> AsyncIterator[bytes]:
            for chunk in self.chunks:
                assert len(chunk) <= maximum_chunk_size
                yield chunk

        try:
            yield _chunks()
        finally:
            self.closed = True

    async def create_multipart_upload(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3MultipartUpload:
        del transfer_metadata
        self.multipart_creates += 1
        return S3MultipartUpload(identity=destination, upload_id="multipart-1")

    async def create_preparation_multipart_upload(
        self,
        *,
        destination: S3ObjectIdentity,
        content_type: str | None,
    ) -> S3MultipartUpload:
        del content_type
        self.preparation_multipart_creates += 1
        return S3MultipartUpload(identity=destination, upload_id="preparation-1")

    async def upload_part(
        self,
        *,
        upload: S3MultipartUpload,
        part_number: int,
        body: bytes,
    ) -> S3CompletedPart:
        del upload
        self.uploaded_parts.append((part_number, body))
        return S3CompletedPart(part_number=part_number, etag=f"etag-{part_number}")

    async def complete_multipart_upload(
        self,
        *,
        upload: S3MultipartUpload,
        completed_parts: tuple[S3CompletedPart, ...],
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject:
        self.completed_parts = completed_parts
        if self.complete_error:
            raise RuntimeError("complete failed")
        return _verified_object(
            upload.identity,
            size=expected_size,
            sha256=expected_sha256,
        )

    async def complete_preparation_multipart_upload(
        self,
        *,
        upload: S3MultipartUpload,
        completed_parts: tuple[S3CompletedPart, ...],
        expected_size: int,
    ) -> object:
        del upload, expected_size
        self.preparation_completes += 1
        self.completed_parts = completed_parts
        if self.complete_error:
            raise RuntimeError("complete failed")
        return object()

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
        del multipart_copy_threshold, multipart_part_size
        self.copy_calls.append((source, destination))
        return _verified_object(
            destination,
            size=expected_size,
            sha256=transfer_metadata.sha256,
        )

    async def abort_multipart_upload(self, *, upload: S3MultipartUpload) -> None:
        del upload
        self.abort_calls += 1
        if self.abort_error:
            raise RuntimeError("abort failed")

    async def create_empty_immutable(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3VerifiedObject:
        self.empty_creates += 1
        return _verified_object(
            destination,
            size=0,
            sha256=transfer_metadata.sha256,
        )

    async def delete_verified_transfer_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        del identity, expected_size, expected_sha256
        self.delete_calls += 1

    async def delete(self, bucket: str, key: str) -> None:
        del bucket, key
        self.delete_calls += 1


@pytest.mark.asyncio
async def test_download_streams_offsets_completion_and_closes_body() -> None:
    harness = await _harness(chunks=[b"a", b"bc"])

    frames = [
        frame
        async for frame in harness.servicer.DownloadTransfer(_request(), _Context())
    ]

    assert [frame.chunk.offset for frame in frames[:-1]] == [0, 1]
    assert [frame.chunk.data for frame in frames[:-1]] == [b"a", b"bc"]
    assert frames[-1].complete.actual_size == 3
    assert frames[-1].complete.sha256 == _DIGEST
    assert harness.object_store.verify_calls == 1
    assert harness.object_store.closed is True


@pytest.mark.asyncio
async def test_zero_byte_download_emits_only_completion() -> None:
    harness = await _harness(
        chunks=[],
        size=0,
        sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )

    frames = [
        frame
        async for frame in harness.servicer.DownloadTransfer(_request(), _Context())
    ]

    assert len(frames) == 1
    assert frames[0].complete.actual_size == 0
    assert harness.object_store.closed is True


@pytest.mark.asyncio
async def test_download_separates_desired_and_reconnected_runner_generations() -> None:
    """A physical reconnect remains valid within one desired Runtime generation."""
    harness = await _harness(
        chunks=[b"abc"],
        desired_generation=7,
        connection_registrations=2,
    )

    frames = [
        frame
        async for frame in harness.servicer.DownloadTransfer(
            _request(runner_generation=2),
            _Context(),
        )
    ]

    assert frames[-1].complete.actual_size == 3
    record = await harness.state.get("transfer-1")
    assert record is not None
    assert record.admission.desired_generation == 7
    assert record.accepted_runner_generation == 2
    assert record.phase is RuntimeTransferPhase.VERIFYING


@pytest.mark.asyncio
async def test_progress_is_coalesced_by_byte_and_time_thresholds() -> None:
    """Small chunks avoid state writes while byte/time barriers still persist."""
    clock = _Clock(_NOW)
    size = 2 * 1024 * 1024
    harness = await _harness(
        chunks=[],
        size=size,
        sha256="a" * 64,
        clock=clock,
    )
    streaming = await harness.claim()
    context = _Context()

    small = await harness.servicer._record_progress(
        streaming,
        128 * 1024,
        context,
        force=False,
    )
    assert small.revision == streaming.revision
    assert small.progress is None

    clock.now += timedelta(seconds=2)
    timed = await harness.servicer._record_progress(
        small,
        256 * 1024,
        context,
        force=False,
    )
    assert timed.revision == streaming.revision + 1
    assert timed.progress is not None
    assert timed.progress.bytes_transferred == 256 * 1024

    coalesced = await harness.servicer._record_progress(
        timed,
        512 * 1024,
        context,
        force=False,
    )
    assert coalesced.revision == timed.revision

    threshold = await harness.servicer._record_progress(
        coalesced,
        1280 * 1024,
        context,
        force=False,
    )
    assert threshold.revision == timed.revision + 1
    assert threshold.progress is not None
    assert threshold.progress.bytes_transferred == 1280 * 1024

    forced = await harness.servicer._record_progress(
        threshold,
        size,
        context,
        force=True,
    )
    assert forced.progress is not None
    assert forced.progress.bytes_transferred == size


@pytest.mark.asyncio
async def test_missing_or_stale_auth_fails_before_s3() -> None:
    harness = await _harness(chunks=[b"abc"])

    with pytest.raises(_Abort) as error:
        _ = [
            frame
            async for frame in harness.servicer.DownloadTransfer(
                _request(), _Context(token=None)
            )
        ]

    assert error.value.code is grpc.StatusCode.UNAUTHENTICATED
    assert harness.object_store.verify_calls == 0


@pytest.mark.asyncio
async def test_wrong_direction_or_duplicate_claim_fails_before_s3() -> None:
    upload = await _harness(chunks=[b"abc"], direction=RuntimeTransferDirection.UPLOAD)
    with pytest.raises(_Abort):
        _ = [
            frame
            async for frame in upload.servicer.DownloadTransfer(_request(), _Context())
        ]
    assert upload.object_store.verify_calls == 0

    duplicate = await _harness(chunks=[b"abc"])
    await duplicate.claim()
    with pytest.raises(_Abort):
        _ = [
            frame
            async for frame in duplicate.servicer.DownloadTransfer(
                _request(), _Context()
            )
        ]
    assert duplicate.object_store.verify_calls == 0


@pytest.mark.asyncio
async def test_upload_aggregates_bounded_parts_and_publishes_available() -> None:
    data = b"a" * MULTIPART_PART_BYTES + b"z"
    digest = hashlib.sha256(data).hexdigest()
    harness = await _harness(
        chunks=[],
        size=len(data),
        sha256=digest,
        direction=RuntimeTransferDirection.UPLOAD,
    )

    result = await harness.servicer.UploadTransfer(
        _upload_frames(
            data[:MAX_TRANSFER_CHUNK_BYTES],
            *(
                data[offset : offset + MAX_TRANSFER_CHUNK_BYTES]
                for offset in range(
                    MAX_TRANSFER_CHUNK_BYTES,
                    MULTIPART_PART_BYTES,
                    MAX_TRANSFER_CHUNK_BYTES,
                )
            ),
            b"z",
        ),
        _Context(),
    )

    assert result.status == pb.UPLOAD_TRANSFER_STATUS_SUCCEEDED
    assert result.actual_size == len(data)
    assert result.sha256 == digest
    assert harness.object_store.multipart_creates == 1
    assert [part[0] for part in harness.object_store.uploaded_parts] == [1, 2]
    assert [len(part[1]) for part in harness.object_store.uploaded_parts] == [
        MULTIPART_PART_BYTES,
        1,
    ]
    assert harness.object_store.completed_parts is not None
    record = await harness.state.get("transfer-1")
    assert record is not None
    assert record.phase is RuntimeTransferPhase.AVAILABLE
    assert record.actual_size == len(data)
    assert record.actual_sha256 == digest
    assert record.cleanup_status is RuntimeTransferCleanupStatus.COMPLETE
    assert record.multipart_cleanup_handle is None


@pytest.mark.asyncio
async def test_zero_byte_upload_uses_verified_empty_object_path() -> None:
    empty_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    harness = await _harness(
        chunks=[],
        size=0,
        sha256=empty_sha256,
        direction=RuntimeTransferDirection.UPLOAD,
    )

    result = await harness.servicer.UploadTransfer(_upload_frames(), _Context())

    assert result.status == pb.UPLOAD_TRANSFER_STATUS_SUCCEEDED
    assert result.actual_size == 0
    assert result.sha256 == empty_sha256
    assert harness.object_store.empty_creates == 1
    assert harness.object_store.multipart_creates == 0


@pytest.mark.asyncio
async def test_unknown_digest_upload_promotes_preparation_object_after_verification() -> (
    None
):
    """Upload accepts an unknown expected digest and publishes actual evidence."""
    data = b"abc"
    digest = hashlib.sha256(data).hexdigest()
    harness = await _harness(
        chunks=[],
        size=len(data),
        sha256=None,
        direction=RuntimeTransferDirection.UPLOAD,
    )

    result = await harness.servicer.UploadTransfer(_upload_frames(data), _Context())

    assert result.status == pb.UPLOAD_TRANSFER_STATUS_SUCCEEDED
    assert result.sha256 == digest
    assert harness.object_store.preparation_multipart_creates == 1
    assert harness.object_store.preparation_completes == 1
    assert len(harness.object_store.copy_calls) == 1
    record = await harness.state.get("transfer-1")
    assert record is not None
    assert record.phase is RuntimeTransferPhase.AVAILABLE
    assert record.object is not None
    assert record.object.sha256 == digest
    assert record.actual_sha256 == digest
    assert record.pre_ready_object_handle is None


@pytest.mark.asyncio
async def test_upload_rejects_invalid_frames_and_auth_before_s3() -> None:
    invalid = await _harness(
        chunks=[],
        direction=RuntimeTransferDirection.UPLOAD,
    )
    with pytest.raises(_Abort) as error:
        await invalid.servicer.UploadTransfer(
            _frames(
                pb.UploadTransferFrame(chunk=pb.TransferChunk(offset=0, data=b"a"))
            ),
            _Context(),
        )
    assert error.value.code is grpc.StatusCode.FAILED_PRECONDITION
    assert invalid.object_store.multipart_creates == 0

    unauthorized = await _harness(
        chunks=[],
        direction=RuntimeTransferDirection.UPLOAD,
    )
    with pytest.raises(_Abort) as error:
        await unauthorized.servicer.UploadTransfer(
            _upload_frames(b"abc"), _Context(token=None)
        )
    assert error.value.code is grpc.StatusCode.UNAUTHENTICATED
    assert unauthorized.object_store.multipart_creates == 0

    duplicate = await _harness(
        chunks=[],
        direction=RuntimeTransferDirection.UPLOAD,
    )
    await duplicate.claim()
    with pytest.raises(_Abort) as error:
        await duplicate.servicer.UploadTransfer(_upload_frames(b"abc"), _Context())
    assert error.value.code is grpc.StatusCode.ALREADY_EXISTS
    assert duplicate.object_store.multipart_creates == 0


@pytest.mark.asyncio
async def test_upload_offset_failure_aborts_and_records_cleanup() -> None:
    harness = await _harness(
        chunks=[],
        direction=RuntimeTransferDirection.UPLOAD,
    )
    with pytest.raises(_Abort) as error:
        await harness.servicer.UploadTransfer(
            _frames(
                pb.UploadTransferFrame(
                    open=pb.UploadTransferOpen(identity=_upload_identity())
                ),
                pb.UploadTransferFrame(chunk=pb.TransferChunk(offset=0, data=b"a")),
                pb.UploadTransferFrame(chunk=pb.TransferChunk(offset=2, data=b"bc")),
            ),
            _Context(),
        )

    assert error.value.code is grpc.StatusCode.DATA_LOSS
    assert harness.object_store.abort_calls >= 1
    record = await harness.state.get("transfer-1")
    assert record is not None
    assert record.phase is RuntimeTransferPhase.TERMINAL
    assert record.cleanup_status is RuntimeTransferCleanupStatus.COMPLETE
    assert record.multipart_cleanup_handle is None


@pytest.mark.asyncio
async def test_upload_complete_and_abort_failures_preserve_cleanup_evidence() -> None:
    complete_failure = await _harness(
        chunks=[],
        direction=RuntimeTransferDirection.UPLOAD,
    )
    complete_failure.object_store.complete_error = True
    with pytest.raises(_Abort) as error:
        await complete_failure.servicer.UploadTransfer(
            _upload_frames(b"abc"), _Context()
        )
    assert error.value.code is grpc.StatusCode.INTERNAL
    assert complete_failure.object_store.abort_calls >= 1
    completed_record = await complete_failure.state.get("transfer-1")
    assert completed_record is not None
    assert completed_record.phase is RuntimeTransferPhase.TERMINAL
    assert completed_record.cleanup_status is RuntimeTransferCleanupStatus.COMPLETE

    abort_failure = await _harness(
        chunks=[],
        direction=RuntimeTransferDirection.UPLOAD,
    )
    abort_failure.object_store.abort_error = True
    with pytest.raises(_Abort) as error:
        await abort_failure.servicer.UploadTransfer(
            _frames(
                pb.UploadTransferFrame(
                    open=pb.UploadTransferOpen(identity=_upload_identity())
                ),
                pb.UploadTransferFrame(chunk=pb.TransferChunk(offset=0, data=b"abc")),
                pb.UploadTransferFrame(
                    complete=pb.UploadTransferComplete(actual_size=3, sha256="0" * 64)
                ),
            ),
            _Context(),
        )
    assert error.value.code is grpc.StatusCode.DATA_LOSS
    failed_record = await abort_failure.state.get("transfer-1")
    assert failed_record is not None
    assert failed_record.phase is RuntimeTransferPhase.TERMINAL
    assert (
        failed_record.cleanup_status is RuntimeTransferCleanupStatus.RETRYABLE_FAILURE
    )
    assert failed_record.multipart_cleanup_handle == "multipart-1"


@pytest.mark.asyncio
async def test_download_generic_storage_failure_maps_internal() -> None:
    """Unclassified object-store failures settle and return bounded INTERNAL."""
    harness = await _harness(chunks=[b"abc"])
    harness.object_store.verify_error = True

    with pytest.raises(_Abort) as error:
        _ = [
            frame
            async for frame in harness.servicer.DownloadTransfer(
                _request(),
                _Context(),
            )
        ]

    assert error.value.code is grpc.StatusCode.INTERNAL
    record = await harness.state.get("transfer-1")
    assert record is not None
    assert record.phase is RuntimeTransferPhase.TERMINAL
    assert record.failure is RuntimeTransferFailure.STREAM


@pytest.mark.asyncio
async def test_download_read_failure_at_deadline_maps_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A body read failure cannot mask deadline authority on the wire."""
    clock = _Clock(_NOW)
    harness = await _harness(chunks=[b"abc"], clock=clock)

    @asynccontextmanager
    async def fail_at_deadline(
        identity: S3ObjectIdentity,
        *,
        maximum_chunk_size: int,
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        del identity, maximum_chunk_size

        async def chunks() -> AsyncIterator[bytes]:
            clock.now = _NOW + timedelta(minutes=5)
            raise RuntimeError("read failed at deadline")
            yield b""  # pragma: no cover

        yield chunks()

    monkeypatch.setattr(harness.object_store, "iter_chunks", fail_at_deadline)

    with pytest.raises(_Abort) as error:
        _ = [
            frame
            async for frame in harness.servicer.DownloadTransfer(
                _request(),
                _Context(),
            )
        ]

    assert error.value.code is grpc.StatusCode.DEADLINE_EXCEEDED
    record = await harness.state.get("transfer-1")
    assert record is not None
    assert record.phase is RuntimeTransferPhase.TERMINAL
    assert record.terminal_outcome is RuntimeTransferOutcome.EXPIRED
    assert record.failure is RuntimeTransferFailure.EXPIRED


@pytest.mark.asyncio
async def test_stream_lease_backend_failure_fences_and_cancels_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any ordinary renewal backend failure fails closed."""
    harness = await _harness(chunks=[b"abc"])
    record = await harness.claim()

    async def failing_renewal(
        record: RuntimeTransferRecord,
        credential: RuntimeRunnerCredential,
    ) -> RuntimeTransferRecord:
        del record, credential
        raise ConnectionError("coordination unavailable")

    monkeypatch.setattr(
        transfer_server_module,
        "STREAM_OWNER_RENEWAL_SECONDS",
        0,
    )
    monkeypatch.setattr(harness.servicer, "renew_stream_owner", failing_renewal)
    owner = asyncio.create_task(asyncio.sleep(3600))
    keeper = _StreamLeaseKeeper(
        servicer=harness.servicer,
        record=record,
        credential=RuntimeRunnerCredential("credential-1", "runtime-1", 1),
        owner_task=owner,
    )

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(owner, timeout=1)
    assert keeper.termination is _StreamTermination.FENCED
    await keeper.stop()


@pytest.mark.asyncio
async def test_upload_keeper_fence_at_deadline_maps_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A keeper fence cannot mask deadline authority on an active upload."""
    clock = _Clock(_NOW)
    harness = await _harness(
        chunks=[],
        direction=RuntimeTransferDirection.UPLOAD,
        clock=clock,
    )

    class _FencedKeeper:
        termination = _StreamTermination.FENCED

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(
        harness.servicer,
        "_start_lease_keeper",
        lambda record, credential: _FencedKeeper(),
    )

    async def cancel_at_deadline() -> AsyncIterator[pb.UploadTransferFrame]:
        yield pb.UploadTransferFrame(
            open=pb.UploadTransferOpen(identity=_upload_identity())
        )
        clock.now = _NOW + timedelta(minutes=5)
        raise asyncio.CancelledError

    with pytest.raises(_Abort) as error:
        await harness.servicer.UploadTransfer(cancel_at_deadline(), _Context())

    assert error.value.code is grpc.StatusCode.DEADLINE_EXCEEDED
    record = await harness.state.get("transfer-1")
    assert record is not None
    assert record.phase is RuntimeTransferPhase.TERMINAL
    assert record.terminal_outcome is RuntimeTransferOutcome.EXPIRED
    assert record.failure is RuntimeTransferFailure.EXPIRED


@pytest.mark.asyncio
async def test_post_completion_fence_deletes_exact_completed_attempt_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fence after multipart completion deletes the completed attempt object."""
    harness = await _harness(
        chunks=[],
        direction=RuntimeTransferDirection.UPLOAD,
    )

    async def fence_verification(*args: object, **kwargs: object) -> None:
        del args, kwargs

    monkeypatch.setattr(harness.state, "begin_verification", fence_verification)

    with pytest.raises(_Abort) as error:
        await harness.servicer.UploadTransfer(_upload_frames(b"abc"), _Context())

    assert error.value.code is grpc.StatusCode.FAILED_PRECONDITION
    assert harness.object_store.completed_parts is not None
    assert harness.object_store.delete_calls == 1
    assert harness.object_store.abort_calls == 0
    record = await harness.state.get("transfer-1")
    assert record is not None
    assert record.phase is RuntimeTransferPhase.TERMINAL
    assert record.cleanup_status is RuntimeTransferCleanupStatus.COMPLETE
    assert record.multipart_cleanup_handle is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "outcome", "failure"),
    [
        (
            RuntimeTransferCancellationReason.CALLER,
            RuntimeTransferOutcome.CANCELLED,
            RuntimeTransferFailure.CANCELLED,
        ),
        (
            RuntimeTransferCancellationReason.DEADLINE,
            RuntimeTransferOutcome.EXPIRED,
            RuntimeTransferFailure.EXPIRED,
        ),
        (
            RuntimeTransferCancellationReason.SUPERSEDED,
            RuntimeTransferOutcome.SUPERSEDED,
            RuntimeTransferFailure.FENCED,
        ),
    ],
)
async def test_post_publish_cancellation_deletes_object_before_success(
    monkeypatch: pytest.MonkeyPatch,
    reason: RuntimeTransferCancellationReason,
    outcome: RuntimeTransferOutcome,
    failure: RuntimeTransferFailure,
) -> None:
    """A cancellation winning the post-publish CAS cannot observe RPC success."""
    harness = await _harness(
        chunks=[],
        direction=RuntimeTransferDirection.UPLOAD,
    )

    async def cancel_before_upload_response(
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        accepted_runner_generation: int,
        claim_id: str,
        expected_revision: int,
        actual_size: int,
        actual_sha256: str,
    ) -> RuntimeTransferRecord | None:
        del (
            runtime_id,
            desired_generation,
            accepted_runner_generation,
            claim_id,
            expected_revision,
            actual_size,
            actual_sha256,
        )
        current = await harness.state.get(transfer_id)
        assert current is not None
        cancelled = await harness.state.request_cancellation(
            transfer_id,
            attempt_id=attempt_id,
            expected_revision=current.revision,
            reason=reason,
        )
        assert cancelled is not None
        return None

    monkeypatch.setattr(
        harness.state,
        "commit_upload_response",
        cancel_before_upload_response,
    )

    with pytest.raises(_Abort) as error:
        await harness.servicer.UploadTransfer(_upload_frames(b"abc"), _Context())

    expected_code = (
        grpc.StatusCode.DEADLINE_EXCEEDED
        if reason is RuntimeTransferCancellationReason.DEADLINE
        else grpc.StatusCode.FAILED_PRECONDITION
    )
    assert error.value.code is expected_code
    assert harness.object_store.delete_calls == 1
    record = await harness.state.get("transfer-1")
    assert record is not None
    assert record.phase is RuntimeTransferPhase.TERMINAL
    assert record.terminal_outcome is outcome
    assert record.failure is failure
    assert record.cleanup_status is RuntimeTransferCleanupStatus.COMPLETE
    assert record.completed_object_cleanup_required is False


@pytest.mark.asyncio
async def test_upload_deadline_crossing_during_completion_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An S3 completion returning at the deadline cannot become a fenced failure."""
    clock = _Clock(_NOW)
    harness = await _harness(
        chunks=[],
        direction=RuntimeTransferDirection.UPLOAD,
        clock=clock,
    )
    complete = harness.object_store.complete_multipart_upload

    async def complete_at_deadline(
        *,
        upload: S3MultipartUpload,
        completed_parts: tuple[S3CompletedPart, ...],
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject:
        verified = await complete(
            upload=upload,
            completed_parts=completed_parts,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )
        clock.now = _NOW + timedelta(minutes=5)
        return verified

    monkeypatch.setattr(
        harness.object_store,
        "complete_multipart_upload",
        complete_at_deadline,
    )

    with pytest.raises(_Abort) as error:
        await harness.servicer.UploadTransfer(_upload_frames(b"abc"), _Context())

    assert error.value.code is grpc.StatusCode.DEADLINE_EXCEEDED
    assert harness.object_store.delete_calls == 1
    record = await harness.state.get("transfer-1")
    assert record is not None
    assert record.phase is RuntimeTransferPhase.TERMINAL
    assert record.terminal_outcome is RuntimeTransferOutcome.EXPIRED
    assert record.failure is RuntimeTransferFailure.EXPIRED
    assert record.cleanup_status is RuntimeTransferCleanupStatus.COMPLETE
    assert record.completed_object_cleanup_required is False


class _Harness:
    def __init__(
        self,
        *,
        state: InMemoryRuntimeTransferStateStore,
        servicer: RuntimeRunnerTransferGrpcServicer,
        object_store: _ObjectStore,
    ) -> None:
        self.state = state
        self.servicer = servicer
        self.object_store = object_store

    async def claim(self) -> RuntimeTransferRecord:
        record = await self.state.get("transfer-1")
        assert record is not None
        claimed = await self.state.claim_stream(
            "transfer-1",
            attempt_id="attempt-1",
            runtime_id="runtime-1",
            desired_generation=1,
            accepted_runner_generation=1,
            expected_revision=record.revision,
            claim_id="existing-claim",
            owner_replica_id="other",
        )
        assert claimed is not None
        return claimed


async def _harness(
    *,
    chunks: list[bytes],
    size: int = 3,
    sha256: str | None = _DIGEST,
    direction: RuntimeTransferDirection = RuntimeTransferDirection.DOWNLOAD,
    desired_generation: int = 1,
    connection_registrations: int = 1,
    clock: Callable[[], datetime] | None = None,
) -> _Harness:
    clock = clock or (lambda: _NOW)
    state = InMemoryRuntimeTransferStateStore(
        config=_config(maximum_bytes=max(100, size)),
        clock=clock,
    )
    admitted = await state.admit(
        _admission(direction, size, sha256, desired_generation),
        lease_id="lease-1",
    )
    assert admitted is not None
    ready = await state.mark_ready(
        "transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=desired_generation,
        expected_revision=admitted.revision,
        object=RuntimeTransferObject("object-1", size, sha256),
    )
    assert ready is not None
    coordination = InMemoryRuntimeCoordinationStore()
    connection = None
    for index in range(connection_registrations):
        connection = await coordination.register_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id="runtime-1",
            connection_id=f"connection-{index + 1}",
            owner_replica_id=f"replica-{index + 1}",
            connected_at=_NOW,
            heartbeat_at=datetime.now(UTC),
            ttl_seconds=60,
            metadata={},
        )
    assert connection is not None
    bound = await state.bind_dispatch(
        "transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=desired_generation,
        accepted_runner_generation=connection.generation,
        expected_revision=ready.revision,
        dispatch_id="dispatch-1",
        dispatch_request_id="request-1",
    )
    assert bound is not None
    deliverable = await state.mark_dispatch_deliverable(
        "transfer-1",
        attempt_id="attempt-1",
        expected_revision=bound.revision,
        dispatch_id="dispatch-1",
        dispatch_request_id="request-1",
    )
    assert deliverable is not None
    object_store = _ObjectStore(chunks)
    terminal_sink = RuntimeTransferCoordinator(
        state_store=state,
        coordination_store=coordination,
        cleanup=None,
        clock=clock,
    )
    return _Harness(
        state=state,
        object_store=object_store,
        servicer=RuntimeRunnerTransferGrpcServicer(
            state_store=state,
            coordination_store=coordination,
            object_store=object_store,
            terminal_sink=terminal_sink,
            bucket="transfer-bucket",
            owner_replica_id="replica-1",
            runner_authenticator=_Authenticator(desired_generation=desired_generation),
            clock=clock,
        ),
    )


def _request(*, runner_generation: int = 1) -> pb.DownloadTransferRequest:
    return pb.DownloadTransferRequest(
        identity=pb.TransferIdentity(
            transfer_id="transfer-1",
            attempt_id="attempt-1",
            runtime_id="runtime-1",
            runner_generation=runner_generation,
        )
    )


async def _frames(
    *frames: pb.UploadTransferFrame,
) -> AsyncIterator[pb.UploadTransferFrame]:
    for frame in frames:
        yield frame


def _upload_identity() -> pb.TransferIdentity:
    return pb.TransferIdentity(
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        runner_generation=1,
    )


def _upload_frames(*chunks: bytes) -> AsyncIterator[pb.UploadTransferFrame]:
    data = b"".join(chunks)
    frames = [
        pb.UploadTransferFrame(open=pb.UploadTransferOpen(identity=_upload_identity()))
    ]
    offset = 0
    for chunk in chunks:
        frames.append(
            pb.UploadTransferFrame(chunk=pb.TransferChunk(offset=offset, data=chunk))
        )
        offset += len(chunk)
    frames.append(
        pb.UploadTransferFrame(
            complete=pb.UploadTransferComplete(
                actual_size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        )
    )
    return _frames(*frames)


def _admission(
    direction: RuntimeTransferDirection,
    size: int,
    sha256: str | None,
    desired_generation: int,
) -> RuntimeTransferAdmission:
    return RuntimeTransferAdmission(
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        direction=direction,
        runtime_id="runtime-1",
        desired_generation=desired_generation,
        operation_id="operation-1",
        session_id=None,
        agent_id=None,
        runtime_path="/workspace/file",
        overwrite=False,
        expected_size=size,
        expected_sha256=sha256,
        product_maximum_size=max(10, size),
        provider_maximum_size=max(10, size),
        deadline_at=_NOW + timedelta(minutes=5),
        source_expires_at=None,
        resource_class="file",
    )


def _config(*, maximum_bytes: int = 100) -> RuntimeTransferConfig:
    return RuntimeTransferConfig(
        per_runtime_attempts=4,
        per_runtime_bytes=maximum_bytes,
        deployment_attempts=4,
        deployment_bytes=maximum_bytes,
        admission_lease=timedelta(minutes=5),
        consumer_lease=timedelta(minutes=1),
        stream_lease=timedelta(seconds=30),
        terminal_ttl=timedelta(minutes=5),
        list_page_size=10,
    )
