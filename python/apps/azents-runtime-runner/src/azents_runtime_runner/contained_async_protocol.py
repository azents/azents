"""Async stream adapter for the contained helper framing protocol."""

import asyncio

from azents_runtime_runner.contained_protocol import (
    FRAME_HEADER_BYTES,
    ContainedProtocolError,
    ProtocolFrame,
    decode_frame,
    decode_frame_header,
)


async def read_async_frame(reader: asyncio.StreamReader) -> ProtocolFrame:
    """Read one validated frame from an asyncio stream."""
    header = await _read_async_exact(reader, FRAME_HEADER_BYTES)
    frame_header = decode_frame_header(header)
    data = await _read_async_exact(reader, frame_header.size)
    return decode_frame(frame_header.kind, data)


async def _read_async_exact(reader: asyncio.StreamReader, size: int) -> bytes:
    try:
        return await reader.readexactly(size)
    except asyncio.IncompleteReadError as error:
        raise ContainedProtocolError("contained frame ended unexpectedly") from error
