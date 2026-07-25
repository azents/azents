"""Bounded S3-backed Runtime Runner download transfer service."""

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
from azcommon.infra.s3.service import S3ObjectIdentity, S3VerifiedObject
from azents_runtime_control.proto import runtime_runner_transfer_pb2 as pb
from azents_runtime_control.proto import runtime_runner_transfer_pb2_grpc as pb_grpc
from azents_runtime_control.transfer import (
    MAX_TRANSFER_CHUNK_BYTES,
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
    RuntimeTransferDirection,
    RuntimeTransferDispatchStatus,
    RuntimeTransferFailure,
    RuntimeTransferOutcome,
    RuntimeTransferRecord,
)
from azents.runtime.transfer.store import RuntimeTransferStateStore

_DEFAULT_MAX_CONCURRENT_DOWNLOADS = 4


class RuntimeRunnerTransferObjectStore(Protocol):
    """Trusted object-store operations needed for bounded downloads."""

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


class RuntimeRunnerTransferGrpcServicer(pb_grpc.RuntimeRunnerTransferServicer):
    """Authenticate and stream state-owned download objects to one Runner."""

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
    ) -> None:
        """Initialize state-owned transfer dependencies.

        :param state_store: authoritative transfer state
        :param coordination_store: current Runner generation registry
        :param object_store: trusted object-store service
        :param bucket: trusted object bucket selected by Control
        :param owner_replica_id: Control replica owning stream claims
        :param runner_authenticator: durable Runner credential authority
        :param clock: timezone-aware clock for deadlines and lease renewal
        :param max_concurrent_downloads: per-replica bounded stream capacity
        """
        if not bucket:
            raise ValueError("Runner transfer bucket is required")
        if max_concurrent_downloads <= 0:
            raise ValueError("max_concurrent_downloads must be positive")
        self._state_store = state_store
        self._coordination_store = coordination_store
        self._object_store = object_store
        self._bucket = bucket
        self._owner_replica_id = owner_replica_id
        self._runner_authenticator = runner_authenticator
        self._auth = RuntimeRunnerCredentialGrpcAuth(runner_authenticator)
        self._clock = clock
        self._downloads = asyncio.Semaphore(max_concurrent_downloads)

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
            identity = S3ObjectIdentity(bucket=self._bucket, key=transfer_object.key)
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
                maximum_chunk_size=MAX_TRANSFER_CHUNK_BYTES,
            ) as chunks:
                async for chunk in chunks:
                    latest = await self._check_stream(latest, credential, context)
                    if not chunk or len(chunk) > MAX_TRANSFER_CHUNK_BYTES:
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
        """Fail closed until the dedicated multipart upload slice is installed."""
        del request_iterator
        await context.abort(
            grpc.StatusCode.UNIMPLEMENTED, "Runner upload transfer is unavailable"
        )
        raise AssertionError("unreachable")

    async def _authorize_download(
        self,
        request: pb.DownloadTransferRequest,
        credential: RuntimeRunnerCredential,
        context: grpc.aio.ServicerContext[object, object],
    ) -> RuntimeTransferRecord:
        identity = request.identity
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

    async def _fail(
        self, record: RuntimeTransferRecord, *, cancelled: bool = False
    ) -> None:
        outcome = (
            RuntimeTransferOutcome.CANCELLED
            if cancelled
            else RuntimeTransferOutcome.FAILED
        )
        failure = (
            RuntimeTransferFailure.CANCELLED
            if cancelled
            else RuntimeTransferFailure.STREAM
        )
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
        ),
        server,
    )


def _expired(record: RuntimeTransferRecord, now: datetime) -> bool:
    return record.admission.deadline_at <= now or record.logical_expires_at <= now


def _claim_id() -> str:
    return f"runner-transfer:{secrets.token_urlsafe(18)}"
