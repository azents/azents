"""Bounded S3-backed Runtime Runner transfer service."""

# Protobuf generated modules expose dynamic message/RPC attributes.
# ruff: noqa: E501, B904

import asyncio
import hashlib
import secrets
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, suppress
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

import grpc
from azcommon.infra.s3.service import (
    S3CompletedPart,
    S3MultipartUpload,
    S3ObjectIdentity,
    S3TransferCancelled,
    S3TransferCleanupRequired,
    S3TransferObjectMetadata,
    S3VerifiedObject,
)
from azents_runtime_control.proto import runtime_runner_transfer_pb2 as pb
from azents_runtime_control.proto import runtime_runner_transfer_pb2_grpc as pb_grpc
from azents_runtime_control.transfer import (
    MAX_TRANSFER_CHUNK_BYTES,
    MULTIPART_PART_BYTES,
    STREAM_OWNER_RENEWAL_SECONDS,
)

from azents.core.runtime_runner_credential import RuntimeRunnerCredential
from azents.runtime.control_protocol.grpc.auth import (
    GrpcAbortContext,
    RuntimeRunnerCredentialAuthenticator,
    RuntimeRunnerCredentialGrpcAuth,
)
from azents.runtime.coordination.data import RuntimeConnectionKind
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.runtime.transfer.data import (
    RuntimeTransferCancellationReason,
    RuntimeTransferCleanupStatus,
    RuntimeTransferDirection,
    RuntimeTransferDispatchStatus,
    RuntimeTransferFailure,
    RuntimeTransferObject,
    RuntimeTransferOutcome,
    RuntimeTransferRecord,
    cancellation_settlement,
)
from azents.runtime.transfer.object_store import runtime_transfer_object_identity
from azents.runtime.transfer.store import RuntimeTransferStateStore

_DEFAULT_MAX_CONCURRENT_DOWNLOADS = 4
_DEFAULT_MAX_CONCURRENT_UPLOADS = 4
_MAX_MULTIPART_PARTS = 10_000
_PROGRESS_INTERVAL_SECONDS = 1
_PROGRESS_MINIMUM_BYTES = 1024 * 1024


class _TransferCancelled(RuntimeError):
    """Raised when durable or transport cancellation stops one stream."""

    def __init__(self, record: RuntimeTransferRecord) -> None:
        super().__init__("Transfer cancellation requested")
        self.record = record


class _TransferExpired(RuntimeError):
    """Raised when one transfer reaches its effective deadline."""

    def __init__(self, record: RuntimeTransferRecord) -> None:
        super().__init__("Transfer deadline expired")
        self.record = record


class _StreamTermination(StrEnum):
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FENCED = "fenced"


class _GrpcStreamContext(GrpcAbortContext, Protocol):
    """gRPC stream context methods needed by transfer state checks."""

    def cancelled(self) -> bool:
        """Return whether the active stream was cancelled."""
        ...


class _RoundRobinChunkScheduler:
    """Grant bounded chunk turns fairly across active transfer files."""

    def __init__(self, maximum_in_flight: int) -> None:
        """Initialize one process-local scheduler."""
        self._maximum_in_flight = maximum_in_flight
        self._waiting: deque[str] = deque()
        self._waiting_set: set[str] = set()
        self._active: set[str] = set()
        self._condition = asyncio.Condition()

    async def acquire(self, participant: str) -> None:
        """Wait until one file receives its next chunk-processing turn."""
        async with self._condition:
            if participant not in self._waiting_set and participant not in self._active:
                self._waiting.append(participant)
                self._waiting_set.add(participant)
            while participant in self._waiting_set and (
                not self._waiting
                or self._waiting[0] != participant
                or len(self._active) >= self._maximum_in_flight
            ):
                await self._condition.wait()
            if participant not in self._waiting_set:
                raise asyncio.CancelledError
            self._waiting.popleft()
            self._waiting_set.remove(participant)
            self._active.add(participant)

    async def release(self, participant: str, *, requeue: bool) -> None:
        """Finish one chunk turn and optionally queue the file's next chunk."""
        async with self._condition:
            self._active.discard(participant)
            if requeue and participant not in self._waiting_set:
                self._waiting.append(participant)
                self._waiting_set.add(participant)
            self._condition.notify_all()

    async def unregister(self, participant: str) -> None:
        """Remove a cancelled, failed, or completed file from future turns."""
        async with self._condition:
            self._active.discard(participant)
            if participant in self._waiting_set:
                self._waiting.remove(participant)
                self._waiting_set.remove(participant)
            self._condition.notify_all()


class _StreamLeaseKeeper:
    """Renew and independently fence one active stream owner."""

    def __init__(
        self,
        *,
        servicer: "RuntimeRunnerTransferGrpcServicer",
        record: RuntimeTransferRecord,
        credential: RuntimeRunnerCredential,
        owner_task: asyncio.Task[Any],
    ) -> None:
        self.servicer = servicer
        self.record = record
        self.credential = credential
        self.owner_task = owner_task
        self.termination: _StreamTermination | None = None
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(STREAM_OWNER_RENEWAL_SECONDS)
                try:
                    current = await self.servicer.renew_stream_owner(
                        self.record,
                        self.credential,
                    )
                except _TransferCancelled:
                    self.termination = _StreamTermination.CANCELLED
                except _TransferExpired:
                    self.termination = _StreamTermination.EXPIRED
                except Exception:
                    self.termination = _StreamTermination.FENCED
                else:
                    self.record = current
                    continue
                self.owner_task.cancel()
                return
        except asyncio.CancelledError:
            raise

    async def stop(self) -> None:
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.task


