"""Deterministic Discord REST and Gateway boundary for E2E tests."""

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
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_HTTP_PORT = 8085
_WEBSOCKET_PORT = 8086
_API_PREFIX = "/api/v10"
_VERIFY_KEY = "233988c4fcf6ffd4dcf0590950d79671de856cfa36f65c16a2be13b1613875f0"
_SIGNING_PRIVATE_KEY = (
    "644f7f07f1f19acdc59e86fb018ac1532875f14b4401a3baa2b8a3f88d137d9c"
)
_MULTIPART_FILE_CONTENT = re.compile(
    rb'Content-Disposition: form-data; name="files\[\d+\]"; filename="[^"]*"\r\n'
    rb"[^\r\n]*\r\n\r\n(.*?)\r\n--",
    re.DOTALL,
)


class FakeState:
    """Thread-safe Discord scenarios and sanitized provider evidence."""

    def __init__(self) -> None:
        self.lock = Lock()
        self.reset()

    def reset(self) -> None:
        """Reset all mutable deterministic provider state."""
        with self.lock:
            self.application_id = "100000000000000001"
            self.guild_id = "200000000000000001"
            self.bot_user_id = "300000000000000001"
            self.verify_key = _VERIFY_KEY
            self.gateway_url = "ws://discord-fake:8086"
            self.api_scenarios: dict[str, str] = {}
            self.gateway_dispatches: list[dict[str, object]] = []
            self.gateway_scenarios: list[str] = ["open"]
            self.request_counts: dict[str, int] = {}
            self.requests: list[dict[str, object]] = []
            self.interaction_configurations: list[dict[str, object]] = []
            self.interactions: list[dict[str, object]] = []
            self._interaction_endpoint_url: str | None = None
            self.deliveries: list[dict[str, object]] = []
            self.gateway_connections = 0
            self.gateway_initial_opcodes: list[int] = []
            self.gateway_heartbeats: list[int | None] = []
            self.gateway_dispatch_evidence: list[dict[str, object]] = []
            self.gateway_terminal_events: list[str] = []
            self._message_sequence = 0
            self._nonce_messages: dict[str, str] = {}
            self._root_threads: dict[tuple[str, str], str] = {}

    def configure(self, payload: dict[str, object]) -> None:
        """Apply bounded fake configuration without retaining evidence bodies."""
        allowed = {
            "application_id",
            "guild_id",
            "bot_user_id",
            "api_scenarios",
            "gateway_dispatches",
            "gateway_scenarios",
        }
        if set(payload) - allowed:
            raise ValueError("Unsupported Discord fake configuration field.")
        with self.lock:
            for name in ("application_id", "guild_id", "bot_user_id"):
                value = payload.get(name)
                if value is not None:
                    if not isinstance(value, str) or not value:
                        raise ValueError(f"{name} must be a non-empty string.")
                    setattr(self, name, value)
            scenarios = payload.get("api_scenarios")
            if scenarios is not None:
                if not isinstance(scenarios, dict):
                    raise ValueError("api_scenarios must be an object of strings.")
                raw_scenarios = cast(dict[object, object], scenarios)
                if not all(
                    isinstance(key, str) and isinstance(value, str)
                    for key, value in raw_scenarios.items()
                ):
                    raise ValueError("api_scenarios must be an object of strings.")
                self.api_scenarios = {
                    cast(str, key): cast(str, value)
                    for key, value in raw_scenarios.items()
                }
            dispatches = payload.get("gateway_dispatches")
            if dispatches is not None:
                self.gateway_dispatches = _gateway_dispatches(dispatches)
            gateway_scenarios = payload.get("gateway_scenarios")
            if gateway_scenarios is not None:
                self.gateway_scenarios = _gateway_scenarios(gateway_scenarios)
            self.request_counts = {}
            self.requests = []
            self.interaction_configurations = []
            self.interactions = []
            self._interaction_endpoint_url = None
            self.deliveries = []
            self.gateway_connections = 0
            self.gateway_initial_opcodes = []
            self.gateway_heartbeats = []
            self.gateway_dispatch_evidence = []
            self.gateway_terminal_events = []
            self._message_sequence = 0
            self._nonce_messages = {}
            self._root_threads = {}

    def record_request(
        self,
        operation: str,
        *,
        method: str,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        """Record provider operation metadata with credentials and bodies excluded."""
        with self.lock:
            self.request_counts[operation] = self.request_counts.get(operation, 0) + 1
            self.requests.append(
                {
                    "operation": operation,
                    "method": method,
                    **(metadata or {}),
                }
            )

    def scenario(self, operation: str) -> str:
        """Return the configured controlled outcome for an operation."""
        with self.lock:
            return self.api_scenarios.get(operation, "ok")

    def configure_interaction_endpoint(
        self,
        application_id: str,
        endpoint_url: str,
    ) -> None:
        """Record callback authority without retaining the callback URL."""
        with self.lock:
            self.interaction_configurations.append({"application_id": application_id})
            self._interaction_endpoint_url = endpoint_url

    def deliver_interaction(self, payload: dict[str, object]) -> tuple[int, object]:
        """Sign and send one interaction without retaining its body or signature."""
        interaction_id = payload.get("id")
        interaction_type = payload.get("type")
        if not isinstance(interaction_id, str) or not isinstance(interaction_type, int):
            raise ValueError("Interaction requires an ID and integer type.")
        with self.lock:
            endpoint_url = self._interaction_endpoint_url
        if endpoint_url is None:
            raise ValueError("Discord interaction endpoint is not configured.")
        raw_body = json.dumps(payload, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        signature = Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(_SIGNING_PRIVATE_KEY)
        ).sign(timestamp.encode() + raw_body)
        request = Request(
            endpoint_url,
            data=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Signature-Ed25519": signature.hex(),
                "X-Signature-Timestamp": timestamp,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:  # noqa: S310
                response_status = response.status
                response_payload: object = json.loads(response.read())
        except OSError:
            response_status = 0
            response_payload = None
        with self.lock:
            self.interactions.append(
                {
                    "interaction_id": interaction_id,
                    "interaction_type": interaction_type,
                    "response_status": response_status,
                }
            )
        return response_status, response_payload

    def create_message(
        self,
        *,
        channel_id: str,
        nonce: str | None,
        file_count: int = 0,
        file_bytes: int = 0,
    ) -> str:
        """Create or converge one provider message without retaining visible content."""
        with self.lock:
            if nonce is not None and nonce in self._nonce_messages:
                message_id = self._nonce_messages[nonce]
                outcome = "duplicate"
            else:
                self._message_sequence += 1
                message_id = str(400000000000000000 + self._message_sequence)
                if nonce is not None:
                    self._nonce_messages[nonce] = message_id
                outcome = "created"
            delivery: dict[str, object] = {
                "operation": "create_message",
                "channel_id": channel_id,
                "message_id": message_id,
                "outcome": outcome,
            }
            if file_count:
                delivery["file_count"] = file_count
                delivery["file_bytes"] = file_bytes
            self.deliveries.append(delivery)
            return message_id

    def get_root_thread(
        self, *, parent_channel_id: str, root_message_id: str
    ) -> str | None:
        """Return the current thread channel for one root message without payloads."""
        with self.lock:
            return self._root_threads.get((parent_channel_id, root_message_id))

    def ensure_root_thread(
        self, *, parent_channel_id: str, root_message_id: str
    ) -> str:
        """Create or reuse one deterministic numeric thread channel identity."""
        with self.lock:
            key = (parent_channel_id, root_message_id)
            thread_id = self._root_threads.get(key)
            if thread_id is None:
                self._message_sequence += 1
                thread_id = str(700000000000000000 + self._message_sequence)
                self._root_threads[key] = thread_id
            return thread_id

    def gateway_start(self, opcode: int) -> tuple[list[dict[str, object]], str]:
        """Record one Identify or Resume and return its configured behavior."""
        with self.lock:
            self.gateway_connections += 1
            self.gateway_initial_opcodes.append(opcode)
            scenario_index = min(
                self.gateway_connections - 1,
                len(self.gateway_scenarios) - 1,
            )
            return list(self.gateway_dispatches), self.gateway_scenarios[scenario_index]

    def gateway_heartbeat(self, sequence: int | None) -> None:
        """Record heartbeat sequence only."""
        with self.lock:
            self.gateway_heartbeats.append(sequence)

    def gateway_dispatch_sent(self, dispatch: dict[str, object]) -> None:
        """Record only event identity and sequence, never the dispatch payload."""
        with self.lock:
            self.gateway_dispatch_evidence.append(
                {
                    "event_type": dispatch["event_type"],
                    "sequence": dispatch["sequence"],
                }
            )

    def gateway_terminal(self, scenario: str) -> None:
        """Record one configured Gateway terminal outcome without frame contents."""
        with self.lock:
            self.gateway_terminal_events.append(scenario)

    def evidence(self) -> dict[str, object]:
        """Return test-assertable evidence with tokens, bodies, and URLs excluded."""
        with self.lock:
            return {
                "request_counts": dict(self.request_counts),
                "requests": list(self.requests),
                "interaction_configurations": list(self.interaction_configurations),
                "interactions": list(self.interactions),
                "deliveries": list(self.deliveries),
                "gateway": {
                    "connections": self.gateway_connections,
                    "initial_opcodes": list(self.gateway_initial_opcodes),
                    "heartbeats": list(self.gateway_heartbeats),
                    "dispatches": list(self.gateway_dispatch_evidence),
                    "terminal_events": list(self.gateway_terminal_events),
                },
            }


STATE = FakeState()


class DiscordHTTPHandler(BaseHTTPRequestHandler):
    """Serve deterministic Discord REST behavior and sanitized control state."""

    state: ClassVar[FakeState] = STATE

    def do_GET(self) -> None:
        """Serve health, evidence, authority metadata, and bounded message reads."""
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json_response(200, {"status": "ok"})
            return
        if parsed.path == "/__testenv/state":
            self._json_response(200, self.state.evidence())
            return
        if parsed.path == f"{_API_PREFIX}/oauth2/applications/@me":
            if self._controlled_response(self._operation("get_current_application")):
                return
            self._json_response(
                200,
                {
                    "id": self.state.application_id,
                    "verify_key": self.state.verify_key,
                },
            )
            return
        if parsed.path == f"{_API_PREFIX}/users/@me":
            if self._controlled_response(self._operation("get_current_bot_user")):
                return
            self._json_response(200, {"id": self.state.bot_user_id})
            return
        if parsed.path == f"{_API_PREFIX}/gateway/bot":
            if self._controlled_response(self._operation("gateway_discovery")):
                return
            self._json_response(200, {"url": self.state.gateway_url})
            return
        if parsed.path.startswith(f"{_API_PREFIX}/guilds/") and parsed.path.endswith(
            "/members/@me"
        ):
            if self._controlled_response(self._operation("guild_membership")):
                return
            self._json_response(200, {"user": {"id": self.state.bot_user_id}})
            return
        if "/channels/" in parsed.path and "/messages/" in parsed.path:
            channel_id, message_id = _channel_message_ids(parsed.path)
            if channel_id is not None and message_id is not None:
                if self._controlled_response(
                    self._operation(
                        "get_message",
                        metadata={"channel_id": channel_id, "message_id": message_id},
                    )
                ):
                    return
                payload: dict[str, object] = {
                    "id": message_id,
                    "channel_id": channel_id,
                    "attachments": [],
                }
                thread_id = self.state.get_root_thread(
                    parent_channel_id=channel_id,
                    root_message_id=message_id,
                )
                if thread_id is not None:
                    payload["thread"] = {
                        "id": thread_id,
                        "parent_id": channel_id,
                    }
                self._json_response(200, payload)
                return
        if parsed.path.startswith("/attachments/"):
            if self._controlled_response(self._operation("download_attachment")):
                return
            self._bytes_response(200, b"deterministic-discord-attachment")
            return
        self._json_response(404, {"message": "Unknown fake endpoint."})

    def do_POST(self) -> None:
        """Serve fake control, command, thread, and message mutations."""
        parsed = urlparse(self.path)
        if parsed.path == "/__testenv/reset":
            self.state.reset()
            self._json_response(200, {"status": "ok"})
            return
        if parsed.path == "/__testenv/configure":
            try:
                self.state.configure(self._json_body())
            except ValueError as error:
                self._json_response(400, {"message": str(error)})
                return
            self._json_response(200, {"status": "ok"})
            return
        if parsed.path == "/__testenv/interactions":
            try:
                status, response = self.state.deliver_interaction(self._json_body())
            except ValueError as error:
                self._json_response(400, {"message": str(error)})
                return
            response_object = (
                cast(dict[str, object], response)
                if isinstance(response, dict)
                else None
            )
            self._json_response(
                200,
                {
                    "status": status,
                    "response_type": (
                        response_object.get("type")
                        if response_object is not None
                        else None
                    ),
                },
            )
            return
        application_command_path = parsed.path.startswith(
            f"{_API_PREFIX}/applications/"
        ) and parsed.path.endswith("/commands")
        if application_command_path:
            if self._controlled_response(self._operation("register_command")):
                return
            self._json_response(201, {"id": "500000000000000001"})
            return
        if parsed.path.endswith("/threads"):
            thread_parent_path = parsed.path.removesuffix("/threads")
            channel_id, message_id = _channel_message_ids(thread_parent_path)
            if channel_id is not None and message_id is not None:
                if self._controlled_response(
                    self._operation(
                        "create_thread",
                        metadata={"channel_id": channel_id, "message_id": message_id},
                    )
                ):
                    return
                thread_id = self.state.ensure_root_thread(
                    parent_channel_id=channel_id,
                    root_message_id=message_id,
                )
                self._json_response(
                    201,
                    {"id": thread_id, "parent_id": channel_id},
                )
                return
        if parsed.path.startswith(f"{_API_PREFIX}/channels/") and parsed.path.endswith(
            "/messages"
        ):
            channel_id = parsed.path.split("/")[-2]
            raw_body = self._read_body()
            body = _json_object_or_empty(raw_body)
            nonce = body.get("nonce")
            file_count, file_bytes = _multipart_file_evidence(raw_body)
            message_id = self.state.create_message(
                channel_id=channel_id,
                nonce=nonce if isinstance(nonce, str) else None,
                file_count=file_count,
                file_bytes=file_bytes,
            )
            scenario = self._operation(
                "create_message",
                metadata={"channel_id": channel_id, "message_id": message_id},
            )
            if self._controlled_response(scenario):
                return
            self._json_response(200, {"id": message_id, "channel_id": channel_id})
            return
        self._json_response(404, {"message": "Unknown fake endpoint."})

    def do_PATCH(self) -> None:
        """Configure callback authority or update a message without retaining bodies."""
        parsed = urlparse(self.path)
        if parsed.path.startswith(f"{_API_PREFIX}/applications/"):
            application_id = parsed.path.rsplit("/", 1)[-1]
            scenario = self._operation(
                "configure_interactions_endpoint",
                metadata={"application_id": application_id},
            )
            if self._controlled_response(scenario):
                return
            if scenario == "ok":
                body = self._json_body_or_empty()
                endpoint_url = body.get("interactions_endpoint_url")
                if not isinstance(endpoint_url, str) or not endpoint_url:
                    self._json_response(400, {"message": "Missing callback URL."})
                    return
                self.state.configure_interaction_endpoint(
                    application_id,
                    endpoint_url,
                )
            self._json_response(200, {})
            return
        channel_id, message_id = _channel_message_ids(parsed.path)
        if channel_id is not None and message_id is not None:
            if self._controlled_response(
                self._operation(
                    "update_message",
                    metadata={"channel_id": channel_id, "message_id": message_id},
                )
            ):
                return
            self._json_response(200, {"id": message_id, "channel_id": channel_id})
            return
        self._json_response(404, {"message": "Unknown fake endpoint."})

    def do_DELETE(self) -> None:
        """Delete one fake message without preserving visible content."""
        channel_id, message_id = _channel_message_ids(urlparse(self.path).path)
        if channel_id is None or message_id is None:
            self._json_response(404, {"message": "Unknown fake endpoint."})
            return
        if self._controlled_response(
            self._operation(
                "delete_message",
                metadata={"channel_id": channel_id, "message_id": message_id},
            )
        ):
            return
        self._json_response(204, None)

    def _operation(
        self,
        operation: str,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> str:
        self.state.record_request(operation, method=self.command, metadata=metadata)
        return self.state.scenario(operation)

    def _controlled_response(self, scenario: str) -> bool:
        """Respond to one configured provider failure and stop the handler path."""
        if scenario == "rate_limited":
            self._json_response(429, {"message": "Rate limited."}, {"Retry-After": "1"})
        elif scenario == "forbidden":
            self._json_response(403, {"message": "Forbidden."})
        elif scenario == "rejected":
            self._json_response(400, {"message": "Rejected."})
        elif scenario in {"server_error", "ambiguous"}:
            self._json_response(503, {"message": "Unavailable."})
        elif scenario == "timeout":
            time.sleep(25)
            self._json_response(503, {"message": "Timed out."})
        else:
            return False
        return True

    def _json_body(self) -> dict[str, object]:
        raw = self._read_body()
        payload: object = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Configuration must be an object.")
        return cast(dict[str, object], payload)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def _json_body_or_empty(self) -> dict[str, object]:
        try:
            return self._json_body()
        except ValueError:
            return {}

    def _json_response(
        self,
        status: int,
        payload: dict[str, object] | None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        if payload is None:
            self.end_headers()
            return
        encoded = json.dumps(payload, separators=(",", ":")).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _bytes_response(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        """Suppress fake request logs because they can contain request paths."""
        del format, args


class DiscordWebSocketHandler(socketserver.BaseRequestHandler):
    """Implement the minimal Gateway protocol without a WebSocket dependency."""

    def handle(self) -> None:
        """Run HELLO, Identify/Resume, READY, Dispatch, and heartbeat ACKs."""
        headers = _read_http_headers(self.request)
        key = headers.get("sec-websocket-key")
        if key is None:
            return
        accept = base64.b64encode(
            hashlib.sha1(f"{key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11".encode()).digest()
        ).decode()
        self.request.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        _send_websocket_text(self.request, {"op": 10, "d": {"heartbeat_interval": 500}})
        try:
            initial = _receive_websocket_json(self.request)
        except ConnectionError:
            return
        except ValueError:
            return
        opcode = initial.get("op")
        if not isinstance(opcode, int):
            return
        dispatches, scenario = STATE.gateway_start(opcode)
        if opcode == 6:
            _send_websocket_text(
                self.request,
                {"op": 0, "s": 1, "t": "RESUMED", "d": {}},
            )
        elif opcode == 2:
            _send_websocket_text(
                self.request,
                {
                    "op": 0,
                    "s": 1,
                    "t": "READY",
                    "d": {
                        "session_id": "discord-e2e-session",
                        "resume_gateway_url": "ws://discord-fake:8086",
                    },
                },
            )
        else:
            return
        for dispatch in dispatches:
            _send_websocket_text(
                self.request,
                {
                    "op": 0,
                    "s": dispatch["sequence"],
                    "t": dispatch["event_type"],
                    "d": dispatch["payload"],
                },
            )
            STATE.gateway_dispatch_sent(dispatch)
        if scenario == "reconnect":
            STATE.gateway_terminal(scenario)
            _send_websocket_text(self.request, {"op": 7, "d": None})
            return
        if scenario == "invalid_session_resumable":
            STATE.gateway_terminal(scenario)
            _send_websocket_text(self.request, {"op": 9, "d": True})
            return
        if scenario == "invalid_session_fresh":
            STATE.gateway_terminal(scenario)
            _send_websocket_text(self.request, {"op": 9, "d": False})
            return
        if scenario == "close_4014":
            STATE.gateway_terminal(scenario)
            _send_websocket_close(self.request, 4014)
            return
        self.request.settimeout(0.5)
        while True:
            try:
                payload = _receive_websocket_json(self.request)
            except TimeoutError:
                continue
            except ConnectionError:
                return
            except ValueError:
                return
            if payload.get("op") != 1:
                continue
            sequence = payload.get("d")
            STATE.gateway_heartbeat(sequence if isinstance(sequence, int) else None)
            _send_websocket_text(self.request, {"op": 11, "d": None})


class ThreadingSocketServer(socketserver.ThreadingTCPServer):
    """Thread-per-connection Gateway server."""

    allow_reuse_address = True
    daemon_threads = True


def _gateway_dispatches(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("gateway_dispatches must be a list.")
    result: list[dict[str, object]] = []
    raw_dispatches = cast(list[object], value)
    for item in raw_dispatches:
        if not isinstance(item, dict):
            raise ValueError("gateway_dispatches items must be objects.")
        raw_item = cast(dict[str, object], item)
        sequence = raw_item.get("sequence")
        event_type = raw_item.get("event_type")
        payload = raw_item.get("payload")
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 2
            or not isinstance(event_type, str)
            or not event_type
            or not isinstance(payload, dict)
        ):
            raise ValueError("gateway dispatch is invalid.")
        result.append(
            {"sequence": sequence, "event_type": event_type, "payload": payload}
        )
    return result


def _gateway_scenarios(value: object) -> list[str]:
    """Validate the bounded sequence of controlled Gateway terminal outcomes."""
    if not isinstance(value, list):
        raise ValueError("gateway_scenarios must be a list.")
    allowed = {
        "open",
        "reconnect",
        "invalid_session_resumable",
        "invalid_session_fresh",
        "close_4014",
    }
    scenarios = cast(list[object], value)
    if not scenarios or not all(
        isinstance(item, str) and item in allowed for item in scenarios
    ):
        raise ValueError("gateway_scenarios contains an unsupported value.")
    return [cast(str, item) for item in scenarios]


def _json_object_or_empty(raw_body: bytes) -> dict[str, object]:
    """Parse a JSON request body only when the provider sent an object."""
    try:
        value: object = json.loads(raw_body)
    except UnicodeDecodeError:
        return {}
    except ValueError:
        return {}
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _multipart_file_evidence(raw_body: bytes) -> tuple[int, int]:
    """Extract multipart file count and bytes without retaining file contents."""
    file_parts = _MULTIPART_FILE_CONTENT.findall(raw_body)
    return len(file_parts), sum(len(file_part) for file_part in file_parts)


def _channel_message_ids(path: str) -> tuple[str | None, str | None]:
    parts = path.strip("/").split("/")
    try:
        channel_index = parts.index("channels")
        message_index = parts.index("messages", channel_index)
    except ValueError:
        return None, None
    if len(parts) <= message_index + 1 or channel_index + 1 >= len(parts):
        return None, None
    return parts[channel_index + 1], parts[message_index + 1]


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


def _send_websocket_text(connection: socket.socket, payload: dict[str, object]) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode()
    header = bytearray([0x81])
    if len(body) < 126:
        header.append(len(body))
    elif len(body) < 65_536:
        header.append(126)
        header.extend(struct.pack("!H", len(body)))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", len(body)))
    connection.sendall(bytes(header) + body)


def _send_websocket_close(connection: socket.socket, code: int) -> None:
    """Send one minimal unmasked WebSocket close frame with a provider close code."""
    payload = struct.pack("!H", code)
    connection.sendall(bytes([0x88, len(payload)]) + payload)


def _receive_websocket_json(connection: socket.socket) -> dict[str, object]:
    first, second = _receive_exact(connection, 2)
    opcode = first & 0x0F
    if opcode == 0x8:
        raise ConnectionError("WebSocket closed.")
    if opcode != 0x1:
        raise ValueError("Expected WebSocket text frame.")
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
    value: object = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("WebSocket payload must be an object.")
    return cast(dict[str, object], value)


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        chunk = connection.recv(size - len(result))
        if not chunk:
            raise ConnectionError("WebSocket connection closed.")
        result.extend(chunk)
    return bytes(result)


def serve() -> None:
    """Run the fake REST and Gateway services until process termination."""
    websocket_server = ThreadingSocketServer(
        ("0.0.0.0", _WEBSOCKET_PORT),
        DiscordWebSocketHandler,
    )
    websocket_thread = threading.Thread(
        target=websocket_server.serve_forever,
        daemon=True,
    )
    websocket_thread.start()
    try:
        ThreadingHTTPServer(("0.0.0.0", _HTTP_PORT), DiscordHTTPHandler).serve_forever()
    finally:
        websocket_server.shutdown()
        websocket_server.server_close()


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    serve()
