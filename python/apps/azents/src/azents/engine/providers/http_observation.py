"""Official HTTP SDK observation at a single-consumed public decoder boundary."""

import json
from collections.abc import AsyncIterator

import httpx2

from azents.core.type_guards import is_string_object_dict
from azents.engine.providers.observation_state import NativeObservationState

_MAX_FRAME_BYTES = 32 * 1024 * 1024


class NativeStreamFramingError(RuntimeError):
    """An input stream cannot be framed within the bounded observation contract."""


class NativeBodyFramer:
    """Observe SDK-decoded input bytes without retaining a raw frame history."""

    def __init__(
        self,
        *,
        state: NativeObservationState,
        sse: bool,
        status_code: int,
    ) -> None:
        self.state = state
        self.sse = sse
        self.status_code = status_code
        self.buffer = bytearray()

    async def feed(self, chunk: bytes) -> None:
        """Frame parsed events without claiming network bytes are progress."""
        self.buffer.extend(chunk)
        if len(self.buffer) > _MAX_FRAME_BYTES:
            raise NativeStreamFramingError(
                "The provider event exceeds the observation framing bound."
            ) from None
        if not self.sse:
            return
        while True:
            boundary = self.buffer.find(b"\n\n")
            crlf_boundary = self.buffer.find(b"\r\n\r\n")
            width = 2
            if crlf_boundary >= 0 and (boundary < 0 or crlf_boundary < boundary):
                boundary = crlf_boundary
                width = 4
            if boundary < 0:
                return
            frame = bytes(self.buffer[:boundary])
            del self.buffer[: boundary + width]
            data = b"\n".join(
                line[5:].lstrip()
                for line in frame.splitlines()
                if line.startswith(b"data:")
            )
            if data and data != b"[DONE]":
                await self._payload(data)

    async def finish(self) -> None:
        """A transport EOF is not synthetic successful completion evidence."""
        if not self.sse and self.buffer:
            await self._payload(bytes(self.buffer))
        self.buffer.clear()

    async def _payload(self, data: bytes) -> None:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError, UnicodeDecodeError:
            if self.status_code >= 400:
                self.state.retain_http_failure(status_code=self.status_code, body=None)
                return
            raise NativeStreamFramingError(
                "The provider stream contains invalid JSON."
            ) from None
        if not is_string_object_dict(payload):
            raise NativeStreamFramingError(
                "The provider stream event is not an object."
            ) from None
        if self.status_code >= 400:
            self.state.retain_http_failure(status_code=self.status_code, body=payload)
        await self.state.observe(payload)


class ObservedHTTPX2Stream(httpx2.AsyncByteStream):
    """Tee public decoded bytes while consuming the original body exactly once."""

    def __init__(
        self,
        *,
        source: httpx2.Response,
        framer: NativeBodyFramer,
    ) -> None:
        self.source = source
        self.framer = framer

    async def __aiter__(self) -> AsyncIterator[bytes]:
        # The supported Response decoder owns gzip/deflate/br/zstd handling.
        # Do not set a chunk_size: that would batch otherwise immediate native
        # events and change the existing parsed-event liveness policy.
        async for chunk in self.source.aiter_bytes():
            await self.framer.feed(chunk)
            yield chunk
        await self.framer.finish()

    async def aclose(self) -> None:
        await self.source.aclose()


class ObservedHTTPX2Transport(httpx2.AsyncBaseTransport):
    """Public middleware for all selected official asynchronous HTTP SDKs."""

    def __init__(
        self, *, delegate: httpx2.AsyncBaseTransport, state: NativeObservationState
    ) -> None:
        self.delegate = delegate
        self.state = state

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        await self.state.authorize_dispatch_with_admission()
        request.extensions["timeout"] = {
            "connect": self.state.timeout_policy.connect_timeout_seconds,
            "read": None,
            "write": None,
            "pool": None,
        }
        response = await self.delegate.handle_async_request(request)
        response.request = request
        self.state.acquired()
        self.state.response_retry_after = response.headers.get("retry-after")
        if response.status_code >= 400:
            self.state.retain_http_failure(status_code=response.status_code, body=None)
        if not isinstance(response.stream, httpx2.AsyncByteStream):
            raise TypeError("The official SDK response is not asynchronous.")
        # Decode through the original Response exactly once. The SDK consumes
        # those same decoded bytes; retaining wire encoding/length here would
        # make the outer Response decompress the content a second time.
        headers = [
            (name, value)
            for name, value in response.headers.multi_items()
            if name.lower() not in {"content-encoding", "content-length"}
        ]
        return httpx2.Response(
            response.status_code,
            headers=headers,
            request=request,
            extensions=dict(response.extensions),
            stream=ObservedHTTPX2Stream(
                source=response,
                framer=NativeBodyFramer(
                    state=self.state,
                    sse="text/event-stream" in response.headers.get("content-type", ""),
                    status_code=response.status_code,
                ),
            ),
        )

    async def aclose(self) -> None:
        await self.delegate.aclose()
