"""Typed authenticated data-stream client for one Runtime Web tunnel."""

import asyncio
import contextlib
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Sequence
from typing import TYPE_CHECKING, Protocol, assert_never

import grpc

from azents_runtime_control.grpc_runner_client import (
    runner_web_identity_from_message,
    runner_web_identity_to_message,
)
from azents_runtime_control.grpc_tls import GrpcClientTlsConfig, create_grpc_aio_channel
from azents_runtime_control.proto import runtime_web_transport_pb2
from azents_runtime_control.runner_web import (
    MAX_RUNTIME_WEB_FRAME_BYTES,
    RunnerWebBodyChunk,
    RunnerWebCancel,
    RunnerWebCancelReason,
    RunnerWebControlFrame,
    RunnerWebControlFrameHandler,
    RunnerWebEventFrame,
    RunnerWebHeader,
    RunnerWebHeartbeat,
    RunnerWebHeartbeatAcknowledgement,
    RunnerWebIdentity,
    RunnerWebProtocol,
    RunnerWebRequestHead,
    RunnerWebResponseHead,
    RunnerWebSocketFrame,
    RunnerWebSocketOpcode,
    RunnerWebStreamAccepted,
    RunnerWebStreamEnd,
    RunnerWebStreamError,
    RunnerWebStreamErrorCode,
)

if TYPE_CHECKING:
    from azents_runtime_control.proto.runtime_web_transport_pb2_grpc import (
        RuntimeRunnerWebAsyncStub as _RuntimeRunnerWebStub,
    )
else:
    from azents_runtime_control.proto.runtime_web_transport_pb2_grpc import (
        RuntimeRunnerWebStub as _RuntimeRunnerWebStub,
    )

_DEFAULT_PENDING_BYTES = 256 * 1024
_MAX_OUTBOUND_MESSAGES = _DEFAULT_PENDING_BYTES // MAX_RUNTIME_WEB_FRAME_BYTES
_LOCAL_SUBCHANNEL_POOL = (("grpc.use_local_subchannel_pool", 1),)


class RunnerWebStream(Protocol):
    """Callable gRPC stream constructor for one independently owned tunnel."""

    def __call__(
        self,
        request_iterator: AsyncIterator[runtime_web_transport_pb2.RunnerWebMessage],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_web_transport_pb2.RunnerWebControlMessage]: ...


class RuntimeRunnerWebStreamClosed(RuntimeError):
    """Runtime Web gRPC stream closed before tunnel completion."""


