"""Typed Gateway client for the isolated Runtime Web Control stream."""

import asyncio
import contextlib
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import grpc
from azents_runtime_control.grpc_runner_web_client import (
    runner_web_control_to_message,
    runner_web_event_from_message,
)
from azents_runtime_control.proto import runtime_web_transport_pb2
from azents_runtime_control.runner_web import (
    MAX_RUNTIME_WEB_FRAME_BYTES,
    RunnerWebControlFrame,
    RunnerWebEventFrame,
    RunnerWebRequestHead,
    RunnerWebStreamAccepted,
)

if TYPE_CHECKING:
    from azents_runtime_control.proto.runtime_web_transport_pb2_grpc import (
        RuntimeWebProxyAsyncStub as _RuntimeWebProxyStub,
    )
else:
    from azents_runtime_control.proto.runtime_web_transport_pb2_grpc import (
        RuntimeWebProxyStub as _RuntimeWebProxyStub,
    )

_QUEUE_BYTES = 256 * 1024
_QUEUE_MESSAGES = _QUEUE_BYTES // MAX_RUNTIME_WEB_FRAME_BYTES
_LOCAL_SUBCHANNEL_POOL = (("grpc.use_local_subchannel_pool", 1),)


class RuntimeWebProxyStream(Protocol):
    """Callable trusted Gateway stream constructor."""

    def __call__(
        self,
        request_iterator: AsyncIterator[runtime_web_transport_pb2.GatewayWebMessage],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_web_transport_pb2.GatewayWebMessage]: ...


class RuntimeWebProxyClosed(RuntimeError):
    """The trusted Control stream ended before application completion."""


class RuntimeWebProxySession:
    """One bounded, non-replayable Gateway request stream."""

    def __init__(self, stream: RuntimeWebProxyStream) -> None:
        self.stream = stream
        self.outbound: asyncio.Queue[
            runtime_web_transport_pb2.GatewayWebMessage | None
        ] = asyncio.Queue(maxsize=_QUEUE_MESSAGES)
        self.inbound: asyncio.Queue[RunnerWebEventFrame | Exception | None] = (
            asyncio.Queue(maxsize=_QUEUE_MESSAGES)
        )
        self.accepted: asyncio.Future[RunnerWebStreamAccepted] | None = None
        self.receiver: asyncio.Task[None] | None = None
        self.finished = False

    async def start(self, head: RunnerWebRequestHead) -> RunnerWebStreamAccepted:
        """Open the stream and wait until Control owns the tunnel."""
        if self.receiver is not None:
            raise RuntimeError("Runtime Web proxy session is already started")
        self.accepted = asyncio.get_running_loop().create_future()
        await self.outbound.put(_gateway_control_message(head))
        self.receiver = asyncio.create_task(
            self._receive(self.stream(self._outbound_messages())),
            name=f"runtime-web-gateway-proxy:{head.identity.tunnel_id}",
        )
        return await self.accepted

    async def send(self, frame: RunnerWebControlFrame) -> None:
        """Send one bounded request body or WebSocket control frame."""
        if self.receiver is None or self.finished:
            raise RuntimeWebProxyClosed("Runtime Web proxy session is not writable")
        if self.receiver.done():
            await self.receiver
            raise RuntimeWebProxyClosed("Runtime Web proxy session is closed")
        await self.outbound.put(_gateway_control_message(frame))

    async def finish_input(self) -> None:
        """Close the client-to-Control side after the final typed frame."""
        if self.finished:
            return
        self.finished = True
        await self.outbound.put(None)

    async def events(self) -> AsyncIterator[RunnerWebEventFrame]:
        """Yield application events with bounded backpressure."""
        while True:
            item = await self.inbound.get()
            try:
                if item is None:
                    return
                if isinstance(item, Exception):
                    raise item
                yield item
            finally:
                self.inbound.task_done()

    async def close(self) -> None:
        """Cancel unfinished transport and release local tasks."""
        await self.finish_input()
        if self.receiver is not None:
            if not self.receiver.done():
                self.receiver.cancel()
            with contextlib.suppress(
                asyncio.CancelledError,
                RuntimeWebProxyClosed,
                grpc.aio.AioRpcError,
            ):
                await self.receiver
            self.receiver = None

    async def _outbound_messages(
        self,
    ) -> AsyncIterator[runtime_web_transport_pb2.GatewayWebMessage]:
        while True:
            message = await self.outbound.get()
            try:
                if message is None:
                    return
                yield message
            finally:
                self.outbound.task_done()

    async def _receive(
        self,
        responses: AsyncIterable[runtime_web_transport_pb2.GatewayWebMessage],
    ) -> None:
        try:
            async for message in responses:
                if message.WhichOneof("payload") == "accepted":
                    accepted = RunnerWebStreamAccepted(
                        tunnel_id=message.accepted.tunnel_id
                    )
                    if self.accepted is not None and not self.accepted.done():
                        self.accepted.set_result(accepted)
                    continue
                await self.inbound.put(_gateway_event(message))
            error = RuntimeWebProxyClosed("Runtime Web proxy stream closed")
            self._fail_acceptance(error)
            await self.inbound.put(None)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._fail_acceptance(error)
            await self.inbound.put(error)
            await self.inbound.put(None)

    def _fail_acceptance(self, error: Exception) -> None:
        if self.accepted is not None and not self.accepted.done():
            self.accepted.set_exception(error)


