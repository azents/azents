"""Runtime Runner loopback HTTP transport for approved Runtime Web tunnels."""

import asyncio
import contextlib
import dataclasses
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

import aiohttp
from azents_runtime_control.grpc_runner_web_client import GrpcRunnerWebClient
from azents_runtime_control.grpc_tls import GrpcClientTlsConfig
from azents_runtime_control.runner_web import (
    MAX_RUNTIME_WEB_FRAME_BYTES,
    MAX_RUNTIME_WEB_SOCKET_MESSAGE_BYTES,
    RunnerWebBodyChunk,
    RunnerWebCancel,
    RunnerWebCancelIntent,
    RunnerWebControlFrame,
    RunnerWebEventFrame,
    RunnerWebHeader,
    RunnerWebHeartbeat,
    RunnerWebHeartbeatAcknowledgement,
    RunnerWebIdentity,
    RunnerWebOpenIntent,
    RunnerWebProtocol,
    RunnerWebRequestHead,
    RunnerWebResponseHead,
    RunnerWebSocketFrame,
    RunnerWebSocketOpcode,
    RunnerWebStreamEnd,
    RunnerWebStreamError,
    RunnerWebStreamErrorCode,
)

_LOGGER = logging.getLogger(__name__)
_DEFAULT_PENDING_BYTES = 256 * 1024
_MAX_PENDING_CONTROL_FRAMES = _DEFAULT_PENDING_BYTES // MAX_RUNTIME_WEB_FRAME_BYTES
_WEBSOCKET_HANDSHAKE_HEADERS = frozenset(
    {
        "connection",
        "upgrade",
        "sec-websocket-accept",
        "sec-websocket-extensions",
        "sec-websocket-key",
        "sec-websocket-version",
    }
)


def _new_http_session() -> aiohttp.ClientSession:
    """Create a byte-preserving loopback HTTP client session."""
    return aiohttp.ClientSession(
        auto_decompress=False,
        skip_auto_headers={"Accept-Encoding", "User-Agent"},
    )


class RunnerWebClient(Protocol):
    """Dedicated Runner-to-Control stream used by one tunnel."""

    def set_control_handler(
        self,
        handler: Callable[[RunnerWebControlFrame], Awaitable[None]],
    ) -> None: ...

    async def start(self, identity: RunnerWebIdentity) -> object: ...

    async def send(self, frame: RunnerWebEventFrame) -> None: ...

    async def finish(self, frame: RunnerWebEventFrame) -> None: ...

    async def close(self) -> None: ...


RunnerWebClientFactory = Callable[[], RunnerWebClient]


@dataclasses.dataclass
class _Tunnel:
    """One active loopback request and its bounded inbound control queue."""

    identity: RunnerWebIdentity
    queue: asyncio.Queue[RunnerWebControlFrame]
    task: asyncio.Task[None] | None = None


