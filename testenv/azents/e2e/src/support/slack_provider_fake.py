"""Deterministic Slack HTTP and Socket Mode boundary for E2E tests."""

import base64
import hashlib
import json
import os
import re
import socket
import socketserver
import struct
import threading
import time
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import ClassVar, cast
from urllib.parse import parse_qs, urlparse

_HTTP_PORT = 8083
_WEBSOCKET_PORT = 8084
_APPROVAL_PATH = re.compile(r"/external-channel/access/([^/?\s]+)")


class FakeState:
    """Thread-safe provider scenario and sanitized evidence store."""

    def __init__(self) -> None:
        self.lock = Lock()
        self.reset()

    def reset(self) -> None:
        """Reset scenarios, provider data, and evidence between journeys."""
        with self.lock:
            self.auth_scenario = "valid"
            self.membership_scenario = "member"
            self.history_scenario = "ok"
            self.permalink_scenario = "ok"
            self.delivery_scenarios: dict[str, str] = {
                "chat.postMessage": "delivered",
                "chat.update": "delivered",
                "chat.delete": "delivered",
            }
            self.history_pages: list[list[dict[str, object]]] = []
            self.socket_envelopes: list[dict[str, object]] = []
            self.socket_disconnect_reason: str | None = None
            self.request_counts: dict[str, int] = {}
            self.requests: list[dict[str, object]] = []
            self.deliveries: list[dict[str, object]] = []
            self.socket_connections = 0
            self.socket_envelope_ids: list[str] = []
            self.socket_acknowledgements: list[str] = []
            self._message_sequence = 0

    def configure(self, payload: dict[str, object]) -> None:
        """Apply one bounded deterministic provider scenario."""
        allowed = {
            "auth_scenario",
            "membership_scenario",
            "history_scenario",
            "permalink_scenario",
            "delivery_scenarios",
            "history_pages",
            "socket_envelopes",
            "socket_disconnect_reason",
        }
        if set(payload) - allowed:
            raise ValueError("Unsupported Slack fake configuration field.")
        with self.lock:
            for name in (
                "auth_scenario",
                "membership_scenario",
                "history_scenario",
                "permalink_scenario",
            ):
                value = payload.get(name)
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError(f"{name} must be a string.")
                    setattr(self, name, value)
            delivery_scenarios = payload.get("delivery_scenarios")
            if delivery_scenarios is not None:
                if not isinstance(delivery_scenarios, dict):
                    raise ValueError("delivery_scenarios must be an object.")
                self.delivery_scenarios = {
                    str(key): str(value)
                    for key, value in cast(
                        dict[object, object],
                        delivery_scenarios,
                    ).items()
                }
            history_pages = payload.get("history_pages")
            if history_pages is not None:
                self.history_pages = _object_pages(history_pages)
            socket_envelopes = payload.get("socket_envelopes")
            if socket_envelopes is not None:
                self.socket_envelopes = _object_list(socket_envelopes)
            if "socket_disconnect_reason" in payload:
                disconnect_reason = payload["socket_disconnect_reason"]
                if disconnect_reason is not None and not isinstance(
                    disconnect_reason,
                    str,
                ):
                    raise ValueError("socket_disconnect_reason must be a string.")
                self.socket_disconnect_reason = disconnect_reason
            self.request_counts = {}
            self.requests = []
            self.deliveries = []
            self.socket_connections = 0
            self.socket_envelope_ids = []
            self.socket_acknowledgements = []

    def record_request(
        self,
        operation: str,
        *,
        method: str,
        metadata: Mapping[str, object],
    ) -> None:
        """Record one sanitized provider call without credentials or message text."""
        with self.lock:
            self.request_counts[operation] = self.request_counts.get(operation, 0) + 1
            self.requests.append(
                {
                    "operation": operation,
                    "method": method,
                    **metadata,
                }
            )

    def next_message_timestamp(self) -> str:
        """Return one deterministic provider message identity."""
        with self.lock:
            self._message_sequence += 1
            return f"1721600100.{self._message_sequence:06d}"

    def evidence(self) -> dict[str, object]:
        """Return sanitized evidence suitable for test assertions and failure output."""
        with self.lock:
            return {
                "request_counts": dict(self.request_counts),
                "requests": list(self.requests),
                "deliveries": list(self.deliveries),
                "socket": {
                    "connections": self.socket_connections,
                    "envelope_ids": list(self.socket_envelope_ids),
                    "acknowledgements": list(self.socket_acknowledgements),
                    "disconnect_reason": self.socket_disconnect_reason,
                },
            }


