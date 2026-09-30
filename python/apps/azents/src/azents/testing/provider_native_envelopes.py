"""Native inference envelopes for small real-process provider smoke fixtures.

These bytes are consumed by the real SDKs. No application ModelResponse is
constructed here. Conditional and malformed protocol cases belong in unit tests.
"""

import dataclasses
import json
import struct
import zlib
from base64 import b64encode
from typing import Literal

NativeFixtureProtocol = Literal[
    "responses", "anthropic", "google", "chat_completions", "bedrock"
]


@dataclasses.dataclass(frozen=True)
class NativeFixtureResponse:
    """HTTP response bytes at the official SDK boundary."""

    content_type: str
    body: bytes


def core_google_image_bytes() -> bytes:
    """Generate a small valid PNG for transport and durable-file verification."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        framed = kind + body
        return (
            struct.pack("!I", len(body))
            + framed
            + struct.pack("!I", zlib.crc32(framed))
        )

    header = struct.pack("!IIBBBBB", 32, 32, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + b"\x20\x60\xc0" * 32 for _ in range(32))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def core_google_image_response(*, model: str, text: str) -> NativeFixtureResponse:
    """Return native inlineData, parsed by the official SDK into image output."""
    return NativeFixtureResponse(
        content_type="text/event-stream",
        body=_sse(
            {
                "candidates": [
                    {
                        "index": 0,
                        "content": {
                            "role": "model",
                            "parts": [
                                {"text": text},
                                {
                                    "inlineData": {
                                        "mimeType": "image/png",
                                        "data": b64encode(
                                            core_google_image_bytes()
                                        ).decode(),
                                    }
                                },
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "modelVersion": model,
                "responseId": "core-native-google-image",
                "usageMetadata": {
                    "promptTokenCount": 3,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 5,
                },
            }
        ),
    )


def core_native_response(
    *, protocol: NativeFixtureProtocol, model: str, text: str
) -> NativeFixtureResponse:
    """Provide one truthful nominal terminal and usage report for each dialect."""
    match protocol:
        case "responses":
            return NativeFixtureResponse(
                content_type="text/event-stream",
                body=_responses(model=model, text=text),
            )
        case "anthropic":
            return NativeFixtureResponse(
                content_type="text/event-stream",
                body=_anthropic(model=model, text=text),
            )
        case "google":
            return NativeFixtureResponse(
                content_type="text/event-stream",
                body=_sse(
                    {
                        "candidates": [
                            {
                                "index": 0,
                                "content": {
                                    "role": "model",
                                    "parts": [{"text": text}],
                                },
                                "finishReason": "STOP",
                            }
                        ],
                        "modelVersion": model,
                        "responseId": "core-native-google",
                        "usageMetadata": {
                            "promptTokenCount": 3,
                            "candidatesTokenCount": 2,
                            "totalTokenCount": 5,
                        },
                    }
                ),
            )
        case "chat_completions":
            return NativeFixtureResponse(
                content_type="text/event-stream",
                body=_chat(model=model, text=text),
            )
        case "bedrock":
            events = [
                aws_event_frame("messageStart", {"role": "assistant"}),
                aws_event_frame(
                    "contentBlockDelta",
                    {"contentBlockIndex": 0, "delta": {"text": text}},
                ),
                aws_event_frame("contentBlockStop", {"contentBlockIndex": 0}),
                aws_event_frame("messageStop", {"stopReason": "end_turn"}),
                aws_event_frame(
                    "metadata",
                    {
                        "usage": {
                            "inputTokens": 3,
                            "outputTokens": 2,
                            "totalTokens": 5,
                        },
                        "metrics": {"latencyMs": 1},
                    },
                ),
            ]
            return NativeFixtureResponse(
                content_type="application/vnd.amazon.eventstream",
                body=b"".join(events),
            )


def aws_event_frame(event_type: str, payload: dict[str, object]) -> bytes:
    """Encode an AWS event-stream message, including both public CRC fields."""
    headers = b"".join(
        _aws_string_header(name, value)
        for name, value in (
            (":message-type", "event"),
            (":event-type", event_type),
            (":content-type", "application/json"),
        )
    )
    body = json.dumps(payload, separators=(",", ":")).encode()
    length = 16 + len(headers) + len(body)
    prelude = struct.pack("!II", length, len(headers))
    message = prelude + struct.pack("!I", zlib.crc32(prelude)) + headers + body
    return message + struct.pack("!I", zlib.crc32(message))


def _aws_string_header(name: str, value: str) -> bytes:
    encoded_name = name.encode()
    encoded_value = value.encode()
    return (
        struct.pack("!B", len(encoded_name))
        + encoded_name
        + b"\x07"
        + struct.pack("!H", len(encoded_value))
        + encoded_value
    )


def _sse(payload: dict[str, object]) -> bytes:
    event_type = payload.get("type")
    prefix = f"event: {event_type}\n" if isinstance(event_type, str) else ""
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"{prefix}data: {encoded}\n\n".encode()


def _responses(*, model: str, text: str) -> bytes:
    message: dict[str, object] = {
        "id": "core-native-message",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }
    response: dict[str, object] = {
        "id": "core-native-response",
        "object": "response",
        "created_at": 1,
        "model": model,
        "status": "completed",
        "output": [message],
        "usage": {
            "input_tokens": 3,
            "output_tokens": 2,
            "total_tokens": 5,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }
    events: list[dict[str, object]] = [
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": {**response, "status": "in_progress", "output": []},
        },
        {
            "type": "response.output_item.added",
            "sequence_number": 1,
            "output_index": 0,
            "item": {**message, "status": "in_progress", "content": []},
        },
        {
            "type": "response.content_part.added",
            "sequence_number": 2,
            "item_id": message["id"],
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": "", "annotations": []},
        },
        {
            "type": "response.output_text.delta",
            "sequence_number": 3,
            "item_id": message["id"],
            "output_index": 0,
            "content_index": 0,
            "delta": text,
        },
        {
            "type": "response.output_text.done",
            "sequence_number": 4,
            "item_id": message["id"],
            "output_index": 0,
            "content_index": 0,
            "text": text,
        },
        {
            "type": "response.output_item.done",
            "sequence_number": 5,
            "output_index": 0,
            "item": message,
        },
        {"type": "response.completed", "sequence_number": 6, "response": response},
    ]
    return b"".join(_sse(event) for event in events)


def _anthropic(*, model: str, text: str) -> bytes:
    events: list[dict[str, object]] = [
        {
            "type": "message_start",
            "message": {
                "id": "core-native-anthropic",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 3, "output_tokens": 0},
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": text},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 2},
        },
        {"type": "message_stop"},
    ]
    return b"".join(_sse(event) for event in events)


def _chat(*, model: str, text: str) -> bytes:
    envelope: dict[str, object] = {
        "id": "core-native-chat",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": model,
    }
    return (
        b"".join(
            _sse(event)
            for event in (
                {
                    **envelope,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": text},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    **envelope,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                },
                {
                    **envelope,
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 2,
                        "total_tokens": 5,
                    },
                },
            )
        )
        + b"data: [DONE]\n\n"
    )
