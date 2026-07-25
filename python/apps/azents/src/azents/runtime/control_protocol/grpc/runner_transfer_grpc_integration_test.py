"""Socket-level Runner Transfer tests with default gRPC message limits."""

# pyright: reportAttributeAccessIssue=false, reportUntypedBaseClass=false
# Protobuf generated modules expose dynamic message/RPC attributes.
# ruff: noqa: E501

import asyncio
import hashlib
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import grpc
import pytest
from azcommon.infra.s3.service import (
    S3CompletedPart,
    S3MultipartUpload,
    S3ObjectIdentity,
    S3TransferObjectMetadata,
    S3VerifiedObject,
)
from azents_runtime_control.proto import runtime_runner_control_pb2 as control_pb
from azents_runtime_control.proto import runtime_runner_control_pb2_grpc as control_grpc
from azents_runtime_control.proto import runtime_runner_transfer_pb2 as transfer_pb
from azents_runtime_control.proto import (
    runtime_runner_transfer_pb2_grpc as transfer_grpc,
)
from azents_runtime_control.transfer import (
    MAX_TRANSFER_CHUNK_BYTES,
    MULTIPART_PART_BYTES,
)
from google.protobuf import timestamp_pb2

from azents.core.runtime_runner_credential import (
    RuntimeRunnerCredential,
    RuntimeRunnerCredentialInvalid,
)
from azents.runtime.control_protocol.data import (
    RuntimeDispatchResult,
    RuntimeRunnerOperation,
)
from azents.runtime.control_protocol.grpc.runner_server import (
    RuntimeRunnerControlGrpcServicer,
)
from azents.runtime.control_protocol.grpc.runner_transfer_server import (
    RuntimeRunnerTransferGrpcServicer,
)
from azents.runtime.control_protocol.service import RuntimeControlProtocolService
from azents.runtime.coordination.data import (
    RuntimeOperationStatus,
    RuntimeReplyRecord,
)
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.runtime.transfer.coordinator import RuntimeTransferCoordinator
from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCancellationReason,
    RuntimeTransferCleanupStatus,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferObject,
    RuntimeTransferOutcome,
)
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore

_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
_FRAME_BYTES = 128 * 1024


class _Authenticator:
    credential = RuntimeRunnerCredential("credential-1", "runtime-1", 1)

    async def authenticate_runner(self, secret: str) -> RuntimeRunnerCredential:
        if secret != "token":
            raise RuntimeRunnerCredentialInvalid("invalid")
        return self.credential

    async def authorize_runner(self, credential: RuntimeRunnerCredential) -> bool:
        return credential == self.credential


class _StateSink:
    async def record_runner_state(self, report: object) -> None:
        del report

    async def validate_runner_registration(self, registration: object) -> bool:
        del registration
        return True


class _TransferResultSink:
    async def handle(self, result: object, *, request_id: str) -> None:
        del result, request_id

    async def handle_failure(
        self,
        operation: object,
        *,
        request_id: str,
        error_code: str,
        failure: object,
    ) -> None:
        del operation, request_id, error_code, failure


class _TransferResultSink:
    async def handle(self, result: object, *, request_id: str) -> None:
        del result, request_id

    async def handle_failure(
        self,
        operation: object,
        *,
        request_id: str,
        error_code: str,
        failure: object,
    ) -> None:
        del operation, request_id, error_code, failure