STATE = FakeState()


class SlackHTTPHandler(BaseHTTPRequestHandler):
    """Serve controllable Slack Web API behavior and sanitized evidence."""

    state: ClassVar[FakeState] = STATE

    def do_GET(self) -> None:
        """Handle readiness, evidence, membership, history, and permalinks."""
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json_response(200, {"status": "ok"})
            return
        if parsed.path == "/__testenv/state":
            self._json_response(200, self.state.evidence())
            return
        operation = parsed.path.removeprefix("/api/")
        query = parse_qs(parsed.query)
        metadata = _query_metadata(query)
        self.state.record_request(operation, method="GET", metadata=metadata)
        if operation == "conversations.info":
            self._conversation_info()
            return
        if operation == "conversations.replies":
            self._conversation_replies(query)
            return
        if operation == "chat.getPermalink":
            self._permalink(query)
            return
        if operation == "bots.info":
            self._bot_info(query)
            return
        self._json_response(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        """Handle scenario control, validation, Socket endpoints, and delivery."""
        if self.path == "/__testenv/reset":
            self.state.reset()
            self._json_response(200, {"status": "reset"})
            return
        if self.path == "/__testenv/configure":
            try:
                self.state.configure(self._json_body())
            except ValueError:
                self._json_response(422, {"error": "invalid_configuration"})
                return
            self._json_response(200, {"status": "configured"})
            return
        operation = urlparse(self.path).path.removeprefix("/api/")
        body = self._json_body()
        self.state.record_request(
            operation,
            method="POST",
            metadata=_body_metadata(body),
        )
        if operation == "auth.test":
            self._auth_test()
            return
        if operation == "apps.connections.open":
            self._connections_open()
            return
        if operation in {"chat.postMessage", "chat.update", "chat.delete"}:
            self._delivery(operation, body)
            return
        self._json_response(404, {"ok": False, "error": "not_found"})

    def log_message(self, format: str, *args: object) -> None:
        """Avoid logging request headers, credentials, or provider message content."""
        del format, args

    def _auth_test(self) -> None:
        scenario = self.state.auth_scenario
        if self._common_failure(scenario):
            return
        self._json_response(
            200,
            {
                "ok": True,
                "team_id": "T-E2E",
                "user_id": "U-BOT-E2E",
                "bot_id": "B-E2E",
            },
        )

    def _bot_info(self, query: dict[str, list[str]]) -> None:
        scenario = self.state.auth_scenario
        if self._common_failure(scenario):
            return
        bot_id = query.get("bot", [""])[0]
        self._json_response(
            200,
            {
                "ok": True,
                "bot": {
                    "id": bot_id,
                    "app_id": "A-E2E",
                },
            },
        )

    def _conversation_info(self) -> None:
        scenario = self.state.membership_scenario
        if self._common_failure(scenario):
            return
        self._json_response(
            200,
            {
                "ok": True,
                "channel": {
                    "is_member": scenario != "not_member",
                    "is_channel": scenario != "dm",
                    "is_group": False,
                    "is_ext_shared": scenario == "slack_connect",
                    "is_org_shared": False,
                    "is_im": scenario == "dm",
                    "is_mpim": False,
                },
            },
        )

    def _conversation_replies(self, query: dict[str, list[str]]) -> None:
        scenario = self.state.history_scenario
        if self._common_failure(scenario):
            return
        cursor = query.get("cursor", [None])[0]
        try:
            page_index = int(cursor.removeprefix("page-")) if cursor else 0
        except ValueError:
            page_index = 0
        with self.state.lock:
            pages = list(self.state.history_pages)
        messages = pages[page_index] if page_index < len(pages) else []
        next_cursor = f"page-{page_index + 1}" if page_index + 1 < len(pages) else ""
        self._json_response(
            200,
            {
                "ok": True,
                "messages": messages,
                "response_metadata": {"next_cursor": next_cursor},
            },
        )

    def _permalink(self, query: dict[str, list[str]]) -> None:
        scenario = self.state.permalink_scenario
        if self._common_failure(scenario):
            return
        channel = query.get("channel", ["C-E2E"])[0]
        timestamp = query.get("message_ts", ["1721600000.000100"])[0]
        self._json_response(
            200,
            {
                "ok": True,
                "permalink": (
                    f"https://example.slack.com/archives/{channel}/"
                    f"p{timestamp.replace('.', '')}"
                ),
            },
        )

    def _connections_open(self) -> None:
        scenario = self.state.auth_scenario
        if self._common_failure(scenario):
            return
        self._json_response(
            200,
            {
                "ok": True,
                "url": f"ws://slack-fake:{_WEBSOCKET_PORT}/socket",
            },
        )

    def _delivery(self, operation: str, body: dict[str, object]) -> None:
        with self.state.lock:
            scenario = self.state.delivery_scenarios.get(operation, "delivered")
        if scenario == "ambiguous":
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return
        if scenario == "timeout":
            time.sleep(21)
            return
        if self._common_failure(scenario):
            return
        timestamp = _optional_string(body, "ts") or self.state.next_message_timestamp()
        text = _optional_string(body, "text")
        approval_request_id = None
        if text is not None:
            match = _APPROVAL_PATH.search(text)
            if match is not None:
                approval_request_id = match.group(1)
        delivery: dict[str, object] = {
            "operation": operation,
            "channel": _optional_string(body, "channel"),
            "thread_ts": _optional_string(body, "thread_ts"),
            "message_ts": timestamp,
            "outcome": "delivered",
            "approval_request_id": approval_request_id,
        }
        with self.state.lock:
            self.state.deliveries.append(delivery)
        self._json_response(200, {"ok": True, "ts": timestamp})

    def _common_failure(self, scenario: str) -> bool:
        if scenario == "invalid":
            self._json_response(200, {"ok": False, "error": "invalid_auth"})
            return True
        if scenario == "revoked":
            self._json_response(200, {"ok": False, "error": "token_revoked"})
            return True
        if scenario == "rate_limited":
            self._json_response(
                429,
                {"ok": False, "error": "ratelimited"},
                headers={"Retry-After": "1"},
            )
            return True
        if scenario in {"unavailable", "failed"}:
            status = 503 if scenario == "unavailable" else 200
            self._json_response(
                status,
                {"ok": False, "error": "channel_not_found"},
            )
            return True
        return False

    def _json_body(self) -> dict[str, object]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}
        try:
            payload: object = json.loads(raw_body)
        except UnicodeDecodeError:
            return {}
        except json.JSONDecodeError:
            return {}
        return cast(dict[str, object], payload) if isinstance(payload, dict) else {}

    def _json_response(
        self,
        status: int,
        payload: Mapping[str, object],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if headers is not None:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


class SlackWebSocketHandler(socketserver.BaseRequestHandler):
    """Serve a minimal deterministic Socket Mode WebSocket."""

    state: ClassVar[FakeState] = STATE

    def handle(self) -> None:
        """Perform the handshake, send configured envelopes, and capture ACKs."""
        request = cast(socket.socket, self.request)
        request.settimeout(10)
        headers = _read_http_headers(request)
        key = headers.get("sec-websocket-key")
        if key is None:
            return
        accept = base64.b64encode(
            hashlib.sha1(f"{key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11".encode()).digest()
        ).decode()
        request.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        with self.state.lock:
            self.state.socket_connections += 1
            envelopes = list(self.state.socket_envelopes)
            disconnect_reason = self.state.socket_disconnect_reason
        _send_websocket_text(request, json.dumps({"type": "hello"}))
        for envelope in envelopes:
            envelope_id = envelope.get("envelope_id")
            if isinstance(envelope_id, str):
                with self.state.lock:
                    self.state.socket_envelope_ids.append(envelope_id)
            _send_websocket_text(
                request,
                json.dumps(envelope, separators=(",", ":")),
            )
            acknowledgement = _receive_websocket_text(request)
            try:
                payload: object = json.loads(acknowledgement)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                acknowledged_id = cast(
                    dict[str, object],
                    payload,
                ).get("envelope_id")
                if isinstance(acknowledged_id, str):
                    with self.state.lock:
                        self.state.socket_acknowledgements.append(acknowledged_id)
        if disconnect_reason is not None:
            _send_websocket_text(
                request,
                json.dumps(
                    {
                        "type": "disconnect",
                        "payload": {"reason": disconnect_reason},
                    },
                    separators=(",", ":"),
                ),
            )


class ThreadingSocketServer(socketserver.ThreadingTCPServer):
    """Reusable threaded TCP server for deterministic WebSocket sessions."""

    allow_reuse_address = True
    daemon_threads = True


def _object_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("Expected a list of objects.")
    result: list[dict[str, object]] = []
    for item in cast(list[object], value):
        if not isinstance(item, dict):
            raise ValueError("Expected a list of objects.")
        result.append(cast(dict[str, object], item))
    return result


def _object_pages(value: object) -> list[list[dict[str, object]]]:
    if not isinstance(value, list):
        raise ValueError("history_pages must be a list.")
    return [_object_list(page) for page in cast(list[object], value)]


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _query_metadata(query: dict[str, list[str]]) -> dict[str, object]:
    return {
        key: values[0]
        for key, values in query.items()
        if key in {"channel", "ts", "message_ts", "cursor", "limit"} and values
    }


def _body_metadata(body: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in body.items()
        if key in {"channel", "thread_ts", "ts"} and isinstance(value, str)
    }


def _read_http_headers(connection: socket.socket) -> dict[str, str]:
    raw = bytearray()
    while b"\r\n\r\n" not in raw and len(raw) < 16 * 1024:
        chunk = connection.recv(4096)
        if not chunk:
            break
        raw.extend(chunk)
    lines = raw.decode(errors="replace").split("\r\n")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, separator, value = line.partition(":")
        if separator:
            headers[name.strip().lower()] = value.strip()
    return headers


def _send_websocket_text(connection: socket.socket, text: str) -> None:
    payload = text.encode()
    header = bytearray([0x81])
    if len(payload) < 126:
        header.append(len(payload))
    elif len(payload) < 65_536:
        header.append(126)
        header.extend(struct.pack("!H", len(payload)))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", len(payload)))
    connection.sendall(bytes(header) + payload)


def _receive_websocket_text(connection: socket.socket) -> str:
    first, second = _receive_exact(connection, 2)
    opcode = first & 0x0F
    if opcode == 0x8:
        return ""
    masked = second & 0x80
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _receive_exact(connection, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _receive_exact(connection, 8))[0]
    mask = _receive_exact(connection, 4) if masked else b""
    payload = bytearray(_receive_exact(connection, length))
    if mask:
        for index in range(len(payload)):
            payload[index] ^= mask[index % 4]
    return payload.decode()


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        chunk = connection.recv(size - len(result))
        if not chunk:
            raise ConnectionError("WebSocket connection closed.")
        result.extend(chunk)
    return bytes(result)


def serve() -> None:
    """Run the HTTP and WebSocket fake services until the process exits."""
    websocket_server = ThreadingSocketServer(
        ("0.0.0.0", _WEBSOCKET_PORT),
        SlackWebSocketHandler,
    )
    websocket_thread = threading.Thread(
        target=websocket_server.serve_forever,
        daemon=True,
    )
    websocket_thread.start()
    try:
        ThreadingHTTPServer(
            ("0.0.0.0", _HTTP_PORT),
            SlackHTTPHandler,
        ).serve_forever()
    finally:
        websocket_server.shutdown()
        websocket_server.server_close()


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    serve()
