"""Typed authenticated Runner Transfer gRPC client."""

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
# Generated protobuf modules expose dynamic message attributes.

from collections.abc import AsyncIterator
from dataclasses import dataclass

import grpc

from azents_runtime_control.grpc_tls import (
    GrpcClientTlsConfig,
    create_grpc_aio_channel,
)
from azents_runtime_control.proto import (
    runtime_runner_transfer_pb2,
    runtime_runner_transfer_pb2_grpc,
)
from azents_runtime_control.runner_transfer import (
    RunnerTransferFailure,
    RunnerTransferIdentity,
)
from azents_runtime_control.transfer import MAX_TRANSFER_CHUNK_BYTES

_LOCAL_SUBCHANNEL_POOL = (("grpc.use_local_subchannel_pool", 1),)


@dataclass(frozen=True)
class RunnerDownloadChunk:
    """One bounded ordered download frame."""

    offset: int
    data: bytes


@dataclass(frozen=True)
class RunnerDownloadComplete:
    """Verified terminal manifest sent by Runtime Control."""

    actual_size: int
    sha256: str


@dataclass(frozen=True)
class RunnerUploadComplete:
    """Runner-observed upload manifest declaration."""

    actual_size: int
    sha256: str


@dataclass(frozen=True)
class RunnerUploadResult:
    """Authoritative completed upload manifest returned by Runtime Control."""

    actual_size: int
    sha256: str


class GrpcRunnerTransferClient:
    """Own one independently pooled authenticated Runner Transfer channel."""

    def __init__(
        self,
        stub: runtime_runner_transfer_pb2_grpc.RuntimeRunnerTransferStub,
        *,
        runner_auth_token: str,
        channel: grpc.aio.Channel | None = None,
    ) -> None:
        """Initialize one independently owned transfer client."""
        if not runner_auth_token:
            raise ValueError("Runner authentication token must not be empty")
        self._stub = stub
        self._channel = channel
        self._metadata = (("authorization", f"Bearer {runner_auth_token}"),)

    @classmethod
    def from_endpoint(
        cls,
        endpoint: str,
        *,
        runner_auth_token: str,
        tls: GrpcClientTlsConfig | None,
        allow_insecure: bool,
    ) -> "GrpcRunnerTransferClient":
        """Create a separately pooled authenticated Transfer channel."""
        channel = create_grpc_aio_channel(
            endpoint,
            tls=tls,
            allow_insecure=allow_insecure,
            options=_LOCAL_SUBCHANNEL_POOL,
        )
        return cls(
            runtime_runner_transfer_pb2_grpc.RuntimeRunnerTransferStub(channel),
            runner_auth_token=runner_auth_token,
            channel=channel,
        )

    async def download(
        self,
        identity: RunnerTransferIdentity,
        *,
        timeout: float,
    ) -> AsyncIterator[RunnerDownloadChunk | RunnerDownloadComplete]:
        """Yield bounded ordered data and one terminal download manifest."""
        if timeout <= 0:
            raise ValueError("Runner Transfer download timeout must be positive")
        request = runtime_runner_transfer_pb2.DownloadTransferRequest(
            identity=_identity_message(identity)
        )
        call = self._stub.DownloadTransfer(
            request,
            metadata=self._metadata,
            timeout=timeout,
        )
        async for frame in call:
            payload = frame.WhichOneof("payload")
            if payload == "chunk":
                yield RunnerDownloadChunk(
                    offset=frame.chunk.offset,
                    data=bytes(frame.chunk.data),
                )
                continue
            if (
                payload == "complete"
                and frame.complete.HasField("actual_size")
                and frame.complete.sha256
            ):
                yield RunnerDownloadComplete(
                    actual_size=frame.complete.actual_size,
                    sha256=frame.complete.sha256,
                )
                continue
            raise ValueError("Runner Transfer download frame is invalid")

    async def upload(
        self,
        identity: RunnerTransferIdentity,
        frames: AsyncIterator[RunnerDownloadChunk | RunnerUploadComplete],
        *,
        timeout: float,
    ) -> RunnerUploadResult:
        """Stream bounded upload frames and return the authoritative manifest."""
        if timeout <= 0:
            raise ValueError("Runner Transfer upload timeout must be positive")

        async def request_frames() -> AsyncIterator[
            runtime_runner_transfer_pb2.UploadTransferFrame
        ]:
            yield runtime_runner_transfer_pb2.UploadTransferFrame(
                open=runtime_runner_transfer_pb2.UploadTransferOpen(
                    identity=_identity_message(identity)
                )
            )
            async for frame in frames:
                if isinstance(frame, RunnerDownloadChunk):
                    if not frame.data or len(frame.data) > MAX_TRANSFER_CHUNK_BYTES:
                        raise ValueError(
                            "Runner upload chunk is outside protocol bounds"
                        )
                    yield runtime_runner_transfer_pb2.UploadTransferFrame(
                        chunk=runtime_runner_transfer_pb2.TransferChunk(
                            offset=frame.offset,
                            data=frame.data,
                        )
                    )
                    continue
                yield runtime_runner_transfer_pb2.UploadTransferFrame(
                    complete=runtime_runner_transfer_pb2.UploadTransferComplete(
                        actual_size=frame.actual_size,
                        sha256=frame.sha256,
                    )
                )

        result = await self._stub.UploadTransfer(
            request_frames(),
            metadata=self._metadata,
            timeout=timeout,
        )
        if (
            result.status
            != runtime_runner_transfer_pb2.UPLOAD_TRANSFER_STATUS_SUCCEEDED
            or not result.HasField("actual_size")
            or not result.sha256
        ):
            raise ValueError("Runner Transfer upload result is invalid")
        return RunnerUploadResult(
            actual_size=result.actual_size,
            sha256=result.sha256,
        )

    async def close(self) -> None:
        """Close only this independently owned data channel."""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None


