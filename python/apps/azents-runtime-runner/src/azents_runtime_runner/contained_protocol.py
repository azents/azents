"""Bounded framed protocol shared with the contained operation helper."""

from __future__ import annotations

import enum
import json
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import BinaryIO, NamedTuple, TypeAlias

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)

PROTOCOL_VERSION = 1
MAX_CONTROL_FRAME_BYTES = 1024 * 1024
MAX_BINARY_FRAME_BYTES = 8 * 1024 * 1024
_HEADER = struct.Struct("!BI")
FRAME_HEADER_BYTES = _HEADER.size


class FrameKind(enum.IntEnum):
    """Contained helper frame kinds."""

    CONTROL = 1
    BINARY = 2


@dataclass(frozen=True)
class ProtocolFrame:
    """One validated contained helper frame."""

    kind: FrameKind
    control: Mapping[str, JsonValue] | None
    binary: bytes | None


class FrameHeader(NamedTuple):
    """One validated contained helper frame header."""

    kind: FrameKind
    size: int


class ContainedProtocolError(RuntimeError):
    """Contained helper framing or payload validation failed."""


def encode_control_frame(payload: Mapping[str, JsonValue]) -> bytes:
    """Encode one bounded JSON object frame."""
    data = json.dumps(
        dict(payload),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    if len(data) > MAX_CONTROL_FRAME_BYTES:
        raise ContainedProtocolError("contained control frame is too large")
    return _HEADER.pack(FrameKind.CONTROL, len(data)) + data


def encode_binary_frame(data: bytes) -> bytes:
    """Encode one bounded raw binary frame."""
    if len(data) > MAX_BINARY_FRAME_BYTES:
        raise ContainedProtocolError("contained binary frame is too large")
    return _HEADER.pack(FrameKind.BINARY, len(data)) + data


def read_sync_frame(reader: BinaryIO) -> ProtocolFrame:
    """Read one validated frame from a blocking binary stream."""
    header = _read_sync_exact(reader, FRAME_HEADER_BYTES)
    frame_header = decode_frame_header(header)
    data = _read_sync_exact(reader, frame_header.size)
    return decode_frame(frame_header.kind, data)


def write_sync_control(writer: BinaryIO, payload: Mapping[str, JsonValue]) -> None:
    """Write and flush one blocking control frame."""
    writer.write(encode_control_frame(payload))
    writer.flush()


def write_sync_binary(writer: BinaryIO, data: bytes) -> None:
    """Write and flush one blocking binary frame."""
    writer.write(encode_binary_frame(data))
    writer.flush()


def _read_sync_exact(reader: BinaryIO, size: int) -> bytes:
    data = reader.read(size)
    if data is None or len(data) != size:
        raise ContainedProtocolError("contained frame ended unexpectedly")
    return data


def decode_frame_header(header: bytes) -> FrameHeader:
    """Decode and validate one complete frame header."""
    kind_value, size = _HEADER.unpack(header)
    kind = _frame_kind(kind_value)
    _validate_frame_size(kind, size)
    return FrameHeader(kind=kind, size=size)


def _frame_kind(value: int) -> FrameKind:
    try:
        return FrameKind(value)
    except ValueError as error:
        raise ContainedProtocolError("contained frame kind is unsupported") from error


def _validate_frame_size(kind: FrameKind, size: int) -> None:
    maximum = (
        MAX_CONTROL_FRAME_BYTES if kind is FrameKind.CONTROL else MAX_BINARY_FRAME_BYTES
    )
    if size > maximum:
        raise ContainedProtocolError("contained frame is too large")


def decode_frame(kind: FrameKind, data: bytes) -> ProtocolFrame:
    """Decode one validated frame body."""
    if kind is FrameKind.BINARY:
        return ProtocolFrame(kind=kind, control=None, binary=data)
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContainedProtocolError("contained control frame is invalid") from error
    if not isinstance(value, dict):
        raise ContainedProtocolError("contained control frame must contain an object")
    if not all(isinstance(key, str) for key in value):
        raise ContainedProtocolError("contained control frame keys must be strings")
    return ProtocolFrame(kind=kind, control=value, binary=None)