class _ObjectStore:
    def __init__(self, download: bytes) -> None:
        self.download = download
        self.parts: list[bytes] = []
        self.uploads: dict[str, bytes] = {}
        self.aborted_upload_ids: list[str] = []
        self.block_download = False
        self.download_blocked = asyncio.Event()
        self.resume_download = asyncio.Event()
        self.block_upload_part = False
        self.upload_part_blocked = asyncio.Event()
        self.resume_upload_part = asyncio.Event()

    async def verify_transfer_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject:
        del identity
        assert len(self.download) == expected_size
        assert hashlib.sha256(self.download).hexdigest() == expected_sha256
        return object()  # type: ignore[return-value]

    @asynccontextmanager
    async def iter_chunks(
        self,
        identity: S3ObjectIdentity,
        *,
        maximum_chunk_size: int,
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        del identity
        assert maximum_chunk_size == MAX_TRANSFER_CHUNK_BYTES

        async def chunks() -> AsyncIterator[bytes]:
            for offset in range(0, len(self.download), _FRAME_BYTES):
                yield self.download[offset : offset + _FRAME_BYTES]
                if offset == 0 and self.block_download:
                    self.download_blocked.set()
                    await self.resume_download.wait()

        yield chunks()

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
        if self.block_upload_part:
            self.upload_part_blocked.set()
            await self.resume_upload_part.wait()
        self.parts.append(body)
        return S3CompletedPart(part_number=part_number, etag=f"etag-{part_number}")

    async def complete_multipart_upload(
        self,
        *,
        upload: S3MultipartUpload,
        completed_parts: tuple[S3CompletedPart, ...],
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject:
        assert tuple(part.part_number for part in completed_parts) == tuple(
            range(1, len(completed_parts) + 1)
        )
        value = b"".join(self.parts)
        assert len(value) == expected_size
        assert hashlib.sha256(value).hexdigest() == expected_sha256
        self.uploads[upload.identity.key] = value
        return object()  # type: ignore[return-value]

    async def abort_multipart_upload(self, *, upload: S3MultipartUpload) -> None:
        self.aborted_upload_ids.append(upload.upload_id)

    async def create_empty_immutable(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3VerifiedObject:
        del destination, transfer_metadata
        return object()  # type: ignore[return-value]

    async def delete_verified_transfer_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        del expected_size, expected_sha256
        self.uploads.pop(identity.key, None)


class _RecordingRunnerServicer(RuntimeRunnerControlGrpcServicer):
    def __init__(self, **kwargs: object) -> None:
        kwargs["transfer_result_sink"] = _TransferResultSink()
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.peers: list[str] = []

    async def ConnectRunner(
        self,
        request_iterator: AsyncIterator[control_pb.RunnerMessage],
        context: grpc.aio.ServicerContext[
            control_pb.RunnerMessage,
            control_pb.RunnerControlMessage,
        ],
    ) -> AsyncIterator[control_pb.RunnerControlMessage]:
        self.peers.append(context.peer())
        async for message in super().ConnectRunner(request_iterator, context):
            yield message


class _RecordingTransferServicer(RuntimeRunnerTransferGrpcServicer):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.peers: list[str] = []

    async def DownloadTransfer(
        self,
        request: transfer_pb.DownloadTransferRequest,
        context: grpc.aio.ServicerContext[
            transfer_pb.DownloadTransferRequest,
            transfer_pb.DownloadTransferFrame,
        ],
    ) -> AsyncIterator[transfer_pb.DownloadTransferFrame]:
        self.peers.append(context.peer())
        async for frame in super().DownloadTransfer(request, context):
            yield frame

    async def UploadTransfer(
        self,
        request_iterator: AsyncIterator[transfer_pb.UploadTransferFrame],
        context: grpc.aio.ServicerContext[
            transfer_pb.UploadTransferFrame,
            transfer_pb.UploadTransferResult,
        ],
    ) -> transfer_pb.UploadTransferResult:
        self.peers.append(context.peer())
        return await super().UploadTransfer(request_iterator, context)


@pytest.mark.asyncio
async def test_default_limit_channels_keep_control_healthy_during_large_transfers() -> (
    None
):
    """Transfer frames over separate sockets avoid the default 4 MiB RPC limit."""
    download = b"d" * (4 * 1024 * 1024 + 123)
    upload = b"u" * (5 * 1024 * 1024 + 123)
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=lambda: _NOW)
    coordination = InMemoryRuntimeCoordinationStore()
    control = RuntimeControlProtocolService(coordination)
    authenticator = _Authenticator()
    object_store = _ObjectStore(download)
    runner = _RecordingRunnerServicer(
        control_protocol=control,
        coordination_store=coordination,
        state_sink=_StateSink(),
        owner_replica_id="replica-1",
        consumer_id="runner-consumer",
        runner_authenticator=authenticator,
        operation_block_ms=1,
    )
    transfer = _RecordingTransferServicer(
        state_store=state,
        coordination_store=coordination,
        object_store=object_store,
        terminal_sink=RuntimeTransferCoordinator(
            state_store=state,
            coordination_store=coordination,
            cleanup=None,
            clock=lambda: _NOW,
        ),
        bucket="bucket",
        owner_replica_id="replica-1",
        runner_authenticator=authenticator,
        clock=lambda: _NOW,
    )
    server = grpc.aio.server()
    control_grpc.add_RuntimeRunnerControlServicer_to_server(runner, server)
    transfer_grpc.add_RuntimeRunnerTransferServicer_to_server(transfer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    local_subchannel_pool = (("grpc.use_local_subchannel_pool", 1),)
    control_channel = grpc.aio.insecure_channel(
        f"127.0.0.1:{port}",
        options=local_subchannel_pool,
    )
    transfer_channel = grpc.aio.insecure_channel(
        f"127.0.0.1:{port}",
        options=local_subchannel_pool,
    )
    inbound: asyncio.Queue[control_pb.RunnerMessage | None] = asyncio.Queue()
    stream = control_grpc.RuntimeRunnerControlStub(control_channel).ConnectRunner(
        _runner_messages(inbound),
        metadata=(("authorization", "Bearer token"),),
    )
    try:
        await inbound.put(_register())
        accepted = await stream.read()
        assert accepted.register_accepted.generation == 1

        await inbound.put(
            control_pb.RunnerMessage(
                connection_id="connection-1",
                request_id="heartbeat-before",
                generation=1,
                heartbeat=control_pb.RunnerHeartbeat(monotonic_sequence=1),
            )
        )
        heartbeat = await stream.read()
        assert heartbeat.heartbeat_ack.monotonic_sequence == 1

        await _ready(state, RuntimeTransferDirection.DOWNLOAD, "download-1", download)
        download_frames = [
            frame
            async for frame in transfer_grpc.RuntimeRunnerTransferStub(
                transfer_channel
            ).DownloadTransfer(_download_request("download-1"), metadata=_metadata())
        ]
        assert b"".join(frame.chunk.data for frame in download_frames[:-1]) == download
        assert download_frames[-1].complete.actual_size == len(download)
        assert all(
            frame.ByteSize() <= MAX_TRANSFER_CHUNK_BYTES for frame in download_frames
        )

        await _ready(state, RuntimeTransferDirection.UPLOAD, "upload-1", upload)
        uploaded = await transfer_grpc.RuntimeRunnerTransferStub(
            transfer_channel
        ).UploadTransfer(_upload_frames("upload-1", upload), metadata=_metadata())
        assert uploaded.actual_size == len(upload)
        assert uploaded.sha256 == hashlib.sha256(upload).hexdigest()
        assert object_store.uploads["transfer-object:upload-1"] == upload

        with pytest.raises(grpc.aio.AioRpcError) as malformed:
            await transfer_grpc.RuntimeRunnerTransferStub(
                transfer_channel
            ).UploadTransfer(
                _malformed_upload_frames(),
                metadata=_metadata(),
            )
        assert malformed.value.code() is grpc.StatusCode.FAILED_PRECONDITION
        await inbound.put(
            control_pb.RunnerMessage(
                connection_id="connection-1",
                request_id="heartbeat-after",
                generation=1,
                heartbeat=control_pb.RunnerHeartbeat(monotonic_sequence=2),
            )
        )
        heartbeat = await stream.read()
        assert heartbeat.heartbeat_ack.monotonic_sequence == 2
        assert runner.peers and transfer.peers
        assert runner.peers[0] != transfer.peers[0]
    finally:
        await inbound.put(None)
        stream.cancel()
        await control_channel.close()
        await transfer_channel.close()
        await server.stop(None)


@pytest.mark.asyncio
async def test_backpressured_transfer_keeps_runner_operation_control_healthy() -> None:
    """A paused transfer stream must not prevent Control operation completion."""
    download = b"d" * (_FRAME_BYTES * 2)
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=lambda: _NOW)
    coordination = InMemoryRuntimeCoordinationStore()
    control = RuntimeControlProtocolService(coordination)
    authenticator = _Authenticator()
    object_store = _ObjectStore(download)
    object_store.block_download = True
    runner = _RecordingRunnerServicer(
        control_protocol=control,
        coordination_store=coordination,
        state_sink=_StateSink(),
        owner_replica_id="replica-1",
        consumer_id="runner-consumer",
        runner_authenticator=authenticator,
        operation_block_ms=1,
    )
    transfer = _RecordingTransferServicer(
        state_store=state,
        coordination_store=coordination,
        object_store=object_store,
        terminal_sink=RuntimeTransferCoordinator(
            state_store=state,
            coordination_store=coordination,
            cleanup=None,
            clock=lambda: _NOW,
        ),
        bucket="bucket",
        owner_replica_id="replica-1",
        runner_authenticator=authenticator,
        clock=lambda: _NOW,
    )
    server = grpc.aio.server()
    control_grpc.add_RuntimeRunnerControlServicer_to_server(runner, server)
    transfer_grpc.add_RuntimeRunnerTransferServicer_to_server(transfer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    local_subchannel_pool = (("grpc.use_local_subchannel_pool", 1),)
    control_channel = grpc.aio.insecure_channel(
        f"127.0.0.1:{port}",
        options=local_subchannel_pool,
    )
    transfer_channel = grpc.aio.insecure_channel(
        f"127.0.0.1:{port}",
        options=local_subchannel_pool,
    )
    inbound: asyncio.Queue[control_pb.RunnerMessage | None] = asyncio.Queue()
    stream = control_grpc.RuntimeRunnerControlStub(control_channel).ConnectRunner(
        _runner_messages(inbound),
        metadata=_metadata(),
    )
    try:
        await inbound.put(_register())
        accepted = await stream.read()
        assert accepted.register_accepted.generation == 1

        await _ready(
            state, RuntimeTransferDirection.DOWNLOAD, "paused-download", download
        )
        download_stream = transfer_grpc.RuntimeRunnerTransferStub(
            transfer_channel
        ).DownloadTransfer(_download_request("paused-download"), metadata=_metadata())
        first = await download_stream.read()
        assert first.chunk.data == download[:_FRAME_BYTES]
        await asyncio.wait_for(object_store.download_blocked.wait(), timeout=1)

        dispatched = await control.dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id="runtime-1",
                runner_generation=1,
                operation_type="bash",
                owner_session_id="session-1",
                payload={"command": "echo control-remains-responsive"},
                deadline_at=datetime.now(UTC) + timedelta(minutes=1),
                body_stream_id=None,
            ),
            created_at=datetime.now(UTC),
        )
        assert isinstance(dispatched, RuntimeDispatchResult)
        operation = await asyncio.wait_for(stream.read(), timeout=1)
        assert operation.operation_request.operation_type == "bash"
        assert (
            operation.operation_request.bash.command
            == "echo control-remains-responsive"
        )

        await inbound.put(
            control_pb.RunnerMessage(
                connection_id="connection-1",
                request_id=f"start:{dispatched.request_id}",
                generation=1,
                operation_start=control_pb.RunnerOperationStart(
                    runtime_id="runtime-1",
                    operation_id=dispatched.operation_id,
                ),
            )
        )
        started = await asyncio.wait_for(stream.read(), timeout=1)
        assert started.operation_start_ack.allowed
        await inbound.put(
            _final_bash_event(
                request_id=dispatched.request_id,
                operation_id=dispatched.operation_id,
            )
        )
        replies = await _wait_for_replies(control, dispatched.reply_stream_id)
        assert replies[-1].event.final
        assert replies[-1].event.payload == {"exit_code": 0}

        object_store.resume_download.set()
        remainder = await _read_remaining_download_frames(download_stream)
        assert (
            b"".join(
                [first.chunk.data, *(frame.chunk.data for frame in remainder[:-1])]
            )
            == download
        )
        assert remainder[-1].complete.actual_size == len(download)
        assert runner.peers[0] != transfer.peers[0]
    finally:
        object_store.resume_download.set()
        await inbound.put(None)
        stream.cancel()
        await control_channel.close()
        await transfer_channel.close()
        await server.stop(None)


@pytest.mark.asyncio
async def test_cancelled_active_upload_aborts_cleanup_and_keeps_control_healthy() -> (
    None
):
    """Typed cancellation aborts one active upload without harming Control."""
    upload = b"u" * MULTIPART_PART_BYTES
    state = InMemoryRuntimeTransferStateStore(
        config=_config(maximum_attempts=1),
        clock=lambda: _NOW,
    )
    coordination = InMemoryRuntimeCoordinationStore()
    control = RuntimeControlProtocolService(coordination)
    authenticator = _Authenticator()
    object_store = _ObjectStore(b"")
    object_store.block_upload_part = True
    transfer_coordinator = RuntimeTransferCoordinator(
        state_store=state,
        coordination_store=coordination,
        cleanup=None,
        clock=lambda: _NOW,
    )
    runner = _RecordingRunnerServicer(
        control_protocol=control,
        coordination_store=coordination,
        state_sink=_StateSink(),
        owner_replica_id="replica-1",
        consumer_id="runner-consumer",
        runner_authenticator=authenticator,
        operation_block_ms=1,
    )
    transfer = _RecordingTransferServicer(
        state_store=state,
        coordination_store=coordination,
        object_store=object_store,
        terminal_sink=transfer_coordinator,
        bucket="bucket",
        owner_replica_id="replica-1",
        runner_authenticator=authenticator,
        clock=lambda: _NOW,
    )
    server = grpc.aio.server()
    control_grpc.add_RuntimeRunnerControlServicer_to_server(runner, server)
    transfer_grpc.add_RuntimeRunnerTransferServicer_to_server(transfer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    local_subchannel_pool = (("grpc.use_local_subchannel_pool", 1),)
    control_channel = grpc.aio.insecure_channel(
        f"127.0.0.1:{port}",
        options=local_subchannel_pool,
    )
    transfer_channel = grpc.aio.insecure_channel(
        f"127.0.0.1:{port}",
        options=local_subchannel_pool,
    )
    inbound: asyncio.Queue[control_pb.RunnerMessage | None] = asyncio.Queue()
    stream = control_grpc.RuntimeRunnerControlStub(control_channel).ConnectRunner(
        _runner_messages(inbound),
        metadata=_metadata(),
    )
    try:
        await inbound.put(_register())
        accepted = await stream.read()
        assert accepted.register_accepted.generation == 1
        admission = _transfer_admission(
            RuntimeTransferDirection.UPLOAD,
            "cancelled-upload",
            upload,
        )
        admitted = await transfer_coordinator.admit(
            admission,
            lease_id="cancelled-upload-lease",
        )
        assert admitted is not None
        ready = await state.mark_ready(
            admission.transfer_id,
            attempt_id=admission.attempt_id,
            runtime_id=admission.runtime_id,
            desired_generation=admission.desired_generation,
            expected_revision=admitted.revision,
            object=RuntimeTransferObject(
                f"transfer-object:{admission.transfer_id}",
                len(upload),
                hashlib.sha256(upload).hexdigest(),
            ),
        )
        assert ready is not None
        dispatched = await transfer_coordinator.dispatch(
            ready,
            expected_revision=ready.revision,
            dispatch_id="cancelled-upload-dispatch",
        )
        intent = await asyncio.wait_for(stream.read(), timeout=1)
        assert intent.transfer_intent.identity.transfer_id == "cancelled-upload"
        assert (
            intent.transfer_intent.dispatch_id
            == dispatched.record.dispatch_id
            == "cancelled-upload-dispatch"
        )

        upload_call = transfer_grpc.RuntimeRunnerTransferStub(
            transfer_channel
        ).UploadTransfer(
            _upload_frames("cancelled-upload", upload), metadata=_metadata()
        )
        await asyncio.wait_for(object_store.upload_part_blocked.wait(), timeout=2)
        current = await state.get("cancelled-upload")
        assert current is not None
        cancelled = await transfer_coordinator.cancel(
            current,
            expected_revision=current.revision,
            reason=RuntimeTransferCancellationReason.CALLER,
        )
        assert cancelled is not None
        cancellation = await asyncio.wait_for(stream.read(), timeout=1)
        assert cancellation.transfer_cancel.identity.transfer_id == "cancelled-upload"
        assert cancellation.transfer_cancel.dispatch_id == "cancelled-upload-dispatch"
        assert (
            cancellation.transfer_cancel.reason
            == control_pb.RUNNER_TRANSFER_CANCEL_REASON_CALLER
        )

        # The synthetic Runner applies the typed cancel to its active data RPC.
        upload_call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await upload_call
        await _wait_for(lambda: bool(object_store.aborted_upload_ids))

        record = await state.get("cancelled-upload")
        assert record is not None
        assert record.terminal_outcome is RuntimeTransferOutcome.CANCELLED
        assert record.cleanup_status is RuntimeTransferCleanupStatus.COMPLETE
        assert record.multipart_cleanup_handle is None
        assert object_store.aborted_upload_ids == ["upload-1"]
        operation = await coordination.get_operation(admission.operation_id)
        assert operation is not None
        assert operation.status is RuntimeOperationStatus.FINAL
        replies = await _wait_for_replies(control, dispatched.reply_stream_id)
        assert replies[-1].event.final
        assert replies[-1].event.payload["outcome"] == "cancelled"

        replacement = await state.admit(
            _transfer_admission(
                RuntimeTransferDirection.UPLOAD,
                "replacement-upload",
                upload,
            ),
            lease_id="replacement-upload-lease",
        )
        assert replacement is not None

        await inbound.put(
            control_pb.RunnerMessage(
                connection_id="connection-1",
                request_id="heartbeat-after-cancellation",
                generation=1,
                heartbeat=control_pb.RunnerHeartbeat(monotonic_sequence=1),
            )
        )
        heartbeat = await asyncio.wait_for(stream.read(), timeout=1)
        assert heartbeat.heartbeat_ack.monotonic_sequence == 1

        followup = await control.dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id="runtime-1",
                runner_generation=1,
                operation_type="bash",
                owner_session_id="session-after-cancellation",
                payload={"command": "echo transfer-cancel-isolated"},
                deadline_at=datetime.now(UTC) + timedelta(minutes=1),
                body_stream_id=None,
            ),
            created_at=datetime.now(UTC),
        )
        assert isinstance(followup, RuntimeDispatchResult)
        request = await asyncio.wait_for(stream.read(), timeout=1)
        assert request.operation_request.bash.command == "echo transfer-cancel-isolated"
        await inbound.put(
            control_pb.RunnerMessage(
                connection_id="connection-1",
                request_id=f"start:{followup.request_id}",
                generation=1,
                operation_start=control_pb.RunnerOperationStart(
                    runtime_id="runtime-1",
                    operation_id=followup.operation_id,
                ),
            )
        )
        started = await asyncio.wait_for(stream.read(), timeout=1)
        assert started.operation_start_ack.allowed
        await inbound.put(
            _final_bash_event(
                request_id=followup.request_id,
                operation_id=followup.operation_id,
            )
        )
        followup_reply = await _wait_for_reply_request(
            control,
            followup.reply_stream_id,
            followup.request_id,
        )
        assert followup_reply.event.payload == {"exit_code": 0}
        assert runner.peers[0] != transfer.peers[0]
    finally:
        object_store.resume_upload_part.set()
        await inbound.put(None)
        stream.cancel()
        await control_channel.close()
        await transfer_channel.close()
        await server.stop(None)