class RuntimeRunnerTransferObjectStore(Protocol):
    """Trusted object-store operations needed for bounded Runner transfers."""

    async def verify_transfer_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject:
        """Verify trusted object metadata before byte streaming."""
        ...

    def iter_chunks(
        self,
        identity: S3ObjectIdentity,
        *,
        maximum_chunk_size: int,
    ) -> AbstractAsyncContextManager[AsyncIterator[bytes]]:
        """Open an owned bounded object body iterator."""
        ...

    async def create_multipart_upload(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3MultipartUpload:
        """Create one immutable multipart upload."""
        ...

    async def create_preparation_multipart_upload(
        self,
        *,
        destination: S3ObjectIdentity,
        content_type: str | None,
    ) -> S3MultipartUpload:
        """Create one digest-unknown temporary multipart upload."""
        ...

    async def upload_part(
        self,
        *,
        upload: S3MultipartUpload,
        part_number: int,
        body: bytes,
    ) -> S3CompletedPart:
        """Upload one bounded multipart part."""
        ...

    async def complete_multipart_upload(
        self,
        *,
        upload: S3MultipartUpload,
        completed_parts: tuple[S3CompletedPart, ...],
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject:
        """Complete and verify one trusted multipart upload."""
        ...

    async def complete_preparation_multipart_upload(
        self,
        *,
        upload: S3MultipartUpload,
        completed_parts: tuple[S3CompletedPart, ...],
        expected_size: int,
    ) -> object:
        """Complete one digest-unknown temporary multipart upload."""
        ...

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
        """Copy one temporary object into a verified immutable object."""
        ...

    async def abort_multipart_upload(self, *, upload: S3MultipartUpload) -> None:
        """Abort one trusted multipart upload."""
        ...

    async def create_empty_immutable(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3VerifiedObject:
        """Create and verify one immutable empty transfer object."""
        ...

    async def delete_verified_transfer_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        """Delete one exact completed attempt object under trusted evidence."""
        ...

    async def delete(self, bucket: str, key: str) -> None:
        """Delete one exact temporary object."""
        ...


class RuntimeTransferTerminalSink(Protocol):
    """Settle and correlate one Control-authoritative transfer terminal."""

    async def settle_terminal(
        self,
        record: RuntimeTransferRecord,
        *,
        outcome: RuntimeTransferOutcome,
        failure: RuntimeTransferFailure,
        cleanup_completed: bool,
    ) -> RuntimeTransferRecord | None:
        """Settle one exact attempt and append its initiating operation final."""
        ...


class RuntimeRunnerTransferGrpcServicer(pb_grpc.RuntimeRunnerTransferServicer):
    """Authenticate and stream state-owned objects to one Runner."""

    def __init__(
        self,
        *,
        state_store: RuntimeTransferStateStore,
        coordination_store: RuntimeCoordinationStore,
        object_store: RuntimeRunnerTransferObjectStore,
        terminal_sink: RuntimeTransferTerminalSink,
        bucket: str,
        owner_replica_id: str,
        runner_authenticator: RuntimeRunnerCredentialAuthenticator,
        clock: Callable[[], datetime],
        max_concurrent_downloads: int = _DEFAULT_MAX_CONCURRENT_DOWNLOADS,
        max_concurrent_uploads: int = _DEFAULT_MAX_CONCURRENT_UPLOADS,
        object_prefix: str = "",
        maximum_chunk_bytes: int = MAX_TRANSFER_CHUNK_BYTES,
        multipart_part_bytes: int = MULTIPART_PART_BYTES,
    ) -> None:
        """Initialize state-owned transfer dependencies.

        :param state_store: authoritative transfer state
        :param coordination_store: current Runner generation registry
        :param object_store: trusted object-store service
        :param terminal_sink: authoritative terminal settlement and correlation
        :param bucket: trusted object bucket selected by Control
        :param object_prefix: internal transfer-object S3 key namespace
        :param owner_replica_id: Control replica owning stream claims
        :param runner_authenticator: durable Runner credential authority
        :param clock: timezone-aware clock for deadlines and lease renewal
        :param max_concurrent_downloads: per-replica bounded chunk I/O capacity
        :param max_concurrent_uploads: per-replica bounded upload capacity
        :param maximum_chunk_bytes: maximum protobuf transfer payload size
        :param multipart_part_bytes: bounded S3 multipart part aggregation size
        """
        if not bucket:
            raise ValueError("Runner transfer bucket is required")
        if max_concurrent_downloads <= 0:
            raise ValueError("max_concurrent_downloads must be positive")
        if max_concurrent_uploads <= 0:
            raise ValueError("max_concurrent_uploads must be positive")
        if not 0 < maximum_chunk_bytes <= MAX_TRANSFER_CHUNK_BYTES:
            raise ValueError("maximum_chunk_bytes exceeds the protocol bound")
        if multipart_part_bytes < MULTIPART_PART_BYTES:
            raise ValueError("multipart_part_bytes must satisfy the S3 part minimum")
        self._state_store = state_store
        self._coordination_store = coordination_store
        self._object_store = object_store
        self._terminal_sink = terminal_sink
        self._bucket = bucket
        self._object_prefix = object_prefix
        self._owner_replica_id = owner_replica_id
        self._runner_authenticator = runner_authenticator
        self._auth = RuntimeRunnerCredentialGrpcAuth(runner_authenticator)
        self._clock = clock
        self._download_chunks = _RoundRobinChunkScheduler(max_concurrent_downloads)
        self._uploads = asyncio.Semaphore(max_concurrent_uploads)
        self._maximum_chunk_bytes = maximum_chunk_bytes
        self._multipart_part_bytes = multipart_part_bytes

    async def DownloadTransfer(
        self,
        request: pb.DownloadTransferRequest,
        context: grpc.aio.ServicerContext[
            pb.DownloadTransferRequest,
            pb.DownloadTransferFrame,
        ],
    ) -> AsyncIterator[pb.DownloadTransferFrame]:
        """Authenticate, fence, claim, and bounded-stream one download object."""
        credential = await self._auth.authenticate(context)
        if not await self._runner_authenticator.authorize_runner(credential):
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "Runner credential is no longer authorized",
            )
            raise AssertionError("unreachable")
        record = await self._authorize_download(request, credential, context)
        participant = _scheduler_participant(record)
        claimed: RuntimeTransferRecord | None = None
        latest: RuntimeTransferRecord | None = None
        keeper: _StreamLeaseKeeper | None = None
        chunk_turn_held = False
        try:
            claimed = await self._state_store.claim_stream(
                record.admission.transfer_id,
                attempt_id=record.admission.attempt_id,
                runtime_id=record.admission.runtime_id,
                desired_generation=record.admission.desired_generation,
                accepted_runner_generation=record.accepted_runner_generation or 0,
                expected_revision=record.revision,
                claim_id=_claim_id(),
                owner_replica_id=self._owner_replica_id,
            )
            if claimed is None:
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Transfer stream claim is unavailable",
                )
                raise AssertionError("unreachable")
            latest = claimed
            keeper = self._start_lease_keeper(claimed, credential)
            if claimed.object is None:
                await self._fail(claimed)
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Transfer object is unavailable",
                )
                raise AssertionError("unreachable")
            transfer_object = claimed.object
            if transfer_object.sha256 is None:
                await self._fail(claimed)
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Transfer object manifest is unavailable",
                )
                raise AssertionError("unreachable")
            identity = self._object_identity(transfer_object.key)
            try:
                await self._object_store.verify_transfer_object(
                    identity=identity,
                    expected_size=transfer_object.size,
                    expected_sha256=transfer_object.sha256,
                )
            except FileNotFoundError, ValueError:
                await self._fail(claimed)
                await context.abort(
                    grpc.StatusCode.DATA_LOSS, "Transfer object verification failed"
                )
                raise AssertionError("unreachable")
            offset = 0
            digest = hashlib.sha256()
            async with self._object_store.iter_chunks(
                identity,
                maximum_chunk_size=self._maximum_chunk_bytes,
            ) as chunks:
                async for chunk in chunks:
                    await self._download_chunks.acquire(participant)
                    chunk_turn_held = True
                    try:
                        latest = await self._check_stream(latest, credential, context)
                        if not chunk or len(chunk) > self._maximum_chunk_bytes:
                            await self._fail(latest)
                            await context.abort(
                                grpc.StatusCode.DATA_LOSS,
                                "Transfer object stream is invalid",
                            )
                            raise AssertionError("unreachable")
                        digest.update(chunk)
                        offset += len(chunk)
                        if offset > latest.admission.expected_size:
                            await self._fail(latest)
                            await context.abort(
                                grpc.StatusCode.DATA_LOSS,
                                "Transfer object exceeds expected size",
                            )
                            raise AssertionError("unreachable")
                        latest = await self._record_progress(
                            latest,
                            offset,
                            context,
                            force=offset == latest.admission.expected_size,
                        )
                    except asyncio.CancelledError:
                        await self._download_chunks.release(
                            participant,
                            requeue=False,
                        )
                        chunk_turn_held = False
                        raise
                    except Exception:
                        await self._download_chunks.release(
                            participant,
                            requeue=False,
                        )
                        chunk_turn_held = False
                        raise
                    await self._download_chunks.release(participant, requeue=True)
                    chunk_turn_held = False
                    yield pb.DownloadTransferFrame(
                        chunk=pb.TransferChunk(offset=offset - len(chunk), data=chunk)
                    )
            if (
                offset != latest.admission.expected_size
                or digest.hexdigest() != transfer_object.sha256
            ):
                await self._fail(latest)
                await context.abort(
                    grpc.StatusCode.DATA_LOSS, "Transfer object manifest does not match"
                )
                raise AssertionError("unreachable")
            await keeper.stop()
            keeper = None
            verifying = await self._state_store.begin_verification(
                latest.admission.transfer_id,
                attempt_id=latest.admission.attempt_id,
                runtime_id=latest.admission.runtime_id,
                desired_generation=latest.admission.desired_generation,
                accepted_runner_generation=latest.accepted_runner_generation or 0,
                claim_id=latest.stream_claim_id or "",
                expected_revision=latest.revision,
            )
            if verifying is None:
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Transfer completion is fenced",
                )
                raise AssertionError("unreachable")
            latest = verifying
            yield pb.DownloadTransferFrame(
                complete=pb.DownloadTransferComplete(
                    actual_size=offset, sha256=digest.hexdigest()
                )
            )
        except _TransferCancelled as exc:
            await self._abort_for_cancellation(exc.record, context)
            raise AssertionError("unreachable")
        except _TransferExpired as exc:
            await self._fail(
                exc.record,
                outcome=RuntimeTransferOutcome.EXPIRED,
                failure=RuntimeTransferFailure.EXPIRED,
            )
            await context.abort(
                grpc.StatusCode.DEADLINE_EXCEEDED,
                "Transfer deadline expired",
            )
            raise AssertionError("unreachable")
        except asyncio.CancelledError:
            if latest is not None:
                current = await self._state_store.get(latest.admission.transfer_id)
                latest = current or latest
                if (
                    keeper is not None
                    and keeper.termination is _StreamTermination.EXPIRED
                ):
                    await self._fail(
                        latest,
                        outcome=RuntimeTransferOutcome.EXPIRED,
                        failure=RuntimeTransferFailure.EXPIRED,
                    )
                    await context.abort(
                        grpc.StatusCode.DEADLINE_EXCEEDED,
                        "Transfer deadline expired",
                    )
                    raise AssertionError("unreachable")
                if (
                    keeper is not None
                    and keeper.termination is _StreamTermination.FENCED
                ):
                    settled = await self._fail(latest)
                    if (
                        settled is not None
                        and settled.terminal_outcome is RuntimeTransferOutcome.EXPIRED
                    ):
                        await context.abort(
                            grpc.StatusCode.DEADLINE_EXCEEDED,
                            "Transfer deadline expired",
                        )
                    await context.abort(
                        grpc.StatusCode.FAILED_PRECONDITION,
                        "Transfer stream is fenced",
                    )
                    raise AssertionError("unreachable")
                await self._fail(latest, cancelled=True)
            raise
        except Exception as exc:
            if _is_abort_exception(exc):
                raise
            if latest is not None:
                settled = await self._fail(latest)
                if (
                    settled is not None
                    and settled.terminal_outcome is RuntimeTransferOutcome.EXPIRED
                ):
                    await context.abort(
                        grpc.StatusCode.DEADLINE_EXCEEDED,
                        "Transfer deadline expired",
                    )
            await context.abort(grpc.StatusCode.INTERNAL, "Transfer stream failed")
            raise AssertionError("unreachable")
        finally:
            if keeper is not None:
                await keeper.stop()
            if chunk_turn_held:
                await self._download_chunks.release(participant, requeue=False)
            await self._download_chunks.unregister(participant)

    async def UploadTransfer(
        self,
        request_iterator: AsyncIterator[pb.UploadTransferFrame],
        context: grpc.aio.ServicerContext[
            pb.UploadTransferFrame,
            pb.UploadTransferResult,
        ],
    ) -> pb.UploadTransferResult:
        """Receive, verify, and publish one bounded Runner upload."""
        credential = await self._auth.authenticate(context)
        try:
            first = await anext(request_iterator)
        except StopAsyncIteration:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Upload transfer must begin with an opening frame",
            )
            raise AssertionError("unreachable")
        if first.WhichOneof("payload") != "open" or not first.open.HasField("identity"):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Upload transfer must begin with an opening frame",
            )
            raise AssertionError("unreachable")
        if not await self._runner_authenticator.authorize_runner(credential):
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "Runner credential is no longer authorized",
            )
            raise AssertionError("unreachable")
        record = await self._authorize_upload(first.open.identity, credential, context)
        if self._uploads.locked():
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Runner upload capacity is exhausted",
            )
            raise AssertionError("unreachable")
        await self._uploads.acquire()
        latest: RuntimeTransferRecord | None = None
        upload: S3MultipartUpload | None = None
        multipart_cleanup_required = False
        completed_object_cleanup_required = False
        identity: S3ObjectIdentity | None = None
        keeper: _StreamLeaseKeeper | None = None
        try:
            latest = await self._state_store.claim_stream(
                record.admission.transfer_id,
                attempt_id=record.admission.attempt_id,
                runtime_id=record.admission.runtime_id,
                desired_generation=record.admission.desired_generation,
                accepted_runner_generation=record.accepted_runner_generation or 0,
                expected_revision=record.revision,
                claim_id=_claim_id(),
                owner_replica_id=self._owner_replica_id,
            )
            if latest is None:
                await context.abort(
                    grpc.StatusCode.ALREADY_EXISTS,
                    "Transfer stream claim is unavailable",
                )
                raise AssertionError("unreachable")
            keeper = self._start_lease_keeper(latest, credential)
            if latest.object is None:
                await self._fail(latest)
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Transfer object is unavailable",
                )
                raise AssertionError("unreachable")
            transfer_object = latest.object
            if transfer_object.size != latest.admission.expected_size:
                await self._fail(latest)
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Transfer object manifest is unavailable",
                )
                raise AssertionError("unreachable")
            if (
                _multipart_part_count(transfer_object.size, self._multipart_part_bytes)
                > _MAX_MULTIPART_PARTS
            ):
                await self._fail(latest)
                await context.abort(
                    grpc.StatusCode.RESOURCE_EXHAUSTED,
                    "Transfer exceeds multipart part capacity",
                )
                raise AssertionError("unreachable")
            identity = self._object_identity(transfer_object.key)
            verified_object_handle = (
                transfer_object.key
                if transfer_object.sha256 is not None
                else _verified_upload_object_handle(transfer_object.key)
            )
            verified_identity = self._object_identity(verified_object_handle)
            offset = 0
            digest = hashlib.sha256()
            parts: list[S3CompletedPart] = []
            buffer = bytearray()
            saw_completion = False
            async for frame in request_iterator:
                latest = await self._check_stream(latest, credential, context)
                if saw_completion:
                    await self._fail(latest, failure=RuntimeTransferFailure.INTEGRITY)
                    await context.abort(
                        grpc.StatusCode.FAILED_PRECONDITION,
                        "Upload transfer must not contain trailing frames",
                    )
                    raise AssertionError("unreachable")
                payload = frame.WhichOneof("payload")
                if payload == "chunk":
                    chunk = frame.chunk
                    data = chunk.data
                    if not data:
                        await self._fail(
                            latest, failure=RuntimeTransferFailure.INTEGRITY
                        )
                        await context.abort(
                            grpc.StatusCode.FAILED_PRECONDITION,
                            "Upload transfer chunks must not be empty",
                        )
                        raise AssertionError("unreachable")
                    if len(data) > self._maximum_chunk_bytes:
                        await self._fail(latest)
                        await context.abort(
                            grpc.StatusCode.RESOURCE_EXHAUSTED,
                            "Upload transfer chunk exceeds capacity",
                        )
                        raise AssertionError("unreachable")
                    if chunk.offset != offset:
                        await self._fail(
                            latest, failure=RuntimeTransferFailure.INTEGRITY
                        )
                        await context.abort(
                            grpc.StatusCode.DATA_LOSS,
                            "Upload transfer chunk offset does not match",
                        )
                        raise AssertionError("unreachable")
                    next_offset = offset + len(data)
                    if next_offset > transfer_object.size:
                        await self._fail(latest)
                        await context.abort(
                            grpc.StatusCode.RESOURCE_EXHAUSTED,
                            "Upload transfer exceeds expected size",
                        )
                        raise AssertionError("unreachable")
                    if transfer_object.size > 0 and upload is None:
                        if transfer_object.sha256 is None:
                            upload = await self._object_store.create_preparation_multipart_upload(
                                destination=identity,
                                content_type=None,
                            )
                        else:
                            upload = await self._object_store.create_multipart_upload(
                                destination=identity,
                                transfer_metadata=S3TransferObjectMetadata(
                                    sha256=transfer_object.sha256,
                                    content_type=None,
                                ),
                            )
                        handled = await self._state_store.record_multipart_cleanup_handle(
                            latest.admission.transfer_id,
                            attempt_id=latest.admission.attempt_id,
                            accepted_runner_generation=latest.accepted_runner_generation
                            or 0,
                            expected_revision=latest.revision,
                            claim_id=latest.stream_claim_id or "",
                            owner_replica_id=self._owner_replica_id,
                            cleanup_handle=upload.upload_id,
                        )
                        if handled is None:
                            await self._object_store.abort_multipart_upload(
                                upload=upload
                            )
                            upload = None
                            await self._fail(latest)
                            await context.abort(
                                grpc.StatusCode.FAILED_PRECONDITION,
                                "Transfer stream is fenced",
                            )
                            raise AssertionError("unreachable")
                        latest = handled
                        pending = await self._state_store.record_cleanup(
                            latest.admission.transfer_id,
                            attempt_id=latest.admission.attempt_id,
                            expected_revision=latest.revision,
                            status=RuntimeTransferCleanupStatus.PENDING,
                        )
                        if pending is None:
                            await self._abort_upload(latest, upload)
                            await context.abort(
                                grpc.StatusCode.FAILED_PRECONDITION,
                                "Transfer cleanup state is fenced",
                            )
                            raise AssertionError("unreachable")
                        latest = pending
                        multipart_cleanup_required = True
                    digest.update(data)
                    offset = next_offset
                    buffer.extend(data)
                    if len(buffer) >= self._multipart_part_bytes:
                        latest = await self._upload_part(
                            latest,
                            credential,
                            context,
                            upload,
                            parts,
                            bytes(buffer[: self._multipart_part_bytes]),
                        )
                        del buffer[: self._multipart_part_bytes]
                    latest = await self._record_progress(
                        latest,
                        offset,
                        context,
                        force=offset == transfer_object.size,
                    )
                    continue
                if payload == "complete":
                    if saw_completion or not frame.complete.HasField("actual_size"):
                        await self._fail(
                            latest, failure=RuntimeTransferFailure.INTEGRITY
                        )
                        await context.abort(
                            grpc.StatusCode.FAILED_PRECONDITION,
                            "Upload transfer completion is invalid",
                        )
                        raise AssertionError("unreachable")
                    saw_completion = True
                    completion = frame.complete
                    if (
                        completion.actual_size != offset
                        or completion.sha256 != digest.hexdigest()
                        or offset != transfer_object.size
                        or (
                            transfer_object.sha256 is not None
                            and digest.hexdigest() != transfer_object.sha256
                        )
                    ):
                        await self._fail(
                            latest, failure=RuntimeTransferFailure.INTEGRITY
                        )
                        await context.abort(
                            grpc.StatusCode.DATA_LOSS,
                            "Upload transfer manifest does not match",
                        )
                        raise AssertionError("unreachable")
                    continue
                await self._fail(latest, failure=RuntimeTransferFailure.INTEGRITY)
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Upload transfer frame sequence is invalid",
                )
                raise AssertionError("unreachable")
            if not saw_completion:
                await self._fail(latest, failure=RuntimeTransferFailure.INTEGRITY)
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Upload transfer completion is required",
                )
                raise AssertionError("unreachable")
            latest = await self._complete_and_commit_upload(
                latest,
                credential=credential,
                context=context,
                keeper=keeper,
                transfer_object=transfer_object,
                staging_identity=identity,
                verified_identity=verified_identity,
                verified_object_handle=verified_object_handle,
                upload=upload,
                parts=parts,
                final_buffer=bytes(buffer),
                actual_size=offset,
                actual_sha256=digest.hexdigest(),
            )
            keeper = None
            multipart_cleanup_required = False
            completed_object_cleanup_required = False
            return pb.UploadTransferResult(
                status=pb.UPLOAD_TRANSFER_STATUS_SUCCEEDED,
                actual_size=offset,
                sha256=digest.hexdigest(),
            )
        except _TransferCancelled as exc:
            latest = exc.record
            if identity is not None:
                latest = await self._cleanup_upload(
                    latest,
                    upload=upload,
                    multipart_cleanup_required=multipart_cleanup_required,
                    completed_object_cleanup_required=(
                        completed_object_cleanup_required
                    ),
                    identity=identity,
                )
            await self._abort_for_cancellation(latest, context)
            raise AssertionError("unreachable")
        except _TransferExpired as exc:
            latest = exc.record
            if identity is not None:
                latest = await self._cleanup_upload(
                    latest,
                    upload=upload,
                    multipart_cleanup_required=multipart_cleanup_required,
                    completed_object_cleanup_required=(
                        completed_object_cleanup_required
                    ),
                    identity=identity,
                )
            await self._fail(
                latest,
                outcome=RuntimeTransferOutcome.EXPIRED,
                failure=RuntimeTransferFailure.EXPIRED,
            )
            await context.abort(
                grpc.StatusCode.DEADLINE_EXCEEDED,
                "Transfer deadline expired",
            )
            raise AssertionError("unreachable")
        except asyncio.CancelledError as exc:
            if isinstance(exc, S3TransferCancelled):
                multipart_cleanup_required = exc.multipart_cleanup_required
                completed_object_cleanup_required = (
                    exc.completed_object_cleanup_required
                )
            if latest is not None:
                current = await self._state_store.get(latest.admission.transfer_id)
                latest = current or latest
                if latest.upload_response_committed_at is not None:
                    raise
                if identity is not None:
                    latest = await self._cleanup_upload(
                        latest,
                        upload=upload,
                        multipart_cleanup_required=multipart_cleanup_required,
                        completed_object_cleanup_required=(
                            completed_object_cleanup_required
                        ),
                        identity=identity,
                    )
                if (
                    keeper is not None
                    and keeper.termination is _StreamTermination.EXPIRED
                ):
                    await self._fail(
                        latest,
                        outcome=RuntimeTransferOutcome.EXPIRED,
                        failure=RuntimeTransferFailure.EXPIRED,
                    )
                    await context.abort(
                        grpc.StatusCode.DEADLINE_EXCEEDED,
                        "Transfer deadline expired",
                    )
                    raise AssertionError("unreachable")
                if (
                    keeper is not None
                    and keeper.termination is _StreamTermination.FENCED
                ):
                    settled = await self._fail(latest)
                    if (
                        settled is not None
                        and settled.terminal_outcome is RuntimeTransferOutcome.EXPIRED
                    ):
                        await context.abort(
                            grpc.StatusCode.DEADLINE_EXCEEDED,
                            "Transfer deadline expired",
                        )
                    await context.abort(
                        grpc.StatusCode.FAILED_PRECONDITION,
                        "Transfer stream is fenced",
                    )
                    raise AssertionError("unreachable")
                await self._fail(latest, cancelled=True)
            raise
        except Exception as exc:
            if _is_abort_exception(exc):
                if latest is not None and identity is not None:
                    latest = await self._cleanup_upload(
                        latest,
                        upload=upload,
                        multipart_cleanup_required=multipart_cleanup_required,
                        completed_object_cleanup_required=(
                            completed_object_cleanup_required
                        ),
                        identity=identity,
                    )
                    settled = await self._settle_lost_upload_authority(latest)
                    if (
                        settled is not None
                        and settled.terminal_outcome is RuntimeTransferOutcome.EXPIRED
                    ):
                        await context.abort(
                            grpc.StatusCode.DEADLINE_EXCEEDED,
                            "Transfer deadline expired",
                        )
                raise
            if latest is not None:
                if identity is not None:
                    latest = await self._cleanup_upload(
                        latest,
                        upload=upload,
                        multipart_cleanup_required=multipart_cleanup_required,
                        completed_object_cleanup_required=(
                            completed_object_cleanup_required
                        ),
                        identity=identity,
                    )
                settled = await self._fail(latest)
                if (
                    settled is not None
                    and settled.terminal_outcome is RuntimeTransferOutcome.EXPIRED
                ):
                    await context.abort(
                        grpc.StatusCode.DEADLINE_EXCEEDED,
                        "Transfer deadline expired",
                    )
            await context.abort(grpc.StatusCode.INTERNAL, "Transfer stream failed")
            raise AssertionError("unreachable")
        finally:
            if keeper is not None:
                await keeper.stop()
            self._uploads.release()

    async def _authorize_download(
        self,
        request: pb.DownloadTransferRequest,
        credential: RuntimeRunnerCredential,
        context: GrpcAbortContext,
    ) -> RuntimeTransferRecord:
        if not request.HasField("identity"):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, "Transfer identity is required"
            )
            raise AssertionError("unreachable")
        identity = request.identity
        if not _valid_identity(identity):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, "Transfer identity is invalid"
            )
            raise AssertionError("unreachable")
        if identity.runtime_id != credential.runtime_id:
            await context.abort(
                grpc.StatusCode.PERMISSION_DENIED, "Transfer identity is not authorized"
            )
            raise AssertionError("unreachable")
        record = await self._state_store.get(identity.transfer_id)
        if (
            record is not None
            and record.admission.attempt_id == identity.attempt_id
            and record.admission.runtime_id == identity.runtime_id
            and record.admission.desired_generation == credential.desired_generation
            and record.admission.direction is RuntimeTransferDirection.DOWNLOAD
            and record.accepted_runner_generation == identity.runner_generation
            and _expired(record, self._now())
        ):
            await self._fail(
                record,
                outcome=RuntimeTransferOutcome.EXPIRED,
                failure=RuntimeTransferFailure.EXPIRED,
            )
            await context.abort(
                grpc.StatusCode.DEADLINE_EXCEEDED,
                "Transfer deadline expired",
            )
            raise AssertionError("unreachable")
        if (
            record is None
            or record.admission.attempt_id != identity.attempt_id
            or record.admission.runtime_id != identity.runtime_id
            or record.admission.desired_generation != credential.desired_generation
            or record.admission.direction is not RuntimeTransferDirection.DOWNLOAD
            or record.phase.value != "ready"
            or record.dispatch_status
            not in {
                RuntimeTransferDispatchStatus.DELIVERABLE,
                RuntimeTransferDispatchStatus.ENQUEUED,
            }
            or record.accepted_runner_generation != identity.runner_generation
            or _expired(record, self._now())
        ):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, "Transfer is unavailable"
            )
            raise AssertionError("unreachable")
        connection = await self._coordination_store.get_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=identity.runtime_id,
        )
        if connection is None or connection.generation != identity.runner_generation:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, "Runner generation is unavailable"
            )
            raise AssertionError("unreachable")
        return record

    async def _authorize_upload(
        self,
        identity: pb.TransferIdentity,
        credential: RuntimeRunnerCredential,
        context: GrpcAbortContext,
    ) -> RuntimeTransferRecord:
        """Authorize one first-frame upload identity before state mutation."""
        if not _valid_identity(identity):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, "Transfer identity is invalid"
            )
            raise AssertionError("unreachable")
        if identity.runtime_id != credential.runtime_id:
            await context.abort(
                grpc.StatusCode.PERMISSION_DENIED, "Transfer identity is not authorized"
            )
            raise AssertionError("unreachable")
        record = await self._state_store.get(identity.transfer_id)
        if (
            record is not None
            and record.admission.attempt_id == identity.attempt_id
            and record.admission.runtime_id == identity.runtime_id
            and record.admission.desired_generation == credential.desired_generation
            and record.admission.direction is RuntimeTransferDirection.UPLOAD
            and record.accepted_runner_generation == identity.runner_generation
            and _expired(record, self._now())
        ):
            await self._fail(
                record,
                outcome=RuntimeTransferOutcome.EXPIRED,
                failure=RuntimeTransferFailure.EXPIRED,
            )
            await context.abort(
                grpc.StatusCode.DEADLINE_EXCEEDED,
                "Transfer deadline expired",
            )
            raise AssertionError("unreachable")
        if (
            record is None
            or record.admission.attempt_id != identity.attempt_id
            or record.admission.runtime_id != identity.runtime_id
            or record.admission.desired_generation != credential.desired_generation
            or record.admission.direction is not RuntimeTransferDirection.UPLOAD
            or record.phase.value not in {"ready", "streaming"}
            or record.dispatch_status
            not in {
                RuntimeTransferDispatchStatus.DELIVERABLE,
                RuntimeTransferDispatchStatus.ENQUEUED,
            }
            or record.accepted_runner_generation != identity.runner_generation
            or _expired(record, self._now())
        ):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, "Transfer is unavailable"
            )
            raise AssertionError("unreachable")
        connection = await self._coordination_store.get_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=identity.runtime_id,
        )
        if connection is None or connection.generation != identity.runner_generation:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, "Runner generation is unavailable"
            )
            raise AssertionError("unreachable")
        return record

    async def _check_stream(
        self,
        record: RuntimeTransferRecord,
        credential: RuntimeRunnerCredential,
        context: _GrpcStreamContext,
    ) -> RuntimeTransferRecord:
        if context.cancelled():
            current = await self._state_store.get(record.admission.transfer_id)
            raise _TransferCancelled(current or record)
        if not await self._runner_authenticator.authorize_runner(credential):
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED, "Runner transfer authorization expired"
            )
            raise AssertionError("unreachable")
        current = await self._state_store.get(record.admission.transfer_id)
        connection = await self._coordination_store.get_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=record.admission.runtime_id,
        )
        if (
            current is not None
            and current.admission.attempt_id == record.admission.attempt_id
            and current.cancellation_requested_at is not None
        ):
            if (
                current.cancellation_reason
                is RuntimeTransferCancellationReason.DEADLINE
            ):
                raise _TransferExpired(current)
            raise _TransferCancelled(current)
        if current is not None and _expired(current, self._now()):
            raise _TransferExpired(current)
        if (
            current is None
            or current.revision != record.revision
            or current.stream_claim_id != record.stream_claim_id
            or current.stream_owner_replica_id != self._owner_replica_id
            or current.admission.desired_generation != credential.desired_generation
            or current.accepted_runner_generation != record.accepted_runner_generation
            or connection is None
            or connection.generation != current.accepted_runner_generation
        ):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, "Transfer stream is fenced"
            )
            raise AssertionError("unreachable")
        return current

    async def _record_progress(
        self,
        record: RuntimeTransferRecord,
        offset: int,
        context: GrpcAbortContext,
        *,
        force: bool,
    ) -> RuntimeTransferRecord:
        now = self._now()
        progress = record.progress
        byte_threshold = max(
            _PROGRESS_MINIMUM_BYTES,
            self._maximum_chunk_bytes * 4,
        )
        previous_bytes = 0 if progress is None else progress.bytes_transferred
        previous_at = record.updated_at if progress is None else progress.observed_at
        if (
            not force
            and offset - previous_bytes < byte_threshold
            and (now - previous_at).total_seconds() < _PROGRESS_INTERVAL_SECONDS
        ):
            return record
        progressed = await self._state_store.record_progress(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            runtime_id=record.admission.runtime_id,
            desired_generation=record.admission.desired_generation,
            accepted_runner_generation=record.accepted_runner_generation or 0,
            claim_id=record.stream_claim_id or "",
            expected_revision=record.revision,
            bytes_transferred=offset,
        )
        if progressed is None:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, "Transfer stream is fenced"
            )
            raise AssertionError("unreachable")
        return progressed

    def _start_lease_keeper(
        self,
        record: RuntimeTransferRecord,
        credential: RuntimeRunnerCredential,
    ) -> _StreamLeaseKeeper:
        owner_task = asyncio.current_task()
        if owner_task is None:
            raise RuntimeError("Runner transfer task is unavailable")
        return _StreamLeaseKeeper(
            servicer=self,
            record=record,
            credential=credential,
            owner_task=owner_task,
        )

    async def renew_stream_owner(
        self,
        record: RuntimeTransferRecord,
        credential: RuntimeRunnerCredential,
    ) -> RuntimeTransferRecord:
        if not await self._runner_authenticator.authorize_runner(credential):
            raise RuntimeError("Runner transfer authorization expired")
        current = await self._state_store.get(record.admission.transfer_id)
        if (
            current is not None
            and current.admission.attempt_id == record.admission.attempt_id
            and current.cancellation_requested_at is not None
        ):
            if (
                current.cancellation_reason
                is RuntimeTransferCancellationReason.DEADLINE
            ):
                raise _TransferExpired(current)
            raise _TransferCancelled(current)
        if current is not None and _expired(current, self._now()):
            raise _TransferExpired(current)
        connection = await self._coordination_store.get_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=record.admission.runtime_id,
        )
        if (
            current is None
            or current.phase.value != "streaming"
            or current.stream_claim_id != record.stream_claim_id
            or current.stream_owner_replica_id != self._owner_replica_id
            or current.admission.desired_generation != credential.desired_generation
            or current.accepted_runner_generation != record.accepted_runner_generation
            or connection is None
            or connection.generation != current.accepted_runner_generation
        ):
            raise RuntimeError("Transfer stream is fenced")
        renewed = await self._state_store.renew_stream_lease(
            current.admission.transfer_id,
            attempt_id=current.admission.attempt_id,
            accepted_runner_generation=current.accepted_runner_generation or 0,
            expected_revision=current.revision,
            claim_id=current.stream_claim_id or "",
            owner_replica_id=self._owner_replica_id,
        )
        if renewed is None:
            raise RuntimeError("Transfer stream lease is fenced")
        return renewed

    async def _complete_and_commit_upload(
        self,
        record: RuntimeTransferRecord,
        *,
        credential: RuntimeRunnerCredential,
        context: _GrpcStreamContext,
        keeper: _StreamLeaseKeeper,
        transfer_object: RuntimeTransferObject,
        staging_identity: S3ObjectIdentity,
        verified_identity: S3ObjectIdentity,
        verified_object_handle: str,
        upload: S3MultipartUpload | None,
        parts: list[S3CompletedPart],
        final_buffer: bytes,
        actual_size: int,
        actual_sha256: str,
    ) -> RuntimeTransferRecord:
        """Persist cleanup authority, complete S3, and commit upload success."""
        latest = await self._check_stream(record, credential, context)
        if transfer_object.size > 0:
            if upload is None:
                await self._fail(latest)
                await context.abort(
                    grpc.StatusCode.INTERNAL,
                    "Upload transfer stream is invalid",
                )
                raise AssertionError("unreachable")
            if final_buffer:
                latest = await self._upload_part(
                    latest,
                    credential,
                    context,
                    upload,
                    parts,
                    final_buffer,
                )
            latest = await self._check_stream(latest, credential, context)
        responsibility = await self._state_store.record_completed_object_cleanup(
            latest.admission.transfer_id,
            attempt_id=latest.admission.attempt_id,
            expected_revision=latest.revision,
            status=RuntimeTransferCleanupStatus.RETRYABLE_FAILURE,
            multipart_cleanup_required=upload is not None,
            completed_object_cleanup_required=True,
        )
        if responsibility is None:
            current = await self._state_store.get(latest.admission.transfer_id)
            cleaned = await self._cleanup_upload(
                current or latest,
                upload=upload,
                multipart_cleanup_required=upload is not None,
                completed_object_cleanup_required=False,
                identity=staging_identity,
            )
            await self._settle_lost_upload_authority(cleaned)
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Transfer completion cleanup authority is fenced",
            )
            raise AssertionError("unreachable")
        latest = responsibility
        try:
            if transfer_object.size == 0:
                if transfer_object.sha256 is None:
                    latest = await self._reserve_unknown_upload_final_object(
                        latest,
                        verified_object_handle=verified_object_handle,
                    )
                await self._object_store.create_empty_immutable(
                    destination=verified_identity,
                    transfer_metadata=S3TransferObjectMetadata(
                        sha256=actual_sha256,
                        content_type=None,
                    ),
                )
            else:
                assert upload is not None
                if transfer_object.sha256 is None:
                    await self._object_store.complete_preparation_multipart_upload(
                        upload=upload,
                        completed_parts=tuple(parts),
                        expected_size=actual_size,
                    )
                else:
                    await self._object_store.complete_multipart_upload(
                        upload=upload,
                        completed_parts=tuple(parts),
                        expected_size=actual_size,
                        expected_sha256=actual_sha256,
                    )
        except (S3TransferCancelled, S3TransferCleanupRequired) as exc:
            retained = await self._state_store.record_completed_object_cleanup(
                latest.admission.transfer_id,
                attempt_id=latest.admission.attempt_id,
                expected_revision=latest.revision,
                status=RuntimeTransferCleanupStatus.RETRYABLE_FAILURE,
                multipart_cleanup_required=exc.multipart_cleanup_required,
                completed_object_cleanup_required=(
                    exc.completed_object_cleanup_required
                ),
            )
            if retained is not None:
                latest = retained
            raise
        if upload is not None:
            completed_only = await self._state_store.record_completed_object_cleanup(
                latest.admission.transfer_id,
                attempt_id=latest.admission.attempt_id,
                expected_revision=latest.revision,
                status=RuntimeTransferCleanupStatus.RETRYABLE_FAILURE,
                multipart_cleanup_required=False,
                completed_object_cleanup_required=True,
            )
            if completed_only is None:
                current = await self._state_store.get(latest.admission.transfer_id)
                cleaned = await self._cleanup_upload(
                    current or latest,
                    upload=upload,
                    multipart_cleanup_required=True,
                    completed_object_cleanup_required=True,
                    identity=staging_identity,
                )
                await self._settle_lost_upload_authority(cleaned)
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Transfer completion state is fenced",
                )
                raise AssertionError("unreachable")
            latest = completed_only
        if transfer_object.sha256 is None and transfer_object.size > 0:
            latest = await self._reserve_unknown_upload_final_object(
                latest,
                verified_object_handle=verified_object_handle,
            )
            await self._object_store.copy_immutable(
                source=staging_identity,
                destination=verified_identity,
                expected_size=actual_size,
                transfer_metadata=S3TransferObjectMetadata(
                    sha256=actual_sha256,
                    content_type=None,
                ),
                multipart_copy_threshold=self._multipart_part_bytes,
                multipart_part_size=self._multipart_part_bytes,
            )
            await self._object_store.delete(
                bucket=staging_identity.bucket,
                key=staging_identity.key,
            )
        await keeper.stop()
        verifying = await self._state_store.begin_verification(
            latest.admission.transfer_id,
            attempt_id=latest.admission.attempt_id,
            runtime_id=latest.admission.runtime_id,
            desired_generation=latest.admission.desired_generation,
            accepted_runner_generation=latest.accepted_runner_generation or 0,
            claim_id=latest.stream_claim_id or "",
            expected_revision=latest.revision,
        )
        if verifying is None:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Transfer stream is fenced",
            )
            raise AssertionError("unreachable")
        available = await self._state_store.publish_available(
            verifying.admission.transfer_id,
            attempt_id=verifying.admission.attempt_id,
            runtime_id=verifying.admission.runtime_id,
            desired_generation=verifying.admission.desired_generation,
            accepted_runner_generation=verifying.accepted_runner_generation or 0,
            claim_id=verifying.stream_claim_id or "",
            expected_revision=verifying.revision,
            actual_size=actual_size,
            actual_sha256=actual_sha256,
        )
        if available is None:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Transfer availability is fenced",
            )
            raise AssertionError("unreachable")
        committed = await self._state_store.commit_upload_response(
            available.admission.transfer_id,
            attempt_id=available.admission.attempt_id,
            runtime_id=available.admission.runtime_id,
            desired_generation=available.admission.desired_generation,
            accepted_runner_generation=available.accepted_runner_generation or 0,
            claim_id=available.stream_claim_id or "",
            expected_revision=available.revision,
            actual_size=actual_size,
            actual_sha256=actual_sha256,
        )
        if committed is not None:
            return committed
        current = await self._state_store.get(available.admission.transfer_id)
        cleaned = await self._cleanup_upload(
            current or available,
            upload=upload,
            multipart_cleanup_required=False,
            completed_object_cleanup_required=True,
            identity=verified_identity,
        )
        await self._settle_lost_upload_authority(cleaned)
        await context.abort(
            grpc.StatusCode.FAILED_PRECONDITION,
            "Transfer upload response lost authority",
        )
        raise AssertionError("unreachable")

    async def _reserve_unknown_upload_final_object(
        self,
        record: RuntimeTransferRecord,
        *,
        verified_object_handle: str,
    ) -> RuntimeTransferRecord:
        """Persist final-object cleanup authority before a native promotion copy."""
        reserved = await self._state_store.record_pre_ready_object(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            accepted_runner_generation=record.accepted_runner_generation or 0,
            expected_revision=record.revision,
            claim_id=record.stream_claim_id or "",
            owner_replica_id=self._owner_replica_id,
            object_handle=verified_object_handle,
        )
        if reserved is None:
            raise RuntimeError("Transfer final-object reservation is fenced")
        return reserved

    async def _upload_part(
        self,
        record: RuntimeTransferRecord,
        credential: RuntimeRunnerCredential,
        context: _GrpcStreamContext,
        upload: S3MultipartUpload | None,
        parts: list[S3CompletedPart],
        body: bytes,
    ) -> RuntimeTransferRecord:
        if upload is None or not body:
            await context.abort(
                grpc.StatusCode.INTERNAL, "Upload transfer multipart state is invalid"
            )
            raise AssertionError("unreachable")
        if len(parts) >= _MAX_MULTIPART_PARTS:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Transfer exceeds multipart part capacity",
            )
            raise AssertionError("unreachable")
        checked = await self._check_stream(record, credential, context)
        completed = await self._object_store.upload_part(
            upload=upload,
            part_number=len(parts) + 1,
            body=body,
        )
        parts.append(completed)
        return checked

    async def _abort_upload(
        self, record: RuntimeTransferRecord, upload: S3MultipartUpload
    ) -> RuntimeTransferRecord:
        status = RuntimeTransferCleanupStatus.COMPLETE
        try:
            await self._object_store.abort_multipart_upload(upload=upload)
        except Exception:
            status = RuntimeTransferCleanupStatus.RETRYABLE_FAILURE
        current = await self._state_store.get(record.admission.transfer_id)
        if (
            current is None
            or current.admission.attempt_id != record.admission.attempt_id
        ):
            return record
        updated = await self._state_store.record_cleanup(
            current.admission.transfer_id,
            attempt_id=current.admission.attempt_id,
            expected_revision=current.revision,
            status=status,
        )
        return updated or current

    async def _cleanup_upload(
        self,
        record: RuntimeTransferRecord,
        *,
        upload: S3MultipartUpload | None,
        multipart_cleanup_required: bool,
        completed_object_cleanup_required: bool,
        identity: S3ObjectIdentity,
    ) -> RuntimeTransferRecord:
        """Clean exact upload artifacts and retain only failed cleanup evidence."""
        current = await self._state_store.get(record.admission.transfer_id)
        if (
            current is not None
            and current.admission.attempt_id == record.admission.attempt_id
        ):
            if current.upload_response_committed_at is not None:
                return current
            record = current
            multipart_cleanup_required = current.multipart_cleanup_handle is not None
            completed_object_cleanup_required = (
                current.completed_object_cleanup_required
            )
        multipart_remaining = multipart_cleanup_required
        completed_remaining = completed_object_cleanup_required
        if multipart_cleanup_required and upload is not None:
            try:
                await self._object_store.abort_multipart_upload(upload=upload)
            except Exception:
                pass
            else:
                multipart_remaining = False
        if completed_object_cleanup_required:
            try:
                if record.object is None:
                    raise ValueError("Completed object metadata is unavailable")
                if record.object.sha256 is None:
                    await self._object_store.delete(
                        bucket=identity.bucket,
                        key=identity.key,
                    )
                else:
                    await self._object_store.delete_verified_transfer_object(
                        identity=identity,
                        expected_size=record.object.size,
                        expected_sha256=record.object.sha256,
                    )
            except Exception:
                pass
            else:
                completed_remaining = False
        current = await self._state_store.get(record.admission.transfer_id)
        if (
            current is None
            or current.admission.attempt_id != record.admission.attempt_id
        ):
            return record
        if not completed_object_cleanup_required:
            if not multipart_cleanup_required:
                return current
            updated = await self._state_store.record_cleanup(
                current.admission.transfer_id,
                attempt_id=current.admission.attempt_id,
                expected_revision=current.revision,
                status=(
                    RuntimeTransferCleanupStatus.RETRYABLE_FAILURE
                    if multipart_remaining
                    else RuntimeTransferCleanupStatus.COMPLETE
                ),
            )
            return updated or current
        updated = await self._state_store.record_completed_object_cleanup(
            current.admission.transfer_id,
            attempt_id=current.admission.attempt_id,
            expected_revision=current.revision,
            status=(
                RuntimeTransferCleanupStatus.RETRYABLE_FAILURE
                if multipart_remaining or completed_remaining
                else RuntimeTransferCleanupStatus.COMPLETE
            ),
            multipart_cleanup_required=multipart_remaining,
            completed_object_cleanup_required=completed_remaining,
        )
        return updated or current

    async def _fail(
        self,
        record: RuntimeTransferRecord,
        *,
        cancelled: bool = False,
        outcome: RuntimeTransferOutcome | None = None,
        failure: RuntimeTransferFailure = RuntimeTransferFailure.STREAM,
    ) -> RuntimeTransferRecord | None:
        if outcome is None:
            outcome = (
                RuntimeTransferOutcome.CANCELLED
                if cancelled
                else RuntimeTransferOutcome.FAILED
            )
        if cancelled:
            failure = RuntimeTransferFailure.CANCELLED
        return await self._terminal_sink.settle_terminal(
            record,
            outcome=outcome,
            failure=failure,
            cleanup_completed=(
                record.cleanup_status is RuntimeTransferCleanupStatus.COMPLETE
                and record.multipart_cleanup_handle is None
                and not record.completed_object_cleanup_required
            ),
        )

    async def _abort_for_cancellation(
        self,
        record: RuntimeTransferRecord,
        context: GrpcAbortContext,
    ) -> None:
        """Settle and expose one persisted cancellation with canonical semantics."""
        reason = record.cancellation_reason or RuntimeTransferCancellationReason.CALLER
        settlement = cancellation_settlement(reason)
        await self._fail(
            record,
            outcome=settlement.outcome,
            failure=settlement.failure or RuntimeTransferFailure.CANCELLED,
        )
        if reason is RuntimeTransferCancellationReason.DEADLINE:
            await context.abort(
                grpc.StatusCode.DEADLINE_EXCEEDED,
                "Transfer deadline expired",
            )
        if reason is RuntimeTransferCancellationReason.SUPERSEDED:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Transfer Runner generation was superseded",
            )
        await context.abort(grpc.StatusCode.CANCELLED, "Transfer was cancelled")

    async def _settle_lost_upload_authority(
        self,
        record: RuntimeTransferRecord,
    ) -> RuntimeTransferRecord | None:
        """Settle the exact authority that defeated post-publish success."""
        if record.phase.value == "terminal":
            return record
        if record.cancellation_reason is not None:
            settlement = cancellation_settlement(record.cancellation_reason)
            return await self._fail(
                record,
                outcome=settlement.outcome,
                failure=settlement.failure or RuntimeTransferFailure.CANCELLED,
            )
        if _expired(record, self._now()):
            return await self._fail(
                record,
                outcome=RuntimeTransferOutcome.EXPIRED,
                failure=RuntimeTransferFailure.EXPIRED,
            )
        return await self._fail(record, failure=RuntimeTransferFailure.FENCED)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Runner transfer clock must be timezone-aware")
        return now

    def _object_identity(self, opaque_key: str) -> S3ObjectIdentity:
        """Resolve one state-owned opaque key into the internal S3 namespace."""
        return runtime_transfer_object_identity(
            bucket=self._bucket,
            object_prefix=self._object_prefix,
            opaque_key=opaque_key,
        )


