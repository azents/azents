"""Public Runtime Terminal binary wire tests."""

import pytest

from azents.api.public.terminal.v1.wire import (
    RuntimeTerminalBinaryFrameInvalid,
    encode_terminal_output_frame,
    parse_terminal_input_frame,
)


def test_terminal_binary_frames_preserve_opaque_bytes() -> None:
    payload = b"\xff\x00terminal"
    input_frame = bytes((1, 1)) + (7).to_bytes(8, "big") + payload

    parsed = parse_terminal_input_frame(input_frame)
    output = encode_terminal_output_frame(sequence=9, data=payload)

    assert parsed.sequence == 7
    assert parsed.data == payload
    assert output[:2] == bytes((1, 2))
    assert int.from_bytes(output[2:10], "big") == 9
    assert output[10:] == payload


@pytest.mark.parametrize(
    "frame",
    [
        b"",
        bytes((2, 1)) + (1).to_bytes(8, "big") + b"x",
        bytes((1, 2)) + (1).to_bytes(8, "big") + b"x",
        bytes((1, 1)) + (0).to_bytes(8, "big") + b"x",
        bytes((1, 1)) + (1).to_bytes(8, "big") + (b"x" * (16 * 1024 + 1)),
    ],
)
def test_terminal_input_frame_rejects_invalid_wire(frame: bytes) -> None:
    with pytest.raises(RuntimeTerminalBinaryFrameInvalid):
        parse_terminal_input_frame(frame)