class RunnerWebTransportManager:
    """Own exact-generation loopback transports without durable body storage."""

    def __init__(
        self,
        *,
        runtime_id: str,
        accepted_generation: Callable[[], int | None],
        client_factory: RunnerWebClientFactory,
        http_session_factory: Callable[[], aiohttp.ClientSession] = _new_http_session,
    ) -> None:
        self.runtime_id = runtime_id
        self.accepted_generation = accepted_generation
        self.client_factory = client_factory
        self.http_session_factory = http_session_factory
        self.tunnels: dict[str, _Tunnel] = {}
        self.lock = asyncio.Lock()

    @classmethod
    def from_endpoint(
        cls,
        *,
        endpoint: str,
        runner_auth_token: str,
        tls: GrpcClientTlsConfig | None,
        allow_insecure: bool,
        runtime_id: str,
        accepted_generation: Callable[[], int | None],
    ) -> "RunnerWebTransportManager":
        """Create a manager using independently pooled authenticated streams."""

        def client_factory() -> GrpcRunnerWebClient:
            return GrpcRunnerWebClient.from_endpoint(
                endpoint,
                runner_auth_token=runner_auth_token,
                tls=tls,
                allow_insecure=allow_insecure,
            )

        return cls(
            runtime_id=runtime_id,
            accepted_generation=accepted_generation,
            client_factory=client_factory,
        )

    async def handle_open(self, intent: RunnerWebOpenIntent) -> None:
        """Start one exact current-generation loopback transport."""
        if not self._identity_current(intent.identity):
            return
        tunnel = _Tunnel(
            identity=intent.identity,
            queue=asyncio.Queue(maxsize=_MAX_PENDING_CONTROL_FRAMES),
        )
        async with self.lock:
            existing = self.tunnels.get(intent.identity.tunnel_id)
            if existing is not None and existing.task is not None:
                if not existing.task.done():
                    return
            task = asyncio.create_task(
                self._run(tunnel),
                name=f"runner-web:{intent.identity.tunnel_id}",
            )
            tunnel.task = task
            self.tunnels[intent.identity.tunnel_id] = tunnel

    async def handle_cancel(self, intent: RunnerWebCancelIntent) -> None:
        """Cancel only the exact active tunnel identity."""
        async with self.lock:
            tunnel = self.tunnels.get(intent.identity.tunnel_id)
            task = None if tunnel is None else tunnel.task
            if tunnel is None or tunnel.identity != intent.identity:
                return
        if task is not None:
            task.cancel()

    async def invalidate_runtime(self) -> None:
        """Cancel all tunnels before accepting a replacement generation."""
        async with self.lock:
            tasks = tuple(
                tunnel.task
                for tunnel in self.tunnels.values()
                if tunnel.task is not None
            )
            self.tunnels.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        """Close every active Runtime Web transport."""
        await self.invalidate_runtime()

    async def _run(self, tunnel: _Tunnel) -> None:
        client = self.client_factory()

        async def receive(frame: RunnerWebControlFrame) -> None:
            if isinstance(frame, RunnerWebCancel):
                current = asyncio.current_task()
                task = tunnel.task
                if task is not None and task is not current:
                    task.cancel()
                return
            await tunnel.queue.put(frame)

        client.set_control_handler(receive)
        try:
            timeout = self._remaining(tunnel.identity.registration_deadline_at)
            await asyncio.wait_for(client.start(tunnel.identity), timeout=timeout)
            head = await asyncio.wait_for(
                tunnel.queue.get(),
                timeout=self._remaining(tunnel.identity.registration_deadline_at),
            )
            if not isinstance(head, RunnerWebRequestHead):
                raise ValueError("Runtime Web request head must be first")
            if head.identity != tunnel.identity:
                raise ValueError("Runtime Web request authority changed")
            if head.protocol is RunnerWebProtocol.HTTP:
                await self._run_http(client, tunnel, head)
            else:
                async with asyncio.timeout(
                    self._remaining(tunnel.identity.transport_deadline_at)
                ):
                    await self._run_websocket(client, tunnel, head)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            await self._finish_error(
                client,
                RunnerWebStreamErrorCode.DEADLINE_EXCEEDED,
            )
        except (aiohttp.ClientError, OSError) as error:
            error_number = getattr(error, "errno", None)
            if error_number is None:
                error_number = getattr(getattr(error, "os_error", None), "errno", None)
            _LOGGER.warning(
                "Runtime Web loopback application unavailable",
                extra={
                    "runtime_id": tunnel.identity.runtime_id,
                    "tunnel_id": tunnel.identity.tunnel_id,
                    "port": tunnel.identity.port,
                    "error_type": type(error).__name__,
                    "error_number": error_number,
                },
            )
            await self._finish_error(
                client,
                RunnerWebStreamErrorCode.APPLICATION_UNAVAILABLE,
            )
        except ValueError:
            await self._finish_error(
                client,
                RunnerWebStreamErrorCode.PROTOCOL_VIOLATION,
            )
        finally:
            await client.close()
            async with self.lock:
                if self.tunnels.get(tunnel.identity.tunnel_id) is tunnel:
                    self.tunnels.pop(tunnel.identity.tunnel_id, None)

    async def _run_http(
        self,
        client: RunnerWebClient,
        tunnel: _Tunnel,
        head: RunnerWebRequestHead,
    ) -> None:
        method = head.method.decode("ascii")
        target = head.target.decode("ascii")
        if not target.startswith("/") or target.startswith("//"):
            raise ValueError("Runtime Web target must be origin-form")
        url = f"http://127.0.0.1:{tunnel.identity.port}{target}"
        headers = [
            (header.name.decode("ascii"), header.value.decode("latin-1"))
            for header in head.headers
        ]
        timeout = aiohttp.ClientTimeout(
            total=self._remaining(tunnel.identity.transport_deadline_at)
        )
        async with self.http_session_factory() as session:
            async with session.request(
                method,
                url,
                headers=headers,
                data=self._request_body(tunnel),
                allow_redirects=False,
                timeout=timeout,
            ) as response:
                await client.send(
                    RunnerWebResponseHead(
                        status=response.status,
                        headers=tuple(
                            RunnerWebHeader(bytes(name), bytes(value))
                            for name, value in response.raw_headers
                        ),
                    )
                )
                sequence = 0
                async for data in response.content.iter_chunked(
                    MAX_RUNTIME_WEB_FRAME_BYTES
                ):
                    if not data:
                        continue
                    sequence += 1
                    await client.send(RunnerWebBodyChunk(sequence, data))
                await client.finish(RunnerWebStreamEnd(sequence))

    async def _run_websocket(
        self,
        client: RunnerWebClient,
        tunnel: _Tunnel,
        head: RunnerWebRequestHead,
    ) -> None:
        if head.method != b"GET":
            raise ValueError("Runtime WebSocket request method must be GET")
        target = head.target.decode("ascii")
        if not target.startswith("/") or target.startswith("//"):
            raise ValueError("Runtime WebSocket target must be origin-form")
        url = f"http://127.0.0.1:{tunnel.identity.port}{target}"
        headers = [
            (name, header.value.decode("latin-1"))
            for header in head.headers
            if (name := header.name.decode("ascii")).lower()
            not in _WEBSOCKET_HANDSHAKE_HEADERS
        ]
        timeout = aiohttp.ClientWSTimeout(
            ws_receive=self._remaining(  # ty: ignore[unknown-argument]
                tunnel.identity.transport_deadline_at
            ),
            ws_close=5.0,  # ty: ignore[unknown-argument]
        )
        async with self.http_session_factory() as session:
            async with session.ws_connect(
                url,
                headers=headers,
                timeout=timeout,
                autoclose=False,
                autoping=False,
            ) as websocket:
                await client.send(
                    RunnerWebResponseHead(
                        status=101,
                        headers=tuple(
                            RunnerWebHeader(
                                bytes(name),
                                bytes(value),
                            )
                            for name, value in websocket._response.raw_headers
                        ),
                    )
                )
                control_task = asyncio.create_task(
                    self._send_websocket_frames(client, tunnel, websocket)
                )
                application_task = asyncio.create_task(
                    self._receive_websocket_frames(client, websocket)
                )
                done, _pending = await asyncio.wait(
                    (control_task, application_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if application_task in done:
                    control_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await control_task
                    await application_task
                    return
                try:
                    await control_task
                except asyncio.CancelledError:
                    application_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await application_task
                    raise
                except Exception:
                    application_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await application_task
                    raise
                await application_task

    async def _send_websocket_frames(
        self,
        client: RunnerWebClient,
        tunnel: _Tunnel,
        websocket: aiohttp.ClientWebSocketResponse,
    ) -> None:
        expected = 1
        message_opcode: RunnerWebSocketOpcode | None = None
        message_data = bytearray()
        while True:
            frame = await tunnel.queue.get()
            if isinstance(frame, RunnerWebSocketFrame):
                if frame.sequence != expected:
                    raise ValueError("Runtime WebSocket input sequence is invalid")
                expected += 1
                if frame.opcode in {
                    RunnerWebSocketOpcode.PING,
                    RunnerWebSocketOpcode.PONG,
                    RunnerWebSocketOpcode.CLOSE,
                }:
                    if message_opcode is not None or not frame.final:
                        raise ValueError(
                            "Runtime WebSocket control frame cannot be fragmented"
                        )
                    await websocket.send_frame(
                        frame.data,
                        _aiohttp_websocket_type(frame.opcode),
                    )
                    if frame.opcode is RunnerWebSocketOpcode.CLOSE:
                        return
                    continue
                if message_opcode is None:
                    message_opcode = frame.opcode
                elif message_opcode is not frame.opcode:
                    raise ValueError("Runtime WebSocket fragment opcode changed")
                message_data.extend(frame.data)
                if len(message_data) > MAX_RUNTIME_WEB_SOCKET_MESSAGE_BYTES:
                    raise ValueError("Runtime WebSocket input message is too large")
                if not frame.final:
                    continue
                if message_opcode is RunnerWebSocketOpcode.TEXT:
                    bytes(message_data).decode("utf-8")
                await websocket.send_frame(
                    bytes(message_data),
                    _aiohttp_websocket_type(message_opcode),
                )
                message_opcode = None
                message_data.clear()
                continue
            if isinstance(frame, RunnerWebHeartbeat):
                await client.send(
                    RunnerWebHeartbeatAcknowledgement(frame.monotonic_sequence)
                )
                continue
            if isinstance(frame, RunnerWebHeartbeatAcknowledgement):
                continue
            if isinstance(frame, RunnerWebStreamEnd):
                if message_opcode is not None:
                    raise ValueError("Runtime WebSocket message ended mid-fragment")
                await websocket.close()
                return
            if isinstance(frame, RunnerWebStreamError):
                raise ValueError("Runtime Web peer closed the WebSocket")
            raise ValueError("Unexpected Runtime WebSocket control frame")

    async def _receive_websocket_frames(
        self,
        client: RunnerWebClient,
        websocket: aiohttp.ClientWebSocketResponse,
    ) -> None:
        sequence = 0
        close_sent = False
        async for message in websocket:
            opcode = {
                aiohttp.WSMsgType.TEXT: RunnerWebSocketOpcode.TEXT,
                aiohttp.WSMsgType.BINARY: RunnerWebSocketOpcode.BINARY,
                aiohttp.WSMsgType.PING: RunnerWebSocketOpcode.PING,
                aiohttp.WSMsgType.PONG: RunnerWebSocketOpcode.PONG,
                aiohttp.WSMsgType.CLOSE: RunnerWebSocketOpcode.CLOSE,
            }.get(message.type)
            if opcode is None:
                if message.type in {
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                }:
                    break
                if message.type is aiohttp.WSMsgType.ERROR:
                    raise aiohttp.ClientConnectionError(
                        "Runtime WebSocket application stream failed"
                    )
                raise ValueError("Unsupported Runtime WebSocket application frame")
            data = _websocket_message_data(message, opcode)
            frames = _websocket_frames(
                data=data,
                opcode=opcode,
                first_sequence=sequence + 1,
            )
            for frame in frames:
                await client.send(frame)
            sequence += len(frames)
            if opcode is RunnerWebSocketOpcode.CLOSE:
                close_sent = True
                break
        if not close_sent and websocket.close_code is not None:
            sequence += 1
            await client.send(
                RunnerWebSocketFrame(
                    sequence=sequence,
                    opcode=RunnerWebSocketOpcode.CLOSE,
                    final=True,
                    data=websocket.close_code.to_bytes(2, "big"),
                )
            )
        await client.finish(RunnerWebStreamEnd(sequence))

    async def _request_body(self, tunnel: _Tunnel) -> AsyncIterator[bytes]:
        expected = 1
        while True:
            frame = await tunnel.queue.get()
            if isinstance(frame, RunnerWebBodyChunk):
                if frame.sequence != expected:
                    raise ValueError("Runtime Web request body sequence is invalid")
                expected += 1
                yield frame.data
                continue
            if isinstance(frame, RunnerWebStreamEnd):
                if frame.final_sequence != expected - 1:
                    raise ValueError("Runtime Web request end sequence is invalid")
                return
            if isinstance(frame, RunnerWebHeartbeat):
                continue
            if isinstance(frame, RunnerWebHeartbeatAcknowledgement):
                continue
            if isinstance(frame, RunnerWebStreamError):
                raise ValueError("Runtime Web peer closed the request")
            if isinstance(frame, RunnerWebSocketFrame):
                raise ValueError("Unexpected WebSocket frame in HTTP request")
            if isinstance(frame, RunnerWebRequestHead):
                raise ValueError("Duplicate Runtime Web request head")
            raise ValueError("Unexpected Runtime Web request frame")

    async def _finish_error(
        self,
        client: RunnerWebClient,
        code: RunnerWebStreamErrorCode,
    ) -> None:
        await client.finish(RunnerWebStreamError(code))

    def _identity_current(self, identity: RunnerWebIdentity) -> bool:
        now = datetime.now(UTC)
        return (
            identity.runtime_id == self.runtime_id
            and self.accepted_generation() == identity.runner_generation
            and now < identity.registration_deadline_at
            and now < identity.approval_deadline_at
            and now < identity.transport_deadline_at
        )

    @staticmethod
    def _remaining(deadline: datetime) -> float:
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise TimeoutError
        return remaining


def _websocket_message_data(
    message: aiohttp.WSMessage,
    opcode: RunnerWebSocketOpcode,
) -> bytes:
    if opcode is RunnerWebSocketOpcode.TEXT:
        if not isinstance(message.data, str):
            raise ValueError("Runtime WebSocket text frame is invalid")
        return message.data.encode("utf-8")
    if opcode is RunnerWebSocketOpcode.CLOSE:
        if not isinstance(message.data, int) or not 0 <= message.data <= 65_535:
            raise ValueError("Runtime WebSocket close code is invalid")
        reason = message.extra
        if not isinstance(reason, str):
            raise ValueError("Runtime WebSocket close reason is invalid")
        return message.data.to_bytes(2, "big") + reason.encode("utf-8")
    if not isinstance(message.data, bytes):
        raise ValueError("Runtime WebSocket binary control frame is invalid")
    return message.data


def _aiohttp_websocket_type(opcode: RunnerWebSocketOpcode) -> aiohttp.WSMsgType:
    return {
        RunnerWebSocketOpcode.TEXT: aiohttp.WSMsgType.TEXT,
        RunnerWebSocketOpcode.BINARY: aiohttp.WSMsgType.BINARY,
        RunnerWebSocketOpcode.PING: aiohttp.WSMsgType.PING,
        RunnerWebSocketOpcode.PONG: aiohttp.WSMsgType.PONG,
        RunnerWebSocketOpcode.CLOSE: aiohttp.WSMsgType.CLOSE,
    }[opcode]


def _websocket_frames(
    *,
    data: bytes,
    opcode: RunnerWebSocketOpcode,
    first_sequence: int,
) -> tuple[RunnerWebSocketFrame, ...]:
    if len(data) > MAX_RUNTIME_WEB_SOCKET_MESSAGE_BYTES:
        raise ValueError("Runtime WebSocket application message is too large")
    if opcode in {
        RunnerWebSocketOpcode.PING,
        RunnerWebSocketOpcode.PONG,
        RunnerWebSocketOpcode.CLOSE,
    }:
        chunks = (data,)
    elif opcode is RunnerWebSocketOpcode.TEXT:
        text = data.decode("utf-8")
        chunks = _utf8_chunks(text)
    else:
        chunks = tuple(
            data[offset : offset + MAX_RUNTIME_WEB_FRAME_BYTES]
            for offset in range(0, len(data), MAX_RUNTIME_WEB_FRAME_BYTES)
        ) or (b"",)
    return tuple(
        RunnerWebSocketFrame(
            sequence=first_sequence + index,
            opcode=opcode,
            final=index == len(chunks) - 1,
            data=chunk,
        )
        for index, chunk in enumerate(chunks)
    )


def _utf8_chunks(text: str) -> tuple[bytes, ...]:
    encoded = text.encode("utf-8")
    if not encoded:
        return (b"",)
    chunks: list[bytes] = []
    offset = 0
    while offset < len(encoded):
        end = min(offset + MAX_RUNTIME_WEB_FRAME_BYTES, len(encoded))
        while end < len(encoded) and encoded[end] & 0xC0 == 0x80:
            end -= 1
        if end == offset:
            raise ValueError("Runtime WebSocket text cannot be fragmented safely")
        chunks.append(encoded[offset:end])
        offset = end
    return tuple(chunks)
