"""Binary Public Runtime Terminal WebSocket frame codec."""

import dataclasses
import struct

from azents.runtime.terminal_coordination.data import MAX_TERMINAL_CHUNK_BYTES

TERMINAL_WEBSOCKET_SUBPROTOCOL = "azents.terminal.v1"
_TERMINAL_BINARY_VERSION = 1
_TERMINAL_INPUT_FRAME_TYPE = 1
_TERMINAL_OUTPUT_FRAME_TYPE = 2
_TERMINAL_HEADER = struct.Struct(">BBQ")


class RuntimeTerminalBinaryFrameInvalid(ValueError):
    """Raised when a Terminal binary frame violates the fixed wire contract."""


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalInputFrame:
    """One parsed ordered browser input frame."""

    sequence: int
    data: bytes


def parse_terminal_input_frame(frame: bytes) -> RuntimeTerminalInputFrame:
    """Parse one versioned input frame with a 16 KiB payload bound."""
    if (
        not _TERMINAL_HEADER.size
        < len(frame)
        <= (_TERMINAL_HEADER.size + MAX_TERMINAL_CHUNK_BYTES)
    ):
        raise RuntimeTerminalBinaryFrameInvalid("Invalid Terminal input frame size")
    version, frame_type, sequence = _TERMINAL_HEADER.unpack_from(frame)
    if version != _TERMINAL_BINARY_VERSION or frame_type != _TERMINAL_INPUT_FRAME_TYPE:
        raise RuntimeTerminalBinaryFrameInvalid("Invalid Terminal input frame type")
    if sequence <= 0:
        raise RuntimeTerminalBinaryFrameInvalid("Invalid Terminal input sequence")
    return RuntimeTerminalInputFrame(
        sequence=sequence,
        data=frame[_TERMINAL_HEADER.size :],
    )


def encode_terminal_output_frame(*, sequence: int, data: bytes) -> bytes:
    """Encode one versioned output frame without interpreting PTY bytes."""
    if sequence <= 0:
        raise ValueError("Terminal output sequence must be positive")
    if not 1 <= len(data) <= MAX_TERMINAL_CHUNK_BYTES:
        raise ValueError("Terminal output payload exceeds the frame bound")
    return (
        _TERMINAL_HEADER.pack(
            _TERMINAL_BINARY_VERSION,
            _TERMINAL_OUTPUT_FRAME_TYPE,
            sequence,
        )
        + data
    )
