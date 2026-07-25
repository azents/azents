"""Socket-level Runner Transfer tests with default gRPC message limits."""

# pyright: reportAttributeAccessIssue=false, reportUntypedBaseClass=false
# Protobuf generated modules expose dynamic message/RPC attributes.
# ruff: noqa: E501

import asyncio
import hashlib
from collections.abc import AsyncIterator
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
from azents_runtime_control.transfer import MAX_TRANSFER_CHUNK_BYTES

from azents.core.runtime_runner_credential import (
    RuntimeRunnerCredential,
    RuntimeRunnerCredentialInvalid,
)
from azents.runtime.control_protocol.data import RuntimeRunnerRegistration
from azents.runtime.control_protocol.grpc.runner_server import (
    RuntimeRunnerControlGrpcServicer,
)
from azents.runtime.control_protocol.grpc.runner_transfer_server import (
    RuntimeRunnerTransferGrpcServicer,
)
from azents.runtime.control_protocol.service import RuntimeControlProtocolService
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferObject,
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

    async def validate_runner_registration(
        self,
        registration: RuntimeRunnerRegistration,
    ) -> bool:
        del registration
        return True


class _ObjectStore:
    def __init__(self, download: bytes) -> None:
        self.download = download
        self.parts: list[bytes] = []
        self.uploads: dict[str, bytes] = {}

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
        del upload

    async def create_empty_immutable(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3VerifiedObject:
        del destination, transfer_metadata
        return object()  # type: ignore[return-value]


class _RecordingRunnerServicer(RuntimeRunnerControlGrpcServicer):
    def __init__(self, **kwargs: object) -> None:
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
                module_versions={"runtime.resources": 1},
                source_versions={"workspace": 1},
            ),
        ),
    )


async def _ready(
    state: InMemoryRuntimeTransferStateStore,
    direction: RuntimeTransferDirection,
    transfer_id: str,
    data: bytes,
) -> None:
    digest = hashlib.sha256(data).hexdigest()
    admission = RuntimeTransferAdmission(
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
    admitted = await state.admit(admission, lease_id=f"{transfer_id}-lease")
    assert admitted is not None
    ready = await state.mark_ready(
        transfer_id,
        attempt_id=admission.attempt_id,
        runtime_id="runtime-1",
        desired_generation=1,
        expected_revision=admitted.revision,
        object=RuntimeTransferObject(
            f"transfer-object:{transfer_id}", len(data), digest
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


def _metadata() -> tuple[tuple[str, str], ...]:
    return (("authorization", "Bearer token"),)


def _config() -> RuntimeTransferConfig:
    maximum = 16 * 1024 * 1024
    return RuntimeTransferConfig(
        per_runtime_attempts=4,
        per_runtime_bytes=maximum,
        deployment_attempts=4,
        deployment_bytes=maximum,
        admission_lease=timedelta(minutes=5),
        consumer_lease=timedelta(minutes=1),
        stream_lease=timedelta(seconds=30),
        terminal_ttl=timedelta(minutes=5),
        list_page_size=10,
    )