class GrpcRuntimeWebProxyClient:
    """Shared mTLS channel that creates independently bounded request sessions."""

    def __init__(
        self,
        *,
        channel: grpc.aio.Channel,
    ) -> None:
        self.channel = channel
        self.stream = _RuntimeWebProxyStub(channel).Proxy

    @classmethod
    def from_endpoint(
        cls,
        endpoint: str,
        *,
        allow_insecure: bool,
        ca_file: Path | None,
        certificate_file: Path | None,
        private_key_file: Path | None,
    ) -> "GrpcRuntimeWebProxyClient":
        """Create a local insecure or production mTLS Control channel."""
        if allow_insecure:
            return cls(
                channel=grpc.aio.insecure_channel(
                    endpoint,
                    options=_LOCAL_SUBCHANNEL_POOL,
                )
            )
        if ca_file is None or certificate_file is None or private_key_file is None:
            raise RuntimeError("Runtime Web Gateway mTLS files are required")
        credentials = grpc.ssl_channel_credentials(
            root_certificates=ca_file.read_bytes(),
            private_key=private_key_file.read_bytes(),
            certificate_chain=certificate_file.read_bytes(),
        )
        return cls(
            channel=grpc.aio.secure_channel(
                endpoint,
                credentials,
                options=_LOCAL_SUBCHANNEL_POOL,
            )
        )

    def open(self) -> RuntimeWebProxySession:
        """Create one request-scoped stream state machine."""
        return RuntimeWebProxySession(self.stream)

    async def close(self) -> None:
        """Close the process-owned gRPC channel."""
        await self.channel.close()


def _gateway_control_message(
    frame: RunnerWebControlFrame,
) -> runtime_web_transport_pb2.GatewayWebMessage:
    message = runner_web_control_to_message(frame)
    payload = message.WhichOneof("payload")
    if payload == "request_head":
        return runtime_web_transport_pb2.GatewayWebMessage(
            request_head=message.request_head
        )
    if payload == "body":
        return runtime_web_transport_pb2.GatewayWebMessage(body=message.body)
    if payload == "end":
        return runtime_web_transport_pb2.GatewayWebMessage(end=message.end)
    if payload == "websocket":
        return runtime_web_transport_pb2.GatewayWebMessage(websocket=message.websocket)
    if payload == "heartbeat":
        return runtime_web_transport_pb2.GatewayWebMessage(heartbeat=message.heartbeat)
    if payload == "heartbeat_ack":
        return runtime_web_transport_pb2.GatewayWebMessage(
            heartbeat_ack=message.heartbeat_ack
        )
    if payload == "cancel":
        return runtime_web_transport_pb2.GatewayWebMessage(cancel=message.cancel)
    if payload == "error":
        return runtime_web_transport_pb2.GatewayWebMessage(error=message.error)
    raise ValueError("Runtime Web Gateway control frame is invalid")


def _gateway_event(
    message: runtime_web_transport_pb2.GatewayWebMessage,
) -> RunnerWebEventFrame:
    payload = message.WhichOneof("payload")
    if payload == "response_head":
        runner = runtime_web_transport_pb2.RunnerWebMessage(
            response_head=message.response_head
        )
    elif payload == "body":
        runner = runtime_web_transport_pb2.RunnerWebMessage(body=message.body)
    elif payload == "end":
        runner = runtime_web_transport_pb2.RunnerWebMessage(end=message.end)
    elif payload == "websocket":
        runner = runtime_web_transport_pb2.RunnerWebMessage(websocket=message.websocket)
    elif payload == "heartbeat":
        runner = runtime_web_transport_pb2.RunnerWebMessage(heartbeat=message.heartbeat)
    elif payload == "heartbeat_ack":
        runner = runtime_web_transport_pb2.RunnerWebMessage(
            heartbeat_ack=message.heartbeat_ack
        )
    elif payload == "error":
        runner = runtime_web_transport_pb2.RunnerWebMessage(error=message.error)
    else:
        raise ValueError("Runtime Web Gateway event frame is invalid")
    return runner_web_event_from_message(runner)
