"""Nominal native cloud envelopes for the real API/worker SDK smoke."""

import hashlib
import json
import struct
import zlib
from base64 import b64encode, urlsafe_b64decode
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs
from uuid import uuid4

CORE_TEXT = '{"title":"Provider cutover core"}'


def inference_profile_source_payload() -> dict[str, dict[str, object]]:
    """Supply synthetic prices to the ordinary validated-source ingestion API."""
    return {
        model: {
            "litellm_provider": "openai",
            "mode": "chat",
            "max_input_tokens": 128_000,
            "max_output_tokens": 16_384,
            "supports_function_calling": True,
            "supports_reasoning": True,
            "input_cost_per_token": 0.000001,
            "cache_read_input_token_cost": 0.0000001,
            "cache_creation_input_token_cost": 0.000001,
            "output_cost_per_token": 0.000002,
            "input_cost_per_token_priority": 0.000002,
            "cache_read_input_token_cost_priority": 0.0000002,
            "cache_creation_input_token_cost_priority": 0.000002,
            "output_cost_per_token_priority": 0.000004,
        }
        for model in ("gpt-5.5", "gpt-5.5-mini", "gpt-6-astra", "gpt-5.6-sol")
    }


def serve_native_responses_websocket(handler: BaseHTTPRequestHandler) -> None:
    """Serve nominal Responses frames consumed by the official WebSocket SDK."""
    key = handler.headers.get("Sec-WebSocket-Key")
    authorization = handler.headers.get("Authorization", "")
    if key is None or not authorization.startswith("Bearer e2e-provider-cutover-"):
        handler.send_error(401)
        return
    challenge = (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
    accept = b64encode(hashlib.sha1(challenge).digest()).decode()
    handler.send_response(101)
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()
    handler.wfile.flush()
    handler.close_connection = True
    while True:
        header = handler.rfile.read(2)
        if len(header) != 2:
            return
        opcode = header[0] & 0x0F
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", handler.rfile.read(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", handler.rfile.read(8))[0]
        if length > 2_000_000:
            raise ValueError("Nominal WebSocket fixture input exceeded its bound")
        mask = handler.rfile.read(4) if header[1] & 0x80 else None
        body = handler.rfile.read(length)
        if mask is not None:
            body = bytes(value ^ mask[index % 4] for index, value in enumerate(body))
        if opcode == 8:
            _write_websocket_frame(handler, body, opcode=8)
            return
        if opcode == 9:
            _write_websocket_frame(handler, body, opcode=10)
            continue
        if opcode != 1:
            raise ValueError("Nominal WebSocket fixture expects text")
        request: object = json.loads(body)
        if not isinstance(request, dict) or request.get("type") != "response.create":
            raise ValueError("Nominal WebSocket fixture expects response.create")
        parameters = request.get("response", request)
        if not isinstance(parameters, dict) or not isinstance(
            parameters.get("model"), str
        ):
            raise ValueError("Native response requires a model identity")
        response_id = "resp_core_" + uuid4().hex
        item = {
            "id": "msg_core_" + uuid4().hex,
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": CORE_TEXT, "annotations": []}],
        }
        response = {
            "id": response_id,
            "object": "response",
            "created_at": 0,
            "status": "completed",
            "model": parameters["model"],
            "output": [item],
            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        }
        events = (
            {
                "type": "response.created",
                "sequence_number": 0,
                "response": {**response, "status": "in_progress", "output": []},
            },
            {
                "type": "response.output_item.done",
                "sequence_number": 1,
                "output_index": 0,
                "item": item,
            },
            {
                "type": "response.completed",
                "sequence_number": 2,
                "response": response,
            },
        )
        for event in events:
            _write_websocket_frame(handler, json.dumps(event).encode(), opcode=1)


def _write_websocket_frame(
    handler: BaseHTTPRequestHandler, body: bytes, *, opcode: int
) -> None:
    """Encode one unmasked server frame at the real SDK transport boundary."""
    length = len(body)
    header = (
        bytes([0x80 | opcode, length])
        if length < 126
        else bytes([0x80 | opcode, 126]) + struct.pack("!H", length)
    )
    handler.wfile.write(header + body)
    handler.wfile.flush()


def google_token_request_valid(body: bytes) -> bool:
    """Recognize the normal signed service-account grant's synthetic identity."""
    form = parse_qs(body.decode())
    assertion = form.get("assertion", [None])[0]
    if not isinstance(assertion, str):
        return False
    pieces = assertion.split(".")
    if len(pieces) != 3:
        return False
    try:
        claims = json.loads(urlsafe_b64decode(pieces[1] + "=" * (-len(pieces[1]) % 4)))
    except ValueError:
        return False
    return (
        isinstance(claims, dict)
        and claims.get("iss")
        == "provider-cutover-core@provider-cutover-core.iam.gserviceaccount.com"
        and form.get("grant_type") == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    )


def bedrock_core_response(body: bytes) -> bytes:
    """Return official Converse stream frames, with native structured text."""
    request: object = json.loads(body)
    if not isinstance(request, dict):
        raise ValueError("Converse request must be an object")
    config = request.get("toolConfig")
    tools = config.get("tools") if isinstance(config, dict) else None
    output_tool = isinstance(tools, list) and any(
        isinstance(tool, dict)
        and isinstance(tool.get("toolSpec"), dict)
        and tool["toolSpec"].get("name") == "json_tool_call"
        for tool in tools
    )
    events: list[tuple[str, dict[str, object]]] = [
        ("messageStart", {"role": "assistant"})
    ]
    if output_tool:
        events.append(
            (
                "contentBlockStart",
                {
                    "contentBlockIndex": 0,
                    "start": {
                        "toolUse": {
                            "toolUseId": "core-json-output",
                            "name": "json_tool_call",
                        }
                    },
                },
            )
        )
    events.extend(
        [
            (
                "contentBlockDelta",
                {
                    "contentBlockIndex": 0,
                    "delta": (
                        {"toolUse": {"input": CORE_TEXT}}
                        if output_tool
                        else {"text": CORE_TEXT}
                    ),
                },
            ),
            ("contentBlockStop", {"contentBlockIndex": 0}),
            (
                "messageStop",
                {"stopReason": "tool_use" if output_tool else "end_turn"},
            ),
            (
                "metadata",
                {
                    "usage": {"inputTokens": 3, "outputTokens": 2, "totalTokens": 5},
                    "metrics": {"latencyMs": 1},
                },
            ),
        ]
    )
    return b"".join(_aws_event_frame(kind, payload) for kind, payload in events)


def _aws_event_frame(event_type: str, payload: dict[str, object]) -> bytes:
    """Encode AWS's documented event frame and checksum fields."""
    headers = b""
    for name, value in (
        (":message-type", "event"),
        (":event-type", event_type),
        (":content-type", "application/json"),
    ):
        key, encoded = name.encode(), value.encode()
        headers += (
            bytes([len(key)])
            + key
            + b"\x07"
            + struct.pack("!H", len(encoded))
            + encoded
        )
    data = json.dumps(payload, separators=(",", ":")).encode()
    prelude = struct.pack("!II", 16 + len(headers) + len(data), len(headers))
    message = prelude + struct.pack("!I", zlib.crc32(prelude)) + headers + data
    return message + struct.pack("!I", zlib.crc32(message))