async def _runner_messages(
    inbound: asyncio.Queue[control_pb.RunnerMessage | None],
) -> AsyncIterator[control_pb.RunnerMessage]:
    while (message := await inbound.get()) is not None:
        yield message


def _register() -> control_pb.RunnerMessage:
    return control_pb.RunnerMessage(
        connection_id="connection-1",
        request_id="register",
        register=control_pb.RunnerRegister(
            runtime_id="runtime-1",
            runner_id="runner-1",
            protocol_version="agent-runtime-runner.v1",
            capabilities=("file.transfer.v1",),
            health="ok",
            workspace_path="/workspace",
            auth_credential_id="credential-1",
            execution_policy=control_pb.RunnerExecutionPolicyEvidence(
                snapshot_id="snapshot-1",
                digest="d" * 64,
                desired_generation=1,
                module_versions={"docker": 1, "runtime.resources": 1},
                source_versions={
                    "profile": 1,
                    "workspace": 1,
                    "agent": 1,
                },
            ),
        ),
    )


async def _ready(
    state: InMemoryRuntimeTransferStateStore,
    direction: RuntimeTransferDirection,
    transfer_id: str,
    data: bytes,
) -> None:
    admission = _transfer_admission(direction, transfer_id, data)
    admitted = await state.admit(admission, lease_id=f"{transfer_id}-lease")
    assert admitted is not None
    ready = await state.mark_ready(
        transfer_id,
        attempt_id=admission.attempt_id,
        runtime_id="runtime-1",
        desired_generation=1,
        expected_revision=admitted.revision,
        object=RuntimeTransferObject(
            f"transfer-object:{transfer_id}",
            len(data),
            hashlib.sha256(data).hexdigest(),
        ),
    )
    assert ready is not None
    bound = await state.bind_dispatch(
        transfer_id,
        attempt_id=admission.attempt_id,
        runtime_id="runtime-1",
        desired_generation=1,
        accepted_runner_generation=1,
        expected_revision=ready.revision,
        dispatch_id=f"{transfer_id}-dispatch",
        dispatch_request_id=f"{transfer_id}-request",
    )
    assert bound is not None
    deliverable = await state.mark_dispatch_deliverable(
        transfer_id,
        attempt_id=admission.attempt_id,
        expected_revision=bound.revision,
        dispatch_id=bound.dispatch_id or "",
        dispatch_request_id=bound.dispatch_request_id or "",
    )
    assert deliverable is not None


