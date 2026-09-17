"""HTTP response lifecycle for bounded file downloads."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

from fastapi.responses import StreamingResponse
from starlette.types import Message, Receive, Scope, Send


class DownloadResponseStream(Protocol):
    """Response-scoped stream with explicit terminal lifecycle."""

    @property
    def eof_reached(self) -> bool:
        """Return whether the source reached verified EOF."""
        ...

    def __aiter__(self) -> AsyncIterator[bytes]:
        """Return the single-use response body iterator."""
        ...

    async def complete(self) -> None:
        """Commit successful source consumption."""
        ...

    async def abandon(self) -> None:
        """Abandon unsuccessful source consumption."""
        ...

    async def aclose(self) -> None:
        """Close the underlying source."""
        ...


async def _await_cleanup(operation: Callable[[], Awaitable[None]]) -> None:
    """Run one cleanup operation to completion despite request cancellation."""

    async def run_operation() -> None:
        await operation()

    task = asyncio.create_task(run_operation())
    while True:
        try:
            await asyncio.shield(task)
            return
        except asyncio.CancelledError:
            if task.done():
                await task
                return


class FileDownloadResponse(StreamingResponse):
    """StreamingResponse with explicit EOF, final-send, and cleanup semantics."""

    def __init__(
        self,
        stream: DownloadResponseStream,
        *,
        media_type: str,
        headers: dict[str, str],
    ) -> None:
        self.download_stream = stream
        self.final_send_succeeded = False
        super().__init__(stream, media_type=media_type, headers=headers)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve the stream and commit or abandon its terminal outcome exactly once."""

        async def tracked_send(message: Message) -> None:
            await send(message)
            if message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                self.final_send_succeeded = True

        primary_error: BaseException | None = None
        try:
            await super().__call__(scope, receive, tracked_send)
        except BaseException as error:
            primary_error = error
        terminal_error: BaseException | None = None
        try:
            if self.download_stream.eof_reached and self.final_send_succeeded:
                try:
                    await _await_cleanup(self.download_stream.complete)
                except BaseException as error:
                    terminal_error = error
            else:
                try:
                    await _await_cleanup(self.download_stream.abandon)
                except BaseException as error:
                    terminal_error = error
        finally:
            try:
                await _await_cleanup(self.download_stream.aclose)
            except BaseException as error:
                if terminal_error is None:
                    terminal_error = error

        if primary_error is not None:
            raise primary_error
        if terminal_error is not None:
            raise terminal_error