def add_runtime_runner_transfer_servicer(
    server: grpc.aio.Server,
    *,
    state_store: RuntimeTransferStateStore,
    coordination_store: RuntimeCoordinationStore,
    object_store: RuntimeRunnerTransferObjectStore,
    terminal_sink: RuntimeTransferTerminalSink,
    bucket: str,
    owner_replica_id: str,
    runner_authenticator: RuntimeRunnerCredentialAuthenticator,
    clock: Callable[[], datetime],
    max_concurrent_downloads: int = _DEFAULT_MAX_CONCURRENT_DOWNLOADS,
    max_concurrent_uploads: int = _DEFAULT_MAX_CONCURRENT_UPLOADS,
    object_prefix: str = "",
    maximum_chunk_bytes: int = MAX_TRANSFER_CHUNK_BYTES,
    multipart_part_bytes: int = MULTIPART_PART_BYTES,
) -> None:
    """Register the bounded Runner transfer servicer on one gRPC server."""
    pb_grpc.add_RuntimeRunnerTransferServicer_to_server(
        RuntimeRunnerTransferGrpcServicer(
            state_store=state_store,
            coordination_store=coordination_store,
            object_store=object_store,
            terminal_sink=terminal_sink,
            bucket=bucket,
            owner_replica_id=owner_replica_id,
            runner_authenticator=runner_authenticator,
            clock=clock,
            max_concurrent_downloads=max_concurrent_downloads,
            max_concurrent_uploads=max_concurrent_uploads,
            object_prefix=object_prefix,
            maximum_chunk_bytes=maximum_chunk_bytes,
            multipart_part_bytes=multipart_part_bytes,
        ),
        server,
    )