def _transfer_admission(
    direction: RuntimeTransferDirection,
    transfer_id: str,
    data: bytes,
) -> RuntimeTransferAdmission:
    digest = hashlib.sha256(data).hexdigest()
    return RuntimeTransferAdmission(
        transfer_id=transfer_id,
        attempt_id=f"{transfer_id}-attempt",
        direction=direction,
        runtime_id="runtime-1",
        desired_generation=1,
        operation_id=f"{transfer_id}-operation",
        session_id=None,
        agent_id=None,
        runtime_path="/workspace/file",
        overwrite=False,
        expected_size=len(data),
        expected_sha256=digest,
        product_maximum_size=len(data),
        provider_maximum_size=len(data),
        deadline_at=_NOW + timedelta(minutes=5),
        source_expires_at=None,
        resource_class="file",
    )


def _download_request(transfer_id: str) -> transfer_pb.DownloadTransferRequest:
    return transfer_pb.DownloadTransferRequest(
        identity=transfer_pb.TransferIdentity(
            transfer_id=transfer_id,
            attempt_id=f"{transfer_id}-attempt",
            runtime_id="runtime-1",
            runner_generation=1,
        )
    )


def _upload_frames(
    transfer_id: str,
    data: bytes,
) -> AsyncIterator[transfer_pb.UploadTransferFrame]:
    async def frames() -> AsyncIterator[transfer_pb.UploadTransferFrame]:
        yield transfer_pb.UploadTransferFrame(
            open=transfer_pb.UploadTransferOpen(
                identity=_download_request(transfer_id).identity
            )
        )
        for offset in range(0, len(data), _FRAME_BYTES):
            yield transfer_pb.UploadTransferFrame(
                chunk=transfer_pb.TransferChunk(
                    offset=offset,
                    data=data[offset : offset + _FRAME_BYTES],
                )
            )
        yield transfer_pb.UploadTransferFrame(
            complete=transfer_pb.UploadTransferComplete(
                actual_size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        )

    return frames()


def _malformed_upload_frames() -> AsyncIterator[transfer_pb.UploadTransferFrame]:
    async def frames() -> AsyncIterator[transfer_pb.UploadTransferFrame]:
        yield transfer_pb.UploadTransferFrame(
            chunk=transfer_pb.TransferChunk(offset=0, data=b"invalid")
        )

    return frames()


def _final_bash_event(
    *,
    request_id: str,
    operation_id: str,
) -> control_pb.RunnerMessage:
    return control_pb.RunnerMessage(
        connection_id="connection-1",
        request_id=request_id,
        generation=1,
        operation_event=control_pb.RunnerOperationEvent(
            runtime_id="runtime-1",
            operation_id=operation_id,
            generation=1,
            event_type="final_success",
            created_at=_timestamp(_NOW),
            final=True,
            final_success=control_pb.RunnerOperationFinalSuccessPayload(
                bash=control_pb.BashFinalSuccess(exit_code=0)
            ),
        ),
    )


async def _wait_for_replies(
    control: RuntimeControlProtocolService,
    reply_stream_id: str,
) -> list[RuntimeReplyRecord]:
    replies: list[RuntimeReplyRecord] = []

    async def read() -> bool:
        nonlocal replies
        replies = await control.read_replies(
            reply_stream_id=reply_stream_id,
            after_cursor=None,
            limit=10,
        )
        return bool(replies)

    await _wait_for(read)
    return replies


async def _wait_for_reply_request(
    control: RuntimeControlProtocolService,
    reply_stream_id: str,
    request_id: str,
) -> RuntimeReplyRecord:
    matching: RuntimeReplyRecord | None = None

    async def read() -> bool:
        nonlocal matching
        replies = await control.read_replies(
            reply_stream_id=reply_stream_id,
            after_cursor=None,
            limit=10,
        )
        matching = next(
            (reply for reply in replies if reply.event.request_id == request_id),
            None,
        )
        return matching is not None

    await _wait_for(read)
    assert matching is not None
    return matching


async def _read_remaining_download_frames(
    stream: grpc.aio.UnaryStreamCall[
        transfer_pb.DownloadTransferRequest,
        transfer_pb.DownloadTransferFrame,
    ],
) -> list[transfer_pb.DownloadTransferFrame]:
    frames: list[transfer_pb.DownloadTransferFrame] = []
    while (frame := await stream.read()) is not grpc.aio.EOF:
        frames.append(frame)
    return frames


async def _wait_for(predicate: Callable[[], bool | Awaitable[bool]]) -> None:
    for _ in range(100):
        result = predicate()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return
        await asyncio.sleep(0.01)
    pytest.fail("Timed out waiting for asynchronous test condition")


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def _metadata() -> tuple[tuple[str, str], ...]:
    return (("authorization", "Bearer token"),)


def _config(*, maximum_attempts: int = 4) -> RuntimeTransferConfig:
    maximum = 16 * 1024 * 1024
    return RuntimeTransferConfig(
        per_runtime_attempts=maximum_attempts,
        per_runtime_bytes=maximum,
        deployment_attempts=maximum_attempts,
        deployment_bytes=maximum,
        admission_lease=timedelta(minutes=5),
        consumer_lease=timedelta(minutes=1),
        stream_lease=timedelta(seconds=30),
        terminal_ttl=timedelta(minutes=5),
        list_page_size=10,
    )