def runner_transfer_failure_from_grpc(
    error: grpc.aio.AioRpcError,
) -> RunnerTransferFailure:
    """Map one data-RPC status to its closed Runner result classification."""
    return {
        grpc.StatusCode.UNAVAILABLE: RunnerTransferFailure.UNAVAILABLE,
        grpc.StatusCode.ALREADY_EXISTS: RunnerTransferFailure.ALREADY_CLAIMED,
        grpc.StatusCode.RESOURCE_EXHAUSTED: RunnerTransferFailure.RESOURCE_EXHAUSTED,
        grpc.StatusCode.DEADLINE_EXCEEDED: RunnerTransferFailure.DEADLINE_EXCEEDED,
        grpc.StatusCode.CANCELLED: RunnerTransferFailure.CANCELLED,
        grpc.StatusCode.DATA_LOSS: RunnerTransferFailure.INTEGRITY_FAILED,
        grpc.StatusCode.UNAUTHENTICATED: RunnerTransferFailure.PROTOCOL_VIOLATION,
        grpc.StatusCode.PERMISSION_DENIED: RunnerTransferFailure.PROTOCOL_VIOLATION,
        grpc.StatusCode.FAILED_PRECONDITION: (RunnerTransferFailure.PROTOCOL_VIOLATION),
    }.get(error.code(), RunnerTransferFailure.STREAM_FAILED)


def _identity_message(
    identity: RunnerTransferIdentity,
) -> runtime_runner_transfer_pb2.TransferIdentity:
    return runtime_runner_transfer_pb2.TransferIdentity(
        transfer_id=identity.transfer_id,
        attempt_id=identity.attempt_id,
        runtime_id=identity.runtime_id,
        runner_generation=identity.runner_generation,
    )


__all__ = [
    "GrpcRunnerTransferClient",
    "RunnerDownloadChunk",
    "RunnerDownloadComplete",
    "RunnerUploadComplete",
    "RunnerUploadResult",
    "runner_transfer_failure_from_grpc",
]
