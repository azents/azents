"""OpenAI Responses proxy with deterministic image-generation output."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from base64 import b64encode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar, cast

_PROMPT = "Provider image generation handoff"
_FOLLOW_UP_PROMPT = "Provider image generation follow-up"
_UPSTREAM = os.environ.get("AIMOCK_UPSTREAM", "http://mock-openai:8080")
_IMAGE_PATH = Path(
    os.environ.get(
        "IMAGE_GENERATION_FIXTURE",
        "/fixtures/provider-image-generation.png",
    )
)
_JOURNAL_PATH = "/v1/_image_generation_requests"


def _last_user_text(request: dict[str, object]) -> str | None:
    """Return the text from the last user input item."""
    input_value = request.get("input")
    if isinstance(input_value, str):
        return input_value
    if not isinstance(input_value, list):
        return None
    input_items = cast(list[object], input_value)
    for raw_item in reversed(input_items):
        if not isinstance(raw_item, dict):
            continue
        item = cast(dict[str, object], raw_item)
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return None
        text_parts: list[str] = []
        for raw_part in cast(list[object], content):
            if not isinstance(raw_part, dict):
                continue
            part = cast(dict[str, object], raw_part)
            text = part.get("text")
            if part.get("type") == "input_text" and isinstance(text, str):
                text_parts.append(text)
        return "".join(text_parts)
    return None


class _State:
    requests: ClassVar[list[dict[str, object]]] = []
    lock: ClassVar[threading.Lock] = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        """Return the local journal or proxy the request."""
        if self.path == _JOURNAL_PATH:
            with _State.lock:
                payload = list(_State.requests)
            self._write_json(200, payload)
            return
        self._proxy()

    def do_DELETE(self) -> None:
        """Clear the local journal or proxy the request."""
        if self.path == _JOURNAL_PATH:
            with _State.lock:
                _State.requests.clear()
            self._write_json(200, {"cleared": True})
            return
        self._proxy()

    def do_POST(self) -> None:
        """Emit deterministic image output for the dedicated prompt."""
        body = self._read_body()
        if self.path != "/v1/responses":
            self._proxy(body)
            return
        request_value: object = json.loads(body)
        if not isinstance(request_value, dict):
            self._write_json(400, {"error": {"message": "invalid request"}})
            return
        request = cast(dict[str, object], request_value)
        user_text = _last_user_text(request)
        if user_text in {_PROMPT, _FOLLOW_UP_PROMPT}:
            with _State.lock:
                _State.requests.append(request)
        if user_text == _PROMPT:
            self._write_image_generation_response(request)
            return
        self._proxy(body)

    def log_message(self, format: str, *args: object) -> None:
        """Suppress routine proxy access logs."""
        del format, args

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def _write_image_generation_response(self, request: dict[str, object]) -> None:
        image_base64 = b64encode(_IMAGE_PATH.read_bytes()).decode()
        model_value = request.get("model")
        model = model_value if isinstance(model_value, str) else "gpt-5.5"
        response_id = "resp_provider_image_generation"
        item_id = "ig_provider_image_generation"
        created_at = time.time()
        image_item = {
            "id": item_id,
            "type": "image_generation_call",
            "status": "completed",
            "result": image_base64,
        }
        response = {
            "id": response_id,
            "object": "response",
            "created_at": created_at,
            "model": model,
            "status": "completed",
            "output": [image_item],
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": request.get("tools", []),
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }
        if request.get("stream") is not True:
            self._write_json(200, response)
            return

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
                "item": {
                    "id": item_id,
                    "type": "image_generation_call",
                    "status": "in_progress",
                    "result": None,
                },
            },
            {
                "type": "response.image_generation_call.in_progress",
                "sequence_number": 2,
                "output_index": 0,
                "item_id": item_id,
            },
            {
                "type": "response.image_generation_call.generating",
                "sequence_number": 3,
                "output_index": 0,
                "item_id": item_id,
            },
            {
                "type": "response.image_generation_call.completed",
                "sequence_number": 4,
                "output_index": 0,
                "item_id": item_id,
            },
            {
                "type": "response.output_item.done",
                "sequence_number": 5,
                "output_index": 0,
                "item": image_item,
            },
            {
                "type": "response.completed",
                "sequence_number": 6,
                "response": response,
            },
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for event in events:
            event_type = event.get("type")
            if not isinstance(event_type, str):
                raise RuntimeError("Responses event type is missing.")
            encoded = json.dumps(event, separators=(",", ":")).encode()
            self.wfile.write(b"event: " + event_type.encode() + b"\n")
            self.wfile.write(b"data: " + encoded + b"\n\n")
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def _proxy(self, body: bytes | None = None) -> None:
        target = f"{_UPSTREAM}{self.path}"
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }
        request = urllib.request.Request(
            target,
            data=body,
            headers=headers,
            method=self.command,
        )
        try:
            response = urllib.request.urlopen(request, timeout=300)
        except urllib.error.HTTPError as error:
            response = error
        except urllib.error.URLError as error:
            self._write_json(502, {"error": {"message": str(error.reason)}})
            return
        try:
            status = response.getcode()
            self.send_response(status if status is not None else 502)
            for key, value in response.headers.items():
                if key.lower() not in {
                    "content-length",
                    "connection",
                    "transfer-encoding",
                }:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            read_chunk = getattr(response, "read1", response.read)
            while chunk := read_chunk(64 * 1024):
                self.wfile.write(chunk)
                self.wfile.flush()
        finally:
            response.close()
        self.close_connection = True

    def _write_json(self, status: int, value: object) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    """Run the deterministic proxy."""
    server = ThreadingHTTPServer(("0.0.0.0", 8081), _Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
