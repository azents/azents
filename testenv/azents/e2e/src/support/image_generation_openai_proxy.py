"""Deterministic model, hosted-image, Imagine, and xAI OAuth proxy."""

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
from urllib.parse import parse_qs

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
_XAI_IMAGINE_JOURNAL_PATH = "/v1/_xai_imagine_requests"
_XAI_OAUTH_JOURNAL_PATH = "/v1/_xai_oauth_requests"
_XAI_API_KEY_IMAGE_PROMPT = "A deterministic xAI API-key aurora"
_XAI_OAUTH_IMAGE_PROMPT = "A deterministic xAI OAuth aurora"
_XAI_OAUTH_REFRESH_IMAGE_PROMPT = "A deterministic xAI OAuth refresh aurora"
_XAI_OAUTH_REJECTED_IMAGE_PROMPT = "A deterministic rejected xAI OAuth aurora"
_CAPTURED_MODEL_PROMPTS = {
    _PROMPT,
    _FOLLOW_UP_PROMPT,
    "xAI API-key image generation",
    "xAI OAuth image generation",
    "xAI OAuth image generation after 401",
    "xAI OAuth image generation repeated 401",
    "xAI image generation disabled",
}


def _last_user_text(request: dict[str, object]) -> str | None:
    """Return the text from the last user input or message item."""
    input_value = request.get("input", request.get("messages"))
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
            if part.get("type") in {"input_text", "text"} and isinstance(text, str):
                text_parts.append(text)
        return "".join(text_parts)
    return None


class _State:
    requests: ClassVar[list[dict[str, object]]] = []
    imagine_requests: ClassVar[list[dict[str, object]]] = []
    oauth_requests: ClassVar[list[dict[str, object]]] = []
    lock: ClassVar[threading.Lock] = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        """Return a local journal or proxy the request."""
        journal = self._journal_for_path()
        if journal is not None:
            with _State.lock:
                payload = list(journal)
            self._write_json(200, payload)
            return
        self._proxy()

    def do_DELETE(self) -> None:
        """Clear a local journal or proxy the request."""
        journal = self._journal_for_path()
        if journal is not None:
            with _State.lock:
                journal.clear()
            self._write_json(200, {"cleared": True})
            return
        self._proxy()

    def do_POST(self) -> None:
        """Handle deterministic image and OAuth boundaries."""
        body = self._read_body()
        if self.path == "/v1/images/generations":
            self._write_xai_imagine_response(body)
            return
        if self.path == "/oauth2/token":
            self._write_xai_oauth_token_response(body)
            return
        if self.path not in {"/v1/responses", "/v1/chat/completions"}:
            self._proxy(body)
            return
        request_value: object = json.loads(body)
        if not isinstance(request_value, dict):
            self._write_json(400, {"error": {"message": "invalid request"}})
            return
        request = cast(dict[str, object], request_value)
        user_text = _last_user_text(request)
        if user_text in _CAPTURED_MODEL_PROMPTS:
            with _State.lock:
                _State.requests.append(request)
        if self.path == "/v1/responses" and user_text == _PROMPT:
            self._write_image_generation_response(request)
            return
        self._proxy(body)

    def _journal_for_path(self) -> list[dict[str, object]] | None:
        """Return the journal selected by the current request path."""
        if self.path == _JOURNAL_PATH:
            return _State.requests
        if self.path == _XAI_IMAGINE_JOURNAL_PATH:
            return _State.imagine_requests
        if self.path == _XAI_OAUTH_JOURNAL_PATH:
            return _State.oauth_requests
        return None

    def _write_xai_imagine_response(self, body: bytes) -> None:
        """Return deterministic Imagine output and bounded auth failures."""
        try:
            request_value: object = json.loads(body)
        except json.JSONDecodeError:
            self._write_json(400, {"error": {"message": "invalid request"}})
            return
        if not isinstance(request_value, dict):
            self._write_json(400, {"error": {"message": "invalid request"}})
            return
        request = cast(dict[str, object], request_value)
        prompt = request.get("prompt")
        if not isinstance(prompt, str):
            self._write_json(400, {"error": {"message": "prompt is required"}})
            return
        credential = self._xai_credential_label()
        status = 200
        if prompt == _XAI_OAUTH_REFRESH_IMAGE_PROMPT and credential == "oauth_initial":
            status = 401
        elif prompt == _XAI_OAUTH_REJECTED_IMAGE_PROMPT:
            status = 401
        elif prompt not in {
            _XAI_API_KEY_IMAGE_PROMPT,
            _XAI_OAUTH_IMAGE_PROMPT,
            _XAI_OAUTH_REFRESH_IMAGE_PROMPT,
            _XAI_OAUTH_REJECTED_IMAGE_PROMPT,
        }:
            status = 400
        with _State.lock:
            _State.imagine_requests.append(
                {
                    "prompt": prompt,
                    "credential": credential,
                    "status": status,
                }
            )
        if status != 200:
            self._write_json(status, {"error": {"message": "deterministic failure"}})
            return
        self._write_json(
            200,
            {"data": [{"b64_json": b64encode(_IMAGE_PATH.read_bytes()).decode()}]},
        )

    def _write_xai_oauth_token_response(self, body: bytes) -> None:
        """Return a deterministic replacement token without journaling secrets."""
        form = parse_qs(body.decode())
        refresh_token = form.get("refresh_token", [None])[0]
        if refresh_token == "test-xai-refresh-success":
            refresh_case = "success"
            access_token = "test-xai-oauth-refreshed"
        elif refresh_token == "test-xai-refresh-rejected":
            refresh_case = "rejected"
            access_token = "test-xai-oauth-rejected-refreshed"
        else:
            self._write_json(400, {"error": "invalid_grant"})
            return
        with _State.lock:
            _State.oauth_requests.append({"refresh_case": refresh_case})
        self._write_json(
            200,
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    def _xai_credential_label(self) -> str:
        """Classify deterministic credentials without recording token values."""
        authorization = self.headers.get("Authorization")
        return {
            "Bearer test-xai-api-key": "api_key",
            "Bearer test-xai-oauth-token": "oauth",
            "Bearer test-xai-oauth-refresh-initial": "oauth_initial",
            "Bearer test-xai-oauth-refreshed": "oauth_refreshed",
            "Bearer test-xai-oauth-rejected-initial": "oauth_rejected_initial",
            "Bearer test-xai-oauth-rejected-refreshed": "oauth_rejected_refreshed",
        }.get(authorization or "", "unknown")

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