def _expired(record: RuntimeTransferRecord, now: datetime) -> bool:
    return record.admission.deadline_at <= now or record.logical_expires_at <= now


def _claim_id() -> str:
    return f"runner-transfer:{secrets.token_urlsafe(18)}"


def _scheduler_participant(record: RuntimeTransferRecord) -> str:
    """Return one exact active-attempt identity for fair chunk scheduling."""
    admission = record.admission
    return ":".join(
        (
            admission.transfer_id,
            admission.attempt_id,
            admission.runtime_id,
            str(admission.desired_generation),
        )
    )


def _multipart_part_count(size: int, multipart_part_bytes: int) -> int:
    return (size + multipart_part_bytes - 1) // multipart_part_bytes


def _verified_upload_object_handle(staging_handle: str) -> str:
    """Return the state-owned immutable handle for one unknown-digest upload."""
    return f"{staging_handle}:verified"


def _is_abort_exception(exc: Exception) -> bool:
    """Return whether a gRPC context already selected an explicit status."""
    if isinstance(exc, grpc.aio.AbortError):
        return True
    return isinstance(getattr(exc, "code", None), grpc.StatusCode)


def _valid_identity(identity: pb.TransferIdentity) -> bool:
    return (
        all(
            0 < len(value.encode("utf-8")) <= 128
            for value in (
                identity.transfer_id,
                identity.attempt_id,
                identity.runtime_id,
            )
        )
        and identity.runner_generation > 0
    )
