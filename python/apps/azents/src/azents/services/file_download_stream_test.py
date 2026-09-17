"""Tests for bounded, single-use object-storage download streams."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest

from azents.services.file_download_stream import (
    BoundedDownloadStream,
    DownloadStreamError,
)


@dataclass
class _SourceContext:
    """Track close ownership for one fake source context."""

    iterator: AsyncGenerator[bytes, None]
    close_calls: int = 0

    async def __aenter__(self) -> AsyncGenerator[bytes, None]:
        """Return the already-open source iterator."""
        return self.iterator

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Close the source and record the close operation."""
        del exc_type, exc, tb
        self.close_calls += 1


@dataclass
class _Terminal:
    """Record successful and unsuccessful terminal actions."""

    complete_calls: int = 0
    abandon_calls: int = 0

    async def complete(self) -> None:
        """Record successful completion."""
        self.complete_calls += 1

    async def abandon(self) -> None:
        """Record unsuccessful completion."""
        self.abandon_calls += 1


async def _chunks(values: list[bytes]) -> AsyncGenerator[bytes, None]:
    """Yield configured source chunks."""
    for value in values:
        yield value


def _stream(
    values: list[bytes],
    *,
    expected: bytes,
    maximum_chunk_size: int = 4,
    terminal: _Terminal | None = None,
) -> tuple[BoundedDownloadStream, _SourceContext, _Terminal]:
    """Build one bounded stream with deterministic source and terminal hooks."""
    selected_terminal = terminal or _Terminal()
    context = _SourceContext(_chunks(values))
    stream = BoundedDownloadStream(
        source_context=context,
        source_iterator=context.iterator,
        expected_size=len(expected),
        expected_sha256=hashlib.sha256(expected).hexdigest(),
        maximum_chunk_size=maximum_chunk_size,
        on_complete=selected_terminal.complete,
        on_abandon=selected_terminal.abandon,
    )
    return stream, context, selected_terminal


@pytest.mark.asyncio
async def test_stream_verifies_multi_chunk_eof_and_closes_source() -> None:
    """Normal iteration yields exact bytes and closes its source once."""
    stream, context, terminal = _stream([b"ab", b"cd"], expected=b"abcd")

    body = b"".join([chunk async for chunk in stream])

    assert body == b"abcd"
    assert stream.eof_reached
    assert context.close_calls == 1
    await stream.complete()
    await stream.complete()
    assert terminal.complete_calls == 1
    assert terminal.abandon_calls == 0


@pytest.mark.asyncio
async def test_zero_byte_stream_completes_with_empty_body() -> None:
    """A zero-byte source reaches verified EOF without a synthetic chunk."""
    stream, context, terminal = _stream([], expected=b"")

    body = b"".join([chunk async for chunk in stream])

    assert body == b""
    assert stream.eof_reached
    await stream.complete()
    assert context.close_calls == 1
    assert terminal.complete_calls == 1


@pytest.mark.asyncio
async def test_complete_before_eof_is_rejected_without_terminal_action() -> None:
    """A response cannot acknowledge a source before exact EOF."""
    stream, _context, terminal = _stream([b"data"], expected=b"data")

    with pytest.raises(DownloadStreamError, match="verified EOF"):
        await stream.complete()

    assert terminal.complete_calls == 0
    assert terminal.abandon_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("values", "expected", "error"),
    [
        ([b"ab"], b"abcd", "ended before"),
        ([b"abcde"], b"abcd", "exceeded"),
        ([b""], b"abcd", "empty chunk"),
        ([b"abc"], b"abcx", "ended before"),
    ],
)
async def test_invalid_source_fails_closed(
    values: list[bytes], expected: bytes, error: str
) -> None:
    """Truncation, overflow, empty chunks, and hash mismatch never complete."""
    stream, context, terminal = _stream(
        values,
        expected=expected,
        maximum_chunk_size=8 if error == "exceeded" else 4,
    )

    with pytest.raises(DownloadStreamError, match=error):
        async for _chunk in stream:
            pass

    assert not stream.eof_reached
    assert context.close_calls == 1
    await stream.abandon()
    await stream.abandon()
    assert terminal.complete_calls == 0
    assert terminal.abandon_calls == 1


@pytest.mark.asyncio
async def test_source_error_closes_before_abandon() -> None:
    """A source read error closes the object body before unsuccessful cleanup."""

    async def failing_chunks() -> AsyncGenerator[bytes, None]:
        yield b"ab"
        raise OSError("source failed")

    context = _SourceContext(failing_chunks())
    terminal = _Terminal()
    stream = BoundedDownloadStream(
        source_context=context,
        source_iterator=context.iterator,
        expected_size=4,
        expected_sha256=hashlib.sha256(b"abcd").hexdigest(),
        maximum_chunk_size=4,
        on_complete=terminal.complete,
        on_abandon=terminal.abandon,
    )

    with pytest.raises(OSError, match="source failed"):
        async for _chunk in stream:
            pass
    await stream.abandon()

    assert context.close_calls == 1
    assert terminal.abandon_calls == 1


@pytest.mark.asyncio
async def test_stream_rejects_replay() -> None:
    """A single response handle cannot be iterated a second time."""
    stream, _context, _terminal = _stream([b"data"], expected=b"data")

    iterator = stream.__aiter__()
    del iterator
    with pytest.raises(DownloadStreamError, match="replayed"):
        stream.__aiter__()
