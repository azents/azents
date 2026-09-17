"""Bounded, single-use object-storage download streams."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Literal, Protocol


class DownloadStreamError(RuntimeError):
    """Raised when a bounded download stream cannot verify its source."""


class DownloadStreamTerminal(Protocol):
    """Terminal operations owned by one response-scoped download."""

    async def complete(self) -> None:
        """Commit successful response consumption."""
        ...

    async def abandon(self) -> None:
        """Abort unsuccessful response consumption."""
        ...


async def _noop_terminal_action() -> None:
    """Complete a source that has no external terminal authority."""


class BoundedDownloadStream:
    """Consume one bounded object iterator and verify its exact manifest."""

    def __init__(
        self,
        *,
        source_context: AbstractAsyncContextManager[AsyncIterator[bytes]],
        source_iterator: AsyncIterator[bytes],
        expected_size: int,
        expected_sha256: str,
        maximum_chunk_size: int,
        before_read: Callable[[], Awaitable[None]] | None = None,
        on_complete: Callable[[], Awaitable[None]] = _noop_terminal_action,
        on_abandon: Callable[[], Awaitable[None]] = _noop_terminal_action,
    ) -> None:
        if expected_size < 0:
            raise ValueError("expected_size must not be negative")
        if len(expected_sha256) != 64:
            raise ValueError("expected_sha256 must contain 64 hexadecimal characters")
        try:
            int(expected_sha256, 16)
        except ValueError as error:
            raise ValueError(
                "expected_sha256 must contain 64 hexadecimal characters"
            ) from error
        if maximum_chunk_size <= 0:
            raise ValueError("maximum_chunk_size must be positive")
        self.source_context = source_context
        self.source_iterator = source_iterator
        self.expected_size = expected_size
        self.expected_sha256 = expected_sha256
        self.maximum_chunk_size = maximum_chunk_size
        self.before_read = before_read
        self.on_complete = on_complete
        self.on_abandon = on_abandon
        self._observed_size = 0
        self._digest = hashlib.sha256()
        self._eof_reached = False
        self._source_closed = False
        self._iterator_started = False
        self._state: Literal[
            "active", "committing", "completed", "abandoning", "abandoned"
        ] = "active"
        self._terminal_lock = asyncio.Lock()
        self._completion_task: asyncio.Task[None] | None = None
        self._abandon_task: asyncio.Task[None] | None = None

    @property
    def eof_reached(self) -> bool:
        """Return whether the exact source manifest reached EOF."""
        return self._eof_reached

    def __aiter__(self) -> BoundedDownloadStream:
        """Return this single-use async iterator."""
        if self._iterator_started:
            raise DownloadStreamError("Download stream cannot be replayed")
        self._iterator_started = True
        return self

    async def __anext__(self) -> bytes:
        """Read and verify one bounded source chunk."""
        if self._eof_reached:
            raise StopAsyncIteration
        try:
            if self.before_read is not None:
                await self.before_read()
            chunk = await self.source_iterator.__anext__()
        except StopAsyncIteration:
            await self._close_source()
            self._validate_eof()
            self._eof_reached = True
            raise
        except BaseException:
            await self._close_source()
            raise

        if not isinstance(chunk, bytes | bytearray | memoryview):
            await self._close_source()
            raise DownloadStreamError("Download source yielded a non-byte chunk")
        chunk_bytes = bytes(chunk)
        if not chunk_bytes:
            await self._close_source()
            raise DownloadStreamError("Download source yielded an empty chunk")
        if len(chunk_bytes) > self.maximum_chunk_size:
            await self._close_source()
            raise DownloadStreamError("Download source yielded an oversized chunk")
        next_size = self._observed_size + len(chunk_bytes)
        if next_size > self.expected_size:
            await self._close_source()
            raise DownloadStreamError("Download source exceeded its expected size")
        self._observed_size = next_size
        self._digest.update(chunk_bytes)
        return chunk_bytes

    async def complete(self) -> None:
        """Commit the stream after exact EOF and final response send."""
        if not self._eof_reached:
            raise DownloadStreamError("Download stream has not reached verified EOF")
        async with self._terminal_lock:
            if self._state == "completed":
                return
            if self._state in {"abandoning", "abandoned"}:
                raise DownloadStreamError("Download stream was abandoned")
            if self._completion_task is None:
                self._state = "committing"
                self._completion_task = asyncio.create_task(self._run_complete_action())
            task = self._completion_task
        await asyncio.shield(task)
        async with self._terminal_lock:
            if task.done() and task.exception() is None:
                self._state = "completed"

    async def abandon(self) -> None:
        """Abort the stream and invoke its unsuccessful terminal action once."""
        async with self._terminal_lock:
            if self._state in {"completed", "committing"}:
                return
            if self._state == "abandoned":
                return
            if self._abandon_task is None:
                self._state = "abandoning"
                self._abandon_task = asyncio.create_task(self._abandon_impl())
            task = self._abandon_task
        await asyncio.shield(task)
        async with self._terminal_lock:
            if task.done() and task.exception() is None:
                self._state = "abandoned"

    async def aclose(self) -> None:
        """Close the source without changing its terminal outcome."""
        await self._close_source()

    async def _run_complete_action(self) -> None:
        """Invoke the successful terminal action in a concrete coroutine."""
        await self.on_complete()

    async def _abandon_impl(self) -> None:
        """Close the source before invoking the unsuccessful terminal action."""
        source_error: BaseException | None = None
        try:
            await self._close_source()
        except BaseException as error:
            source_error = error
        try:
            await self.on_abandon()
        finally:
            if source_error is not None:
                raise source_error

    async def _close_source(self) -> None:
        """Close the owned source context at most once."""
        if self._source_closed:
            return
        self._source_closed = True
        await self.source_context.__aexit__(None, None, None)

    def _validate_eof(self) -> None:
        """Require exact source size and SHA-256 at normal EOF."""
        if self._observed_size != self.expected_size:
            raise DownloadStreamError("Download source ended before its expected size")
        if self._digest.hexdigest() != self.expected_sha256:
            raise DownloadStreamError("Download source SHA-256 did not match")