class GrpcRunnerWebClient:
    """Own one independently pooled authenticated Runtime Web data stream."""

    def __init__(
        self,
        stream: RunnerWebStream,
        *,
        runner_auth_token: str,
        channel: grpc.aio.Channel | None = None,
    ) -> None:
        if not runner_auth_token:
            raise ValueError("Runner authentication token must not be empty")
        self.stream = stream
        self.channel = channel
        self.metadata = (("authorization", f"Bearer {runner_auth_token}"),)
        self.outbound: asyncio.Queue[
            runtime_web_transport_pb2.RunnerWebMessage | None
        ] = asyncio.Queue(maxsize=_MAX_OUTBOUND_MESSAGES)
        self.control_handler: RunnerWebControlFrameHandler | None = None
        self.accepted: asyncio.Future[RunnerWebStreamAccepted] | None = None
        self.receiver_task: asyncio.Task[None] | None = None
        self.finished = False

    @classmethod
    def from_endpoint(
        cls,
        endpoint: str,
        *,
        runner_auth_token: str,
        tls: GrpcClientTlsConfig | None,
        allow_insecure: bool,
    ) -> "GrpcRunnerWebClient":
        channel = create_grpc_aio_channel(
            endpoint,
            tls=tls,
            allow_insecure=allow_insecure,
            options=_LOCAL_SUBCHANNEL_POOL,
        )
        return cls(
            _RuntimeRunnerWebStub(channel).ConnectWeb,
            runner_auth_token=runner_auth_token,
            channel=channel,
        )

    def set_control_handler(self, handler: RunnerWebControlFrameHandler) -> None:
        self.control_handler = handler

    async def start(self, identity: RunnerWebIdentity) -> RunnerWebStreamAccepted:
        if self.accepted is not None:
            raise RuntimeError("Runtime Web stream is already registered")
        self.accepted = asyncio.get_running_loop().create_future()
        responses = self.stream(
            self._outbound_messages(_registration_message(identity)),
            metadata=self.metadata,
        )
        self.receiver_task = asyncio.create_task(self._receive(responses))
        return await self.accepted

    async def send(self, frame: RunnerWebEventFrame) -> None:
        if self.finished:
            raise RuntimeError("Runtime Web stream is already finished")
        if self.receiver_task is not None and self.receiver_task.done():
            raise RuntimeRunnerWebStreamClosed("Runtime Web stream is closed")
        await self.outbound.put(runner_web_event_to_message(frame))

    async def finish(self, frame: RunnerWebEventFrame) -> None:
        if self.finished:
            raise RuntimeError("Runtime Web stream is already finished")
        if self.receiver_task is None:
            raise RuntimeError("Runtime Web stream is not registered")
        self.finished = True
        await self.outbound.put(runner_web_event_to_message(frame))
        await self.outbound.join()
        await self.outbound.put(None)
        await self.receiver_task

    async def close(self) -> None:
        if self.receiver_task is not None:
            self.receiver_task.cancel()
            with contextlib.suppress(
                asyncio.CancelledError,
                RuntimeRunnerWebStreamClosed,
                grpc.aio.AioRpcError,
            ):
                await self.receiver_task
            self.receiver_task = None
        if self.channel is not None:
            await self.channel.close()
            self.channel = None

    async def _outbound_messages(
        self,
        registration: runtime_web_transport_pb2.RunnerWebMessage,
    ) -> AsyncIterator[runtime_web_transport_pb2.RunnerWebMessage]:
        yield registration
        while True:
            message = await self.outbound.get()
            if message is None:
                self.outbound.task_done()
                return
            try:
                yield message
            finally:
                self.outbound.task_done()

    async def _receive(
        self,
        responses: AsyncIterable[runtime_web_transport_pb2.RunnerWebControlMessage],
    ) -> None:
        try:
            async for message in responses:
                payload = message.WhichOneof("payload")
                if payload == "accepted":
                    accepted = RunnerWebStreamAccepted(
                        tunnel_id=message.accepted.tunnel_id
                    )
                    if self.accepted is not None and not self.accepted.done():
                        self.accepted.set_result(accepted)
                    continue
                if self.control_handler is None:
                    raise RuntimeRunnerWebStreamClosed(
                        "Runtime Web control handler is not registered"
                    )
                await self.control_handler(runner_web_control_from_message(message))
            self._fail_pending(RuntimeRunnerWebStreamClosed("stream closed"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_pending(exc)
            raise

    def _fail_pending(self, exc: Exception) -> None:
        if self.accepted is not None and not self.accepted.done():
            self.accepted.set_exception(exc)


def runner_web_control_from_message(
    message: runtime_web_transport_pb2.RunnerWebControlMessage,
) -> RunnerWebControlFrame:
    payload = message.WhichOneof("payload")
    if payload == "request_head":
        return RunnerWebRequestHead(
            identity=runner_web_identity_from_message(message.request_head.identity),
            protocol=_protocol_from_message(message.request_head.protocol),
            method=bytes(message.request_head.method),
            target=bytes(message.request_head.target),
            headers=_headers_from_message(message.request_head.headers),
        )
    if payload == "body":
        return RunnerWebBodyChunk(message.body.sequence, bytes(message.body.data))
    if payload == "end":
        return RunnerWebStreamEnd(message.end.final_sequence)
    if payload == "websocket":
        return _websocket_from_message(message.websocket)
    if payload == "heartbeat":
        return RunnerWebHeartbeat(message.heartbeat.monotonic_sequence)
    if payload == "heartbeat_ack":
        return RunnerWebHeartbeatAcknowledgement(
            message.heartbeat_ack.monotonic_sequence
        )
    if payload == "cancel":
        return RunnerWebCancel(_cancel_reason_from_message(message.cancel.reason))
    if payload == "error":
        return RunnerWebStreamError(_error_code_from_message(message.error.code))
    raise ValueError("Runner Web control payload is invalid")


def runner_web_control_to_message(
    frame: RunnerWebControlFrame,
) -> runtime_web_transport_pb2.RunnerWebControlMessage:
    match frame:
        case RunnerWebRequestHead(
            identity=identity,
            protocol=protocol,
            method=method,
            target=target,
            headers=headers,
        ):
            return runtime_web_transport_pb2.RunnerWebControlMessage(
                request_head=runtime_web_transport_pb2.RuntimeWebRequestHead(
                    identity=runner_web_identity_to_message(identity),
                    protocol=_protocol_to_message(protocol),
                    method=method,
                    target=target,
                    headers=_headers_to_message(headers),
                )
            )
        case RunnerWebBodyChunk(sequence=sequence, data=data):
            return runtime_web_transport_pb2.RunnerWebControlMessage(
                body=runtime_web_transport_pb2.RuntimeWebBodyChunk(
                    sequence=sequence, data=data
                )
            )
        case RunnerWebStreamEnd(final_sequence=final_sequence):
            return runtime_web_transport_pb2.RunnerWebControlMessage(
                end=runtime_web_transport_pb2.RuntimeWebStreamEnd(
                    final_sequence=final_sequence
                )
            )
        case RunnerWebSocketFrame() as websocket:
            return runtime_web_transport_pb2.RunnerWebControlMessage(
                websocket=_websocket_to_message(websocket)
            )
        case RunnerWebHeartbeat(monotonic_sequence=sequence):
            return runtime_web_transport_pb2.RunnerWebControlMessage(
                heartbeat=runtime_web_transport_pb2.RuntimeWebHeartbeat(
                    monotonic_sequence=sequence
                )
            )
        case RunnerWebHeartbeatAcknowledgement(monotonic_sequence=sequence):
            return runtime_web_transport_pb2.RunnerWebControlMessage(
                heartbeat_ack=(
                    runtime_web_transport_pb2.RuntimeWebHeartbeatAcknowledgement(
                        monotonic_sequence=sequence
                    )
                )
            )
        case RunnerWebCancel(reason=reason):
            return runtime_web_transport_pb2.RunnerWebControlMessage(
                cancel=runtime_web_transport_pb2.RuntimeWebCancel(
                    reason=_cancel_reason_to_message(reason)
                )
            )
        case RunnerWebStreamError(code=code):
            return runtime_web_transport_pb2.RunnerWebControlMessage(
                error=runtime_web_transport_pb2.RuntimeWebStreamError(
                    code=_error_code_to_message(code)
                )
            )
        case _ as unreachable:
            assert_never(unreachable)


def runner_web_event_from_message(
    message: runtime_web_transport_pb2.RunnerWebMessage,
) -> RunnerWebEventFrame:
    payload = message.WhichOneof("payload")
    if payload == "response_head":
        return RunnerWebResponseHead(
            status=message.response_head.status,
            headers=_headers_from_message(message.response_head.headers),
        )
    if payload == "body":
        return RunnerWebBodyChunk(message.body.sequence, bytes(message.body.data))
    if payload == "end":
        return RunnerWebStreamEnd(message.end.final_sequence)
    if payload == "websocket":
        return _websocket_from_message(message.websocket)
    if payload == "heartbeat":
        return RunnerWebHeartbeat(message.heartbeat.monotonic_sequence)
    if payload == "heartbeat_ack":
        return RunnerWebHeartbeatAcknowledgement(
            message.heartbeat_ack.monotonic_sequence
        )
    if payload == "error":
        return RunnerWebStreamError(_error_code_from_message(message.error.code))
    raise ValueError("Runner Web event payload is invalid")


def runner_web_event_to_message(
    frame: RunnerWebEventFrame,
) -> runtime_web_transport_pb2.RunnerWebMessage:
    match frame:
        case RunnerWebResponseHead(status=status, headers=headers):
            return runtime_web_transport_pb2.RunnerWebMessage(
                response_head=runtime_web_transport_pb2.RuntimeWebResponseHead(
                    status=status,
                    headers=_headers_to_message(headers),
                )
            )
        case RunnerWebBodyChunk(sequence=sequence, data=data):
            return runtime_web_transport_pb2.RunnerWebMessage(
                body=runtime_web_transport_pb2.RuntimeWebBodyChunk(
                    sequence=sequence, data=data
                )
            )
        case RunnerWebStreamEnd(final_sequence=final_sequence):
            return runtime_web_transport_pb2.RunnerWebMessage(
                end=runtime_web_transport_pb2.RuntimeWebStreamEnd(
                    final_sequence=final_sequence
                )
            )
        case RunnerWebSocketFrame() as websocket:
            return runtime_web_transport_pb2.RunnerWebMessage(
                websocket=_websocket_to_message(websocket)
            )
        case RunnerWebHeartbeat(monotonic_sequence=sequence):
            return runtime_web_transport_pb2.RunnerWebMessage(
                heartbeat=runtime_web_transport_pb2.RuntimeWebHeartbeat(
                    monotonic_sequence=sequence
                )
            )
        case RunnerWebHeartbeatAcknowledgement(monotonic_sequence=sequence):
            return runtime_web_transport_pb2.RunnerWebMessage(
                heartbeat_ack=(
                    runtime_web_transport_pb2.RuntimeWebHeartbeatAcknowledgement(
                        monotonic_sequence=sequence
                    )
                )
            )
        case RunnerWebStreamError(code=code):
            return runtime_web_transport_pb2.RunnerWebMessage(
                error=runtime_web_transport_pb2.RuntimeWebStreamError(
                    code=_error_code_to_message(code)
                )
            )
        case _ as unreachable:
            assert_never(unreachable)


def _registration_message(
    identity: RunnerWebIdentity,
) -> runtime_web_transport_pb2.RunnerWebMessage:
    return runtime_web_transport_pb2.RunnerWebMessage(
        register=runtime_web_transport_pb2.RunnerWebRegistration(
            identity=runner_web_identity_to_message(identity)
        )
    )


def _headers_from_message(
    headers: Iterable[runtime_web_transport_pb2.RuntimeWebHeader],
) -> tuple[RunnerWebHeader, ...]:
    return tuple(
        RunnerWebHeader(name=bytes(header.name), value=bytes(header.value))
        for header in headers
    )


def _headers_to_message(
    headers: tuple[RunnerWebHeader, ...],
) -> list[runtime_web_transport_pb2.RuntimeWebHeader]:
    return [
        runtime_web_transport_pb2.RuntimeWebHeader(
            name=header.name,
            value=header.value,
        )
        for header in headers
    ]


def _protocol_from_message(
    value: runtime_web_transport_pb2.RuntimeWebProtocol.ValueType,
) -> RunnerWebProtocol:
    return {
        runtime_web_transport_pb2.RUNTIME_WEB_PROTOCOL_HTTP: RunnerWebProtocol.HTTP,
        runtime_web_transport_pb2.RUNTIME_WEB_PROTOCOL_WEBSOCKET: (
            RunnerWebProtocol.WEBSOCKET
        ),
    }[value]


def _protocol_to_message(
    protocol: RunnerWebProtocol,
) -> runtime_web_transport_pb2.RuntimeWebProtocol.ValueType:
    return {
        RunnerWebProtocol.HTTP: runtime_web_transport_pb2.RUNTIME_WEB_PROTOCOL_HTTP,
        RunnerWebProtocol.WEBSOCKET: (
            runtime_web_transport_pb2.RUNTIME_WEB_PROTOCOL_WEBSOCKET
        ),
    }[protocol]


def _websocket_from_message(
    message: runtime_web_transport_pb2.RuntimeWebSocketFrame,
) -> RunnerWebSocketFrame:
    return RunnerWebSocketFrame(
        sequence=message.sequence,
        opcode={
            runtime_web_transport_pb2.RUNTIME_WEB_SOCKET_OPCODE_TEXT: (
                RunnerWebSocketOpcode.TEXT
            ),
            runtime_web_transport_pb2.RUNTIME_WEB_SOCKET_OPCODE_BINARY: (
                RunnerWebSocketOpcode.BINARY
            ),
            runtime_web_transport_pb2.RUNTIME_WEB_SOCKET_OPCODE_PING: (
                RunnerWebSocketOpcode.PING
            ),
            runtime_web_transport_pb2.RUNTIME_WEB_SOCKET_OPCODE_PONG: (
                RunnerWebSocketOpcode.PONG
            ),
            runtime_web_transport_pb2.RUNTIME_WEB_SOCKET_OPCODE_CLOSE: (
                RunnerWebSocketOpcode.CLOSE
            ),
        }[message.opcode],
        final=message.final,
        data=bytes(message.data),
    )


def _websocket_to_message(
    frame: RunnerWebSocketFrame,
) -> runtime_web_transport_pb2.RuntimeWebSocketFrame:
    return runtime_web_transport_pb2.RuntimeWebSocketFrame(
        sequence=frame.sequence,
        opcode={
            RunnerWebSocketOpcode.TEXT: (
                runtime_web_transport_pb2.RUNTIME_WEB_SOCKET_OPCODE_TEXT
            ),
            RunnerWebSocketOpcode.BINARY: (
                runtime_web_transport_pb2.RUNTIME_WEB_SOCKET_OPCODE_BINARY
            ),
            RunnerWebSocketOpcode.PING: (
                runtime_web_transport_pb2.RUNTIME_WEB_SOCKET_OPCODE_PING
            ),
            RunnerWebSocketOpcode.PONG: (
                runtime_web_transport_pb2.RUNTIME_WEB_SOCKET_OPCODE_PONG
            ),
            RunnerWebSocketOpcode.CLOSE: (
                runtime_web_transport_pb2.RUNTIME_WEB_SOCKET_OPCODE_CLOSE
            ),
        }[frame.opcode],
        final=frame.final,
        data=frame.data,
    )


def _cancel_reason_from_message(
    value: runtime_web_transport_pb2.RuntimeWebCancelReason.ValueType,
) -> RunnerWebCancelReason:
    return RunnerWebCancelReason(
        {
            runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_CALLER: "caller",
            runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_APPROVAL_EXPIRED: (
                "approval_expired"
            ),
            runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_AUTHORITY_REVOKED: (
                "authority_revoked"
            ),
            runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_RUNTIME_REPLACED: (
                "runtime_replaced"
            ),
            runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_DEADLINE: "deadline",
            runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_SHUTDOWN: "shutdown",
            runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_PROTOCOL_VIOLATION: (
                "protocol_violation"
            ),
        }[value]
    )


def _cancel_reason_to_message(
    reason: RunnerWebCancelReason,
) -> runtime_web_transport_pb2.RuntimeWebCancelReason.ValueType:
    return {
        RunnerWebCancelReason.CALLER: (
            runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_CALLER
        ),
        RunnerWebCancelReason.APPROVAL_EXPIRED: (
            runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_APPROVAL_EXPIRED
        ),
        RunnerWebCancelReason.AUTHORITY_REVOKED: (
            runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_AUTHORITY_REVOKED
        ),
        RunnerWebCancelReason.RUNTIME_REPLACED: (
            runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_RUNTIME_REPLACED
        ),
        RunnerWebCancelReason.DEADLINE: (
            runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_DEADLINE
        ),
        RunnerWebCancelReason.SHUTDOWN: (
            runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_SHUTDOWN
        ),
        RunnerWebCancelReason.PROTOCOL_VIOLATION: (
            runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_PROTOCOL_VIOLATION
        ),
    }[reason]


def _error_code_from_message(
    value: runtime_web_transport_pb2.RuntimeWebStreamErrorCode.ValueType,
) -> RunnerWebStreamErrorCode:
    values = list(RunnerWebStreamErrorCode)
    if value <= 0 or value > len(values):
        raise ValueError("Runtime Web stream error code is invalid")
    return values[value - 1]


def _error_code_to_message(
    code: RunnerWebStreamErrorCode,
) -> runtime_web_transport_pb2.RuntimeWebStreamErrorCode.ValueType:
    return {
        RunnerWebStreamErrorCode.STALE_AUTHORITY: (
            runtime_web_transport_pb2.RUNTIME_WEB_STREAM_ERROR_CODE_STALE_AUTHORITY
        ),
        RunnerWebStreamErrorCode.STALE_RUNTIME_GENERATION: (
            runtime_web_transport_pb2.RUNTIME_WEB_STREAM_ERROR_CODE_STALE_RUNTIME_GENERATION
        ),
        RunnerWebStreamErrorCode.STALE_ROUTE: (
            runtime_web_transport_pb2.RUNTIME_WEB_STREAM_ERROR_CODE_STALE_ROUTE
        ),
        RunnerWebStreamErrorCode.DUPLICATE_JOIN: (
            runtime_web_transport_pb2.RUNTIME_WEB_STREAM_ERROR_CODE_DUPLICATE_JOIN
        ),
        RunnerWebStreamErrorCode.PROTOCOL_VIOLATION: (
            runtime_web_transport_pb2.RUNTIME_WEB_STREAM_ERROR_CODE_PROTOCOL_VIOLATION
        ),
        RunnerWebStreamErrorCode.RESOURCE_EXHAUSTED: (
            runtime_web_transport_pb2.RUNTIME_WEB_STREAM_ERROR_CODE_RESOURCE_EXHAUSTED
        ),
        RunnerWebStreamErrorCode.DEADLINE_EXCEEDED: (
            runtime_web_transport_pb2.RUNTIME_WEB_STREAM_ERROR_CODE_DEADLINE_EXCEEDED
        ),
        RunnerWebStreamErrorCode.APPLICATION_UNAVAILABLE: (
            runtime_web_transport_pb2.RUNTIME_WEB_STREAM_ERROR_CODE_APPLICATION_UNAVAILABLE
        ),
        RunnerWebStreamErrorCode.TRANSPORT_UNAVAILABLE: (
            runtime_web_transport_pb2.RUNTIME_WEB_STREAM_ERROR_CODE_TRANSPORT_UNAVAILABLE
        ),
    }[code]
