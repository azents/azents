"""Bounded S3-backed Runtime Runner transfer service."""

# pyright: reportAttributeAccessIssue=false, reportUntypedBaseClass=false
# Protobuf generated modules expose dynamic message/RPC attributes.
# ruff: noqa: E501, B904

import asyncio
import hashlib
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

import grpc
from azcommon.infra.s3.service import (
    S3CompletedPart,
    S3MultipartUpload,
    S3ObjectIdentity,
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
    RuntimeRunnerCredentialAuthenticator,
    RuntimeRunnerCredentialGrpcAuth,
)
from azents.runtime.coordination.data import RuntimeConnectionKind
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.runtime.transfer.data import (
    RuntimeTransferCleanupStatus,
    RuntimeTransferDirection,
    RuntimeTransferDispatchStatus,
    RuntimeTransferFailure,
    RuntimeTransferOutcome,
    RuntimeTransferRecord,
)
from azents.runtime.transfer.object_store import runtime_transfer_object_identity
from azents.runtime.transfer.store import RuntimeTransferStateStore

_DEFAULT_MAX_CONCURRENT_DOWNLOADS = 4
_DEFAULT_MAX_CONCURRENT_UPLOADS = 4
_MAX_MULTIPART_PARTS = 10_000


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


class RuntimeRunnerTransferGrpcServicer(pb_grpc.RuntimeRunnerTransferServicer):
    """Authenticate and stream state-owned objects to one Runner."""

    def __init__(
        self,
        *,
        state_store: RuntimeTransferStateStore,
        coordination_store: RuntimeCoordinationStore,
        object_store: RuntimeRunnerTransferObjectStore,
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
        :param bucket: trusted object bucket selected by Control
        :param object_prefix: internal transfer-object S3 key namespace
        :param owner_replica_id: Control replica owning stream claims
        :param runner_authenticator: durable Runner credential authority
        :param clock: timezone-aware clock for deadlines and lease renewal
        :param max_concurrent_downloads: per-replica bounded stream capacity
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
        self._bucket = bucket
        self._object_prefix = object_prefix
        self._owner_replica_id = owner_replica_id
        self._runner_authenticator = runner_authenticator
        self._auth = RuntimeRunnerCredentialGrpcAuth(runner_authenticator)
        self._clock = clock
        self._downloads = asyncio.Semaphore(max_concurrent_downloads)
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
        if self._downloads.locked():
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Runner download capacity is exhausted",
            )
            raise AssertionError("unreachable")
        await self._downloads.acquire()
        claimed: RuntimeTransferRecord | None = None
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
            if claimed.object is None:
                await self._fail(claimed)
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Transfer object is unavailable",
                )
                raise AssertionError("unreachable")
            transfer_object = claimed.object
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
            latest = claimed
            renewed_at = self._now()
            async with self._object_store.iter_chunks(
                identity,
                maximum_chunk_size=self._maximum_chunk_bytes,
            ) as chunks:
                async for chunk in chunks:
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
                    progressed = await self._state_store.record_progress(
                        latest.admission.transfer_id,
                        attempt_id=latest.admission.attempt_id,
                        runtime_id=latest.admission.runtime_id,
                        desired_generation=latest.admission.desired_generation,
                        accepted_runner_generation=latest.accepted_runner_generation
                        or 0,
                        claim_id=latest.stream_claim_id or "",
                        expected_revision=latest.revision,
                        bytes_transferred=offset,
                    )
                    if progressed is None:
                        await context.abort(
                            grpc.StatusCode.FAILED_PRECONDITION,
                            "Transfer stream is fenced",
                        )
                        raise AssertionError("unreachable")
                    latest = progressed
                    now = self._now()
                    if (
                        now - renewed_at
                    ).total_seconds() >= STREAM_OWNER_RENEWAL_SECONDS:
                        renewed = await self._state_store.renew_stream_lease(
                            latest.admission.transfer_id,
                            attempt_id=latest.admission.attempt_id,
                            accepted_runner_generation=latest.accepted_runner_generation
                            or 0,
                            expected_revision=latest.revision,
                            claim_id=latest.stream_claim_id or "",
                            owner_replica_id=self._owner_replica_id,
                        )
                        if renewed is None:
                            await context.abort(
                                grpc.StatusCode.FAILED_PRECONDITION,
                                "Transfer stream lease is fenced",
                            )
                            raise AssertionError("unreachable")
                        latest = renewed
                        renewed_at = now
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
            yield pb.DownloadTransferFrame(
                complete=pb.DownloadTransferComplete(
                    actual_size=offset, sha256=digest.hexdigest()
                )
            )
        except asyncio.CancelledError:
            if claimed is not None:
                await self._fail(claimed, cancelled=True)
            raise
        finally:
            self._downloads.release()

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
            metadata = S3TransferObjectMetadata(
                sha256=transfer_object.sha256,
                content_type=None,
            )
            offset = 0
            digest = hashlib.sha256()
            parts: list[S3CompletedPart] = []
            buffer = bytearray()
            renewed_at = self._now()
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
                        upload = await self._object_store.create_multipart_upload(
                            destination=identity,
                            transfer_metadata=metadata,
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
                    latest = await self._record_progress(latest, offset, context)
                    latest, renewed_at = await self._renew_if_due(
                        latest, renewed_at, context
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
                        or digest.hexdigest() != transfer_object.sha256
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
            latest = await self._check_stream(latest, credential, context)
            if transfer_object.size == 0:
                await self._object_store.create_empty_immutable(
                    destination=identity,
                    transfer_metadata=metadata,
                )
            else:
                if upload is None:
                    await self._fail(latest)
                    await context.abort(
                        grpc.StatusCode.INTERNAL, "Upload transfer stream is invalid"
                    )
                    raise AssertionError("unreachable")
                if buffer:
                    latest = await self._upload_part(
                        latest,
                        credential,
                        context,
                        upload,
                        parts,
                        bytes(buffer),
                    )
                latest = await self._check_stream(latest, credential, context)
                await self._object_store.complete_multipart_upload(
                    upload=upload,
                    completed_parts=tuple(parts),
                    expected_size=offset,
                    expected_sha256=digest.hexdigest(),
                )
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
                actual_size=offset,
                actual_sha256=digest.hexdigest(),
            )
            if available is None:
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Transfer availability is fenced",
                )
                raise AssertionError("unreachable")
            if upload is not None:
                await self._state_store.record_cleanup(
                    available.admission.transfer_id,
                    attempt_id=available.admission.attempt_id,
                    expected_revision=available.revision,
                    status=RuntimeTransferCleanupStatus.COMPLETE,
                )
            return pb.UploadTransferResult(
                status=pb.UPLOAD_TRANSFER_STATUS_SUCCEEDED,
                actual_size=offset,
                sha256=digest.hexdigest(),
            )
        except asyncio.CancelledError:
            if latest is not None:
                if upload is not None:
                    latest = await self._abort_upload(latest, upload)
                await self._fail(latest, cancelled=True)
            raise
        except Exception:
            if latest is not None:
                if upload is not None:
                    latest = await self._abort_upload(latest, upload)
                await self._fail(latest)
            raise
        finally:
            self._uploads.release()

    async def _authorize_download(
        self,
        request: pb.DownloadTransferRequest,
        credential: RuntimeRunnerCredential,
        context: grpc.aio.ServicerContext[object, object],
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
        if (
            identity.runtime_id != credential.runtime_id
            or identity.runner_generation != credential.desired_generation
        ):
            await context.abort(
                grpc.StatusCode.PERMISSION_DENIED, "Transfer identity is not authorized"
            )
            raise AssertionError("unreachable")
        record = await self._state_store.get(identity.transfer_id)
        if (
            record is None
            or record.admission.attempt_id != identity.attempt_id
            or record.admission.runtime_id != identity.runtime_id
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
        context: grpc.aio.ServicerContext[object, object],
    ) -> RuntimeTransferRecord:
        """Authorize one first-frame upload identity before state mutation."""
        if not _valid_identity(identity):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, "Transfer identity is invalid"
            )
            raise AssertionError("unreachable")
        if (
            identity.runtime_id != credential.runtime_id
            or identity.runner_generation != credential.desired_generation
        ):
            await context.abort(
                grpc.StatusCode.PERMISSION_DENIED, "Transfer identity is not authorized"
            )
            raise AssertionError("unreachable")
        record = await self._state_store.get(identity.transfer_id)
        if (
            record is None
            or record.admission.attempt_id != identity.attempt_id
            or record.admission.runtime_id != identity.runtime_id
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
        context: grpc.aio.ServicerContext[object, object],
    ) -> RuntimeTransferRecord:
        if context.cancelled() or not await self._runner_authenticator.authorize_runner(
            credential
        ):
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
            current is None
            or current.revision != record.revision
            or current.stream_claim_id != record.stream_claim_id
            or current.stream_owner_replica_id != self._owner_replica_id
            or current.accepted_runner_generation != credential.desired_generation
            or connection is None
            or connection.generation != credential.desired_generation
            or _expired(current, self._now())
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
        context: grpc.aio.ServicerContext[object, object],
    ) -> RuntimeTransferRecord:
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

    async def _renew_if_due(
        self,
        record: RuntimeTransferRecord,
        renewed_at: datetime,
        context: grpc.aio.ServicerContext[object, object],
    ) -> tuple[RuntimeTransferRecord, datetime]:
        now = self._now()
        if (now - renewed_at).total_seconds() < STREAM_OWNER_RENEWAL_SECONDS:
            return record, renewed_at
        renewed = await self._state_store.renew_stream_lease(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            accepted_runner_generation=record.accepted_runner_generation or 0,
            expected_revision=record.revision,
            claim_id=record.stream_claim_id or "",
            owner_replica_id=self._owner_replica_id,
        )
        if renewed is None:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, "Transfer stream lease is fenced"
            )
            raise AssertionError("unreachable")
        return renewed, now

    async def _upload_part(
        self,
        record: RuntimeTransferRecord,
        credential: RuntimeRunnerCredential,
        context: grpc.aio.ServicerContext[object, object],
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

    async def _fail(
        self,
        record: RuntimeTransferRecord,
        *,
        cancelled: bool = False,
        failure: RuntimeTransferFailure = RuntimeTransferFailure.STREAM,
    ) -> None:
        outcome = (
            RuntimeTransferOutcome.CANCELLED
            if cancelled
            else RuntimeTransferOutcome.FAILED
        )
        failure = RuntimeTransferFailure.CANCELLED if cancelled else failure
        settled = await self._state_store.settle(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            expected_revision=record.revision,
            outcome=outcome,
            failure=failure,
        )
        if settled is not None:
            await self._state_store.release_admission(
                settled.admission.transfer_id,
                attempt_id=settled.admission.attempt_id,
                lease_id=settled.lease_id,
            )

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


def _multipart_part_count(size: int, multipart_part_bytes: int) -> int:
    return (size + multipart_part_bytes - 1) // multipart_part_bytes


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
