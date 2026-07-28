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
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import ClassVar, cast
from urllib.parse import parse_qs, urlparse
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
_MULTIPART_JSON_PAYLOAD = re.compile(
    rb'Content-Disposition: form-data; name="payload_json"\r\n'
    rb"[^\r\n]*\r\n\r\n(.*?)\r\n--",
    re.DOTALL,
)
_ALLOWED_API_SCENARIOS = {
    "ok",
    "credentials_invalid",
    "unauthorized",
    "forbidden",
    "permission_denied",
    "not_found",
    "message_not_found",
    "rate_limited",
    "rejected",
    "provider_rejected",
    "server_error",
    "provider_5xx_unknown",
    "ambiguous",
    "transport_unknown",
    "timeout",
    "malformed_json",
    "response_malformed",
    "response_shape_invalid",
    "response_channel_mismatch",
    "thread_response_invalid",
    "thread_create_committed_unknown",
}
_CONFIRMED_CREATE_FAILURE_SCENARIOS = {
    "credentials_invalid",
    "unauthorized",
    "forbidden",
    "permission_denied",
    "not_found",
    "message_not_found",
    "rate_limited",
    "rejected",
    "provider_rejected",
}
_MAX_HISTORY_PAGES = 32
_MAX_HISTORY_MESSAGES_PER_PAGE = 100
_MAX_CONFIGURED_OBJECT_BYTES = 16 * 1024
_MAX_CONFIGURED_ROOT_MESSAGES = 100


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
            self.api_scenario_sequences: dict[str, list[str]] = {}
            self.history_scenario = "ok"
            self.history_pages: dict[str, list[list[dict[str, object]]]] = {}
            self.root_messages: dict[tuple[str, str], dict[str, object]] = {}
            self.allow_synthetic_roots = False
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
            self._message_ids: set[tuple[str, str]] = set()
            self._deleted_message_ids: set[tuple[str, str]] = set()
            self._delivery_barrier_operation: str | None = None
            self._delivery_barrier_occurrence: int | None = None
            self._delivery_barrier_reached = threading.Event()
            self._delivery_barrier_release = threading.Event()
            self._root_threads: dict[tuple[str, str], str] = {}
            self._thread_reconciliation_pending: set[tuple[str, str]] = set()
            self._evidence_sequence = 0
            self.operation_evidence: list[dict[str, object]] = []

    def configure(self, payload: dict[str, object]) -> None:
        """Apply bounded fake configuration without retaining evidence bodies."""
        allowed = {
            "application_id",
            "guild_id",
            "bot_user_id",
            "api_scenarios",
            "api_scenario_sequences",
            "history_scenario",
            "history_pages",
            "root_messages",
            "allow_synthetic_roots",
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
                _validate_api_scenarios(self.api_scenarios)
            sequences = payload.get("api_scenario_sequences")
            if sequences is not None:
                self.api_scenario_sequences = _scenario_sequences(sequences)
            history_scenario = payload.get("history_scenario")
            if history_scenario is not None:
                if not isinstance(history_scenario, str):
                    raise ValueError("history_scenario must be a string.")
                _validate_api_scenarios({"history_messages": history_scenario})
                self.history_scenario = history_scenario
            history_pages = payload.get("history_pages")
            if history_pages is not None:
                self.history_pages = _object_pages(history_pages)
            root_messages = payload.get("root_messages")
            if root_messages is not None:
                self.root_messages = _root_messages(root_messages)
            allow_synthetic_roots = payload.get("allow_synthetic_roots")
            if allow_synthetic_roots is not None:
                if not isinstance(allow_synthetic_roots, bool):
                    raise ValueError("allow_synthetic_roots must be a boolean.")
                self.allow_synthetic_roots = allow_synthetic_roots
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
            self._message_ids = set()
            self._deleted_message_ids = set()
            self._delivery_barrier_operation = None
            self._delivery_barrier_occurrence = None
            self._delivery_barrier_reached.clear()
            self._delivery_barrier_release.clear()
            self._root_threads = {}
            self._thread_reconciliation_pending = set()
            self._evidence_sequence = 0
            self.operation_evidence = []

    def configure_scenarios(self, payload: dict[str, object]) -> None:
        """Change failure controls without resetting provider identities or evidence."""
        allowed = {"api_scenarios", "api_scenario_sequences", "history_scenario"}
        if set(payload) - allowed:
            raise ValueError("Unsupported Discord fake scenario field.")
        with self.lock:
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
                values = {
                    cast(str, key): cast(str, value)
                    for key, value in raw_scenarios.items()
                }
                _validate_api_scenarios(values)
                self.api_scenarios.update(values)
            sequences = payload.get("api_scenario_sequences")
            if sequences is not None:
                self.api_scenario_sequences.update(_scenario_sequences(sequences))
            history_scenario = payload.get("history_scenario")
            if history_scenario is not None:
                if not isinstance(history_scenario, str):
                    raise ValueError("history_scenario must be a string.")
                _validate_api_scenarios({"history_messages": history_scenario})
                self.history_scenario = history_scenario

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
                    "sequence": len(self.requests) + 1,
                    **(metadata or {}),
                }
            )

    def scenario(self, operation: str) -> str:
        """Return the configured controlled outcome for an operation."""
        with self.lock:
            sequence = self.api_scenario_sequences.get(operation)
            if sequence:
                scenario = sequence.pop(0)
                if not sequence:
                    self.api_scenario_sequences.pop(operation, None)
                return scenario
            return self.api_scenarios.get(operation, "ok")

    def configure_delivery_barrier(self, payload: Mapping[str, object]) -> None:
        """Arm one bounded provider delivery barrier for deterministic E2E ordering."""
        operation = payload.get("operation")
        occurrence = payload.get("occurrence")
        if (
            operation != "create_message"
            or not isinstance(occurrence, int)
            or isinstance(occurrence, bool)
            or occurrence < 1
        ):
            raise ValueError(
                "Barrier requires create_message and a positive occurrence."
            )
        with self.lock:
            self._delivery_barrier_operation = "create_message"
            self._delivery_barrier_occurrence = occurrence
            self._delivery_barrier_reached.clear()
            self._delivery_barrier_release.clear()

    def delivery_barrier_evidence(self) -> dict[str, object]:
        """Return safe barrier state without payloads or provider identities."""
        with self.lock:
            operation = self._delivery_barrier_operation
            occurrence = self._delivery_barrier_occurrence
            request_count = (
                self.request_counts.get(operation, 0) if operation is not None else 0
            )
        return {
            "operation": operation,
            "occurrence": occurrence,
            "request_count": request_count,
            "reached": self._delivery_barrier_reached.is_set(),
            "released": self._delivery_barrier_release.is_set(),
        }

    def release_delivery_barrier(self) -> None:
        """Release the armed provider delivery barrier exactly once."""
        self._delivery_barrier_release.set()

    def wait_for_delivery_barrier(self, operation: str) -> bool:
        """Pause one targeted delivery until the test explicitly releases it."""
        with self.lock:
            if (
                self._delivery_barrier_operation != operation
                or self._delivery_barrier_occurrence is None
                or self.request_counts.get(operation, 0)
                != self._delivery_barrier_occurrence
            ):
                return True
        self._delivery_barrier_reached.set()
        return self._delivery_barrier_release.wait(timeout=60)

    def record_operation(
        self,
        event: str,
        *,
        operation: str,
        outcome: str,
        safe_category: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        """Record ordered provider evidence without payloads or transient secrets."""
        with self.lock:
            self._evidence_sequence += 1
            entry: dict[str, object] = {
                "sequence": self._evidence_sequence,
                "event": event,
                "operation": operation,
                "outcome": outcome,
                **(metadata or {}),
            }
            if safe_category is not None:
                entry["safe_category"] = safe_category
            self.operation_evidence.append(entry)

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
                response_status = int(response.status)
                response_payload: object = json.loads(response.read())
        except OSError:
            response_status = 0
            response_payload = None
        with self.lock:
            evidence: dict[str, object] = {
                "interaction_id": interaction_id,
                "interaction_type": interaction_type,
                "response_status": response_status,
            }
            if isinstance(response_payload, dict):
                response_object = cast(dict[str, object], response_payload)
                response_type = response_object.get("type")
                if isinstance(response_type, int):
                    evidence["response_type"] = response_type
                data = response_object.get("data")
                if isinstance(data, dict):
                    data_object = cast(dict[str, object], data)
                    components = data_object.get("components")
                    if isinstance(components, list):
                        evidence["component_count"] = len(
                            cast(list[object], components)
                        )
                    evidence["has_content"] = isinstance(
                        data_object.get("content"), str
                    )
            self.interactions.append(evidence)
        return response_status, cast(object, response_payload)

    def create_message(
        self,
        *,
        channel_id: str,
        nonce: str | None,
        file_count: int = 0,
        file_bytes: int = 0,
    ) -> tuple[str, str]:
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
            self._message_ids.add((channel_id, message_id))
            return message_id, outcome

    def message_exists(self, *, channel_id: str, message_id: str) -> bool:
        """Return whether one configured or created provider message is live."""
        with self.lock:
            key = (channel_id, message_id)
            return key not in self._deleted_message_ids and (
                key in self._message_ids or key in self.root_messages
            )

    def mark_message_deleted(self, *, channel_id: str, message_id: str) -> None:
        """Record a successful provider deletion without retaining message content."""
        with self.lock:
            self._deleted_message_ids.add((channel_id, message_id))

    def record_delivery(
        self,
        *,
        operation: str,
        channel_id: str,
        message_id: str | None,
        outcome: str,
        file_count: int = 0,
        file_bytes: int = 0,
        safe_category: str | None = None,
    ) -> None:
        """Record sanitized provider mutation evidence."""
        delivery: dict[str, object] = {
            "operation": operation,
            "channel_id": channel_id,
            "outcome": outcome,
        }
        if message_id is not None:
            delivery["message_id"] = message_id
        if file_count:
            delivery["file_count"] = file_count
            delivery["file_bytes"] = file_bytes
        if safe_category is not None:
            delivery["safe_category"] = safe_category
        with self.lock:
            self.deliveries.append(delivery)

    def get_root_thread(
        self, *, parent_channel_id: str, root_message_id: str
    ) -> str | None:
        """Return the current thread channel for one root message without payloads."""
        with self.lock:
            thread_id = self._root_threads.get((parent_channel_id, root_message_id))
            if thread_id is not None:
                return thread_id
            message = self.root_messages.get((parent_channel_id, root_message_id))
            thread = message.get("thread") if message is not None else None
            if isinstance(thread, dict):
                thread_object = cast(dict[str, object], thread)
                configured_thread = thread_object.get("id")
                if isinstance(configured_thread, str) and configured_thread:
                    return configured_thread
            return None

    def mark_thread_reconciliation(
        self, *, parent_channel_id: str, root_message_id: str
    ) -> None:
        """Mark the next root read as post-mutation reconciliation evidence."""
        with self.lock:
            self._thread_reconciliation_pending.add(
                (parent_channel_id, root_message_id)
            )

    def consume_thread_reconciliation(
        self, *, parent_channel_id: str, root_message_id: str
    ) -> bool:
        """Consume one post-mutation reconciliation marker."""
        with self.lock:
            key = (parent_channel_id, root_message_id)
            if key not in self._thread_reconciliation_pending:
                return False
            self._thread_reconciliation_pending.remove(key)
            return True

    def root_message(
        self, *, parent_channel_id: str, root_message_id: str
    ) -> dict[str, object] | None:
        """Return one configured root message without exposing it in evidence."""
        with self.lock:
            if (parent_channel_id, root_message_id) in self._deleted_message_ids:
                return None
            message = self.root_messages.get((parent_channel_id, root_message_id))
            return dict(message) if message is not None else None

    def history_page(
        self, *, channel_id: str, before: str | None, limit: int
    ) -> tuple[list[dict[str, object]], str | None]:
        """Return one bounded configured page and its oldest-message cursor."""
        with self.lock:
            pages = self.history_pages.get(channel_id, [])
            messages = [item for page in pages for item in page]
            start = 0
            if before is not None:
                for index, item in enumerate(messages):
                    if item.get("id") == before:
                        start = index + 1
                        break
                else:
                    return [], None
            page = messages[start : start + limit]
            if not page:
                return [], None
            oldest_value = next(
                (
                    item.get("id")
                    for item in reversed(page)
                    if isinstance(item.get("id"), str)
                ),
                None,
            )
            oldest = oldest_value if isinstance(oldest_value, str) else None
            next_cursor = oldest if start + limit < len(messages) else None
            return [dict(item) for item in page], next_cursor

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
                "operations": list(self.operation_evidence),
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
        if parsed.path == "/__testenv/barrier":
            self._json_response(200, self.state.delivery_barrier_evidence())
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
        if parsed.path.startswith(f"{_API_PREFIX}/channels/") and parsed.path.endswith(
            "/messages"
        ):
            channel_id = parsed.path.split("/")[-2]
            query = parse_qs(parsed.query)
            before_values = query.get("before", [])
            before = before_values[0] if before_values else None
            raw_limit = query.get("limit", ["100"])[0]
            try:
                limit = int(raw_limit)
            except ValueError:
                self._json_response(400, {"message": "Invalid history limit."})
                return
            if not 1 <= limit <= _MAX_HISTORY_MESSAGES_PER_PAGE:
                self._json_response(400, {"message": "Invalid history limit."})
                return
            history_metadata: dict[str, object] = {
                "channel_id": channel_id,
                "limit": limit,
            }
            if before is not None:
                history_metadata["cursor"] = before
            scenario = self._operation(
                "get_history",
                metadata=history_metadata,
            )
            if self._controlled_response(scenario):
                safe_category = _safe_category(scenario)
                outcome = (
                    "unknown"
                    if safe_category
                    in {
                        "transport_unknown",
                        "provider_5xx_unknown",
                    }
                    else "failed"
                )
                self.state.record_operation(
                    "history_page",
                    operation="get_history",
                    outcome=outcome,
                    safe_category=safe_category,
                    metadata=history_metadata,
                )
                return
            if scenario in {"malformed_json", "response_malformed"}:
                self.state.record_operation(
                    "history_page",
                    operation="get_history",
                    outcome="unknown",
                    safe_category="response_malformed",
                    metadata=history_metadata,
                )
                self._raw_response(200, b"{malformed")
                return
            page, _ = self.state.history_page(
                channel_id=channel_id,
                before=before,
                limit=limit,
            )
            self.state.record_operation(
                "history_page",
                operation="get_history",
                outcome="delivered",
                metadata=history_metadata,
            )
            self._json_response_array(200, page)
            return
        if "/channels/" in parsed.path and "/messages/" in parsed.path:
            channel_id, message_id = _channel_message_ids(parsed.path)
            if channel_id is not None and message_id is not None:
                scenario = self._operation(
                    "get_message",
                    metadata={"channel_id": channel_id, "message_id": message_id},
                )
                if self._controlled_response(scenario):
                    safe_category = _safe_category(scenario)
                    outcome = (
                        "unknown"
                        if safe_category
                        in {
                            "transport_unknown",
                            "provider_5xx_unknown",
                        }
                        else "failed"
                    )
                    self.state.record_operation(
                        "thread_read",
                        operation="get_message",
                        outcome=outcome,
                        safe_category=safe_category,
                        metadata={
                            "parent_channel_id": channel_id,
                            "root_message_id": message_id,
                        },
                    )
                    return
                payload = self.state.root_message(
                    parent_channel_id=channel_id,
                    root_message_id=message_id,
                )
                if payload is None and not self.state.allow_synthetic_roots:
                    self.state.record_operation(
                        "thread_read",
                        operation="get_message",
                        outcome="missing",
                        safe_category="message_not_found",
                        metadata={
                            "parent_channel_id": channel_id,
                            "root_message_id": message_id,
                        },
                    )
                    self._json_response(404, {"message": "Not found."})
                    return
                payload = payload or {
                    "id": message_id,
                    "channel_id": channel_id,
                    "content": "Synthetic Discord message",
                    "timestamp": "2026-07-26T00:00:00.000000+00:00",
                    "author": {"id": "600000000000000001"},
                    "attachments": [],
                }
                payload["id"] = message_id
                payload["channel_id"] = channel_id
                thread_id = self.state.get_root_thread(
                    parent_channel_id=channel_id,
                    root_message_id=message_id,
                )
                if thread_id is not None:
                    payload["thread"] = {
                        "id": thread_id,
                        "parent_id": channel_id,
                    }
                if scenario == "response_shape_invalid":
                    self.state.record_operation(
                        "thread_read",
                        operation="get_message",
                        outcome="unknown",
                        safe_category="response_shape_invalid",
                        metadata={
                            "parent_channel_id": channel_id,
                            "root_message_id": message_id,
                        },
                    )
                    self._json_response_array(200, [])
                    return
                if scenario == "response_channel_mismatch":
                    payload["channel_id"] = "0"
                if scenario in {"malformed_json", "response_malformed"}:
                    self.state.record_operation(
                        "thread_read",
                        operation="get_message",
                        outcome="unknown",
                        safe_category="response_malformed",
                        metadata={
                            "parent_channel_id": channel_id,
                            "root_message_id": message_id,
                        },
                    )
                    self._raw_response(200, b"{malformed")
                    return
                self.state.record_operation(
                    "thread_reconcile"
                    if self.state.consume_thread_reconciliation(
                        parent_channel_id=channel_id,
                        root_message_id=message_id,
                    )
                    else "thread_read",
                    operation="get_message",
                    outcome="reused" if thread_id is not None else "missing",
                    safe_category=(
                        "response_channel_mismatch"
                        if scenario == "response_channel_mismatch"
                        else None
                    ),
                    metadata={
                        "parent_channel_id": channel_id,
                        "root_message_id": message_id,
                    },
                )
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
        if parsed.path == "/__testenv/scenario":
            try:
                self.state.configure_scenarios(self._json_body())
            except ValueError as error:
                self._json_response(400, {"message": str(error)})
                return
            self._json_response(200, {"status": "ok"})
            return
        if parsed.path == "/__testenv/barrier":
            try:
                self.state.configure_delivery_barrier(self._json_body())
            except ValueError as error:
                self._json_response(400, {"message": str(error)})
                return
            self._json_response(200, {"status": "ok"})
            return
        if parsed.path == "/__testenv/barrier/release":
            self.state.release_delivery_barrier()
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
            application_id, guild_id = _application_command_ids(parsed.path)
            scenario = self._operation(
                "register_command",
                metadata={
                    "application_id": application_id,
                    **({"guild_id": guild_id} if guild_id is not None else {}),
                },
            )
            if self._controlled_response(scenario):
                return
            self.state.record_operation(
                "command_registration",
                operation="register_command",
                outcome="delivered",
                metadata={
                    "application_id": application_id,
                    **({"guild_id": guild_id} if guild_id is not None else {}),
                },
            )
            self._json_response(201, {"id": "500000000000000001"})
            return
        if parsed.path.endswith("/threads"):
            thread_parent_path = parsed.path.removesuffix("/threads")
            channel_id, message_id = _channel_message_ids(thread_parent_path)
            if channel_id is not None and message_id is not None:
                scenario = self._operation(
                    "create_thread",
                    metadata={"channel_id": channel_id, "message_id": message_id},
                )
                if scenario == "thread_create_committed_unknown":
                    thread_id = self.state.ensure_root_thread(
                        parent_channel_id=channel_id,
                        root_message_id=message_id,
                    )
                    self.state.mark_thread_reconciliation(
                        parent_channel_id=channel_id,
                        root_message_id=message_id,
                    )
                    self.state.record_operation(
                        "thread_create",
                        operation="create_thread",
                        outcome="unknown",
                        safe_category="transport_unknown",
                        metadata={
                            "parent_channel_id": channel_id,
                            "root_message_id": message_id,
                            "thread_channel_id": thread_id,
                        },
                    )
                    self._close_connection()
                    return
                if self._controlled_response(scenario):
                    safe_category = _safe_category(scenario)
                    outcome = (
                        "unknown"
                        if safe_category
                        in {
                            "transport_unknown",
                            "provider_5xx_unknown",
                        }
                        else "failed"
                    )
                    self.state.record_operation(
                        "thread_create",
                        operation="create_thread",
                        outcome=outcome,
                        safe_category=safe_category,
                        metadata={
                            "parent_channel_id": channel_id,
                            "root_message_id": message_id,
                        },
                    )
                    return
                thread_id = self.state.ensure_root_thread(
                    parent_channel_id=channel_id,
                    root_message_id=message_id,
                )
                if scenario == "thread_response_invalid":
                    self.state.mark_thread_reconciliation(
                        parent_channel_id=channel_id,
                        root_message_id=message_id,
                    )
                    self.state.record_operation(
                        "thread_create",
                        operation="create_thread",
                        outcome="unknown",
                        safe_category="thread_response_invalid",
                        metadata={
                            "parent_channel_id": channel_id,
                            "root_message_id": message_id,
                        },
                    )
                    self._json_response(201, {"id": "bad", "parent_id": "0"})
                    return
                self.state.record_operation(
                    "thread_create",
                    operation="create_thread",
                    outcome="delivered",
                    metadata={
                        "parent_channel_id": channel_id,
                        "root_message_id": message_id,
                        "thread_channel_id": thread_id,
                    },
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
            body = _multipart_or_json_object(raw_body)
            nonce = body.get("nonce")
            file_count, file_bytes = _multipart_file_evidence(raw_body)
            scenario = self._operation(
                "create_message",
                metadata={"channel_id": channel_id},
            )
            safe_category = _safe_category(scenario)
            if scenario in _CONFIRMED_CREATE_FAILURE_SCENARIOS:
                self._controlled_response(scenario)
                self.state.record_delivery(
                    operation="create_message",
                    channel_id=channel_id,
                    message_id=None,
                    outcome="failed",
                    file_count=file_count,
                    file_bytes=file_bytes,
                    safe_category=safe_category,
                )
                self.state.record_operation(
                    "message",
                    operation="create_message",
                    outcome="failed",
                    safe_category=safe_category,
                    metadata={"channel_id": channel_id},
                )
                return
            message_id, nonce_outcome = self.state.create_message(
                channel_id=channel_id,
                nonce=nonce if isinstance(nonce, str) else None,
                file_count=file_count,
                file_bytes=file_bytes,
            )
            if not self.state.wait_for_delivery_barrier("create_message"):
                self._close_connection()
                return
            if self._controlled_response(scenario):
                outcome = (
                    "unknown"
                    if safe_category in {"transport_unknown", "provider_5xx_unknown"}
                    else "failed"
                )
                self.state.record_delivery(
                    operation="create_message",
                    channel_id=channel_id,
                    message_id=message_id,
                    outcome=outcome,
                    file_count=file_count,
                    file_bytes=file_bytes,
                    safe_category=safe_category,
                )
                self.state.record_operation(
                    "message",
                    operation="create_message",
                    outcome=outcome,
                    safe_category=safe_category,
                    metadata={"channel_id": channel_id, "message_id": message_id},
                )
                return
            if scenario in {"malformed_json", "response_malformed"}:
                self.state.record_operation(
                    "message",
                    operation="create_message",
                    outcome="unknown",
                    safe_category="response_malformed",
                    metadata={"channel_id": channel_id, "message_id": message_id},
                )
                self._raw_response(200, b"{malformed")
                return
            if scenario == "response_shape_invalid":
                self.state.record_operation(
                    "message",
                    operation="create_message",
                    outcome="unknown",
                    safe_category="response_shape_invalid",
                    metadata={"channel_id": channel_id, "message_id": message_id},
                )
                self._json_response(200, {"channel_id": channel_id})
                return
            response_channel_id = (
                "0" if scenario == "response_channel_mismatch" else channel_id
            )
            self.state.record_delivery(
                operation="create_message",
                channel_id=channel_id,
                message_id=message_id,
                outcome=nonce_outcome,
                file_count=file_count,
                file_bytes=file_bytes,
            )
            self.state.record_operation(
                "message",
                operation="create_message",
                outcome=nonce_outcome,
                safe_category=(
                    "response_channel_mismatch"
                    if scenario == "response_channel_mismatch"
                    else None
                ),
                metadata={"channel_id": channel_id, "message_id": message_id},
            )
            self._json_response(
                200, {"id": message_id, "channel_id": response_channel_id}
            )
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
            scenario = self._operation(
                "update_message",
                metadata={"channel_id": channel_id, "message_id": message_id},
            )
            safe_category = _safe_category(scenario)
            if self._controlled_response(scenario):
                outcome = (
                    "unknown"
                    if safe_category in {"transport_unknown", "provider_5xx_unknown"}
                    else "failed"
                )
                self.state.record_delivery(
                    operation="update_message",
                    channel_id=channel_id,
                    message_id=message_id,
                    outcome=outcome,
                    safe_category=safe_category,
                )
                self.state.record_operation(
                    "message",
                    operation="update_message",
                    outcome=outcome,
                    safe_category=safe_category,
                    metadata={"channel_id": channel_id, "message_id": message_id},
                )
                return
            response_channel_id = (
                "0" if scenario == "response_channel_mismatch" else channel_id
            )
            if scenario in {"malformed_json", "response_malformed"}:
                self.state.record_operation(
                    "message",
                    operation="update_message",
                    outcome="unknown",
                    safe_category="response_malformed",
                    metadata={"channel_id": channel_id, "message_id": message_id},
                )
                self._raw_response(200, b"{malformed")
                return
            if not self.state.message_exists(
                channel_id=channel_id,
                message_id=message_id,
            ):
                self.state.record_delivery(
                    operation="update_message",
                    channel_id=channel_id,
                    message_id=None,
                    outcome="failed",
                    safe_category="message_not_found",
                )
                self.state.record_operation(
                    "message",
                    operation="update_message",
                    outcome="failed",
                    safe_category="message_not_found",
                    metadata={"channel_id": channel_id, "message_id": message_id},
                )
                self._json_response(404, {"message": "Not found."})
                return
            self.state.record_delivery(
                operation="update_message",
                channel_id=channel_id,
                message_id=message_id,
                outcome="delivered",
                safe_category=(
                    "response_channel_mismatch"
                    if scenario == "response_channel_mismatch"
                    else None
                ),
            )
            self.state.record_operation(
                "message",
                operation="update_message",
                outcome="delivered",
                safe_category=(
                    "response_channel_mismatch"
                    if scenario == "response_channel_mismatch"
                    else None
                ),
                metadata={"channel_id": channel_id, "message_id": message_id},
            )
            self._json_response(
                200, {"id": message_id, "channel_id": response_channel_id}
            )
            return
        self._json_response(404, {"message": "Unknown fake endpoint."})

    def do_DELETE(self) -> None:
        """Delete one fake message without preserving visible content."""
        channel_id, message_id = _channel_message_ids(urlparse(self.path).path)
        if channel_id is None or message_id is None:
            self._json_response(404, {"message": "Unknown fake endpoint."})
            return
        scenario = self._operation(
            "delete_message",
            metadata={"channel_id": channel_id, "message_id": message_id},
        )
        safe_category = _safe_category(scenario)
        if self._controlled_response(scenario):
            outcome = (
                "unknown"
                if safe_category in {"transport_unknown", "provider_5xx_unknown"}
                else "failed"
            )
            self.state.record_delivery(
                operation="delete_message",
                channel_id=channel_id,
                message_id=message_id,
                outcome=outcome,
                safe_category=safe_category,
            )
            self.state.record_operation(
                "message",
                operation="delete_message",
                outcome=outcome,
                safe_category=safe_category,
                metadata={"channel_id": channel_id, "message_id": message_id},
            )
            return
        if not self.state.message_exists(
            channel_id=channel_id,
            message_id=message_id,
        ):
            self.state.record_delivery(
                operation="delete_message",
                channel_id=channel_id,
                message_id=None,
                outcome="failed",
                safe_category="message_not_found",
            )
            self.state.record_operation(
                "message",
                operation="delete_message",
                outcome="failed",
                safe_category="message_not_found",
                metadata={"channel_id": channel_id, "message_id": message_id},
            )
            self._json_response(404, {"message": "Not found."})
            return
        self.state.mark_message_deleted(
            channel_id=channel_id,
            message_id=message_id,
        )
        self.state.record_delivery(
            operation="delete_message",
            channel_id=channel_id,
            message_id=message_id,
            outcome="delivered",
        )
        self.state.record_operation(
            "message",
            operation="delete_message",
            outcome="delivered",
            metadata={"channel_id": channel_id, "message_id": message_id},
        )
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
            self._json_response(
                429,
                {"message": "Rate limited.", "retry_after": 1},
                {"Retry-After": "1"},
            )
        elif scenario in {"credentials_invalid", "unauthorized"}:
            self._json_response(401, {"message": "Unauthorized."})
        elif scenario in {"forbidden", "permission_denied"}:
            self._json_response(403, {"message": "Forbidden."})
        elif scenario in {"not_found", "message_not_found"}:
            self._json_response(404, {"message": "Not found."})
        elif scenario in {"rejected", "provider_rejected"}:
            self._json_response(400, {"message": "Rejected."})
        elif scenario in {"server_error", "provider_5xx_unknown", "ambiguous"}:
            self._json_response(503, {"message": "Unavailable."})
        elif scenario == "transport_unknown":
            self._close_connection()
        elif scenario == "timeout":
            time.sleep(25)
            self._close_connection()
        else:
            return False
        return True

    def _close_connection(self) -> None:
        """Close one request to model a transport-ambiguous provider outcome."""
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()

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

    def _json_response_array(self, status: int, payload: Sequence[object]) -> None:
        """Return a JSON array without retaining its provider-visible contents."""
        self.send_response(status)
        encoded = json.dumps(payload, separators=(",", ":")).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _raw_response(self, status: int, payload: bytes) -> None:
        """Return a deliberately malformed or provider-shaped response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

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


def _validate_api_scenarios(scenarios: Mapping[str, str]) -> None:
    """Reject unbounded scenario labels before they can affect evidence."""
    if any(value not in _ALLOWED_API_SCENARIOS for value in scenarios.values()):
        raise ValueError("api_scenarios contains an unsupported value.")


def _scenario_sequences(value: object) -> dict[str, list[str]]:
    """Validate one-shot scenario queues without retaining provider details."""
    if not isinstance(value, dict):
        raise ValueError("api_scenario_sequences must be an object.")
    result: dict[str, list[str]] = {}
    for key, raw_values in cast(dict[object, object], value).items():
        if not isinstance(key, str) or not isinstance(raw_values, list):
            raise ValueError("api_scenario_sequences must contain string lists.")
        values = cast(list[object], raw_values)
        if not all(isinstance(item, str) for item in values):
            raise ValueError("api_scenario_sequences must contain string lists.")
        sequence = [cast(str, item) for item in values]
        _validate_api_scenarios(
            {str(index): item for index, item in enumerate(sequence)}
        )
        result[key] = sequence
    return result


def _object_pages(value: object) -> dict[str, list[list[dict[str, object]]]]:
    """Validate bounded history pages while retaining payloads only in fake memory."""
    if not isinstance(value, list):
        raise ValueError("history_pages must be a list.")
    raw_pages = cast(list[object], value)
    if len(raw_pages) > _MAX_HISTORY_PAGES:
        raise ValueError("history_pages exceeds the configured page bound.")
    pages: dict[str, list[list[dict[str, object]]]] = {}
    for raw_page in raw_pages:
        if not isinstance(raw_page, list):
            raise ValueError("history_pages items must be lists.")
        raw_items = cast(list[object], raw_page)
        if not raw_items or len(raw_items) > _MAX_HISTORY_MESSAGES_PER_PAGE:
            raise ValueError("history_pages contains an invalid page size.")
        page: list[dict[str, object]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise ValueError("history_pages messages must be objects.")
            item = cast(dict[str, object], raw_item)
            channel_id = item.get("channel_id")
            if not isinstance(channel_id, str) or not channel_id:
                raise ValueError("history messages require channel_id.")
            if _serialized_size(item) > _MAX_CONFIGURED_OBJECT_BYTES:
                raise ValueError("history message exceeds the configured size bound.")
            page.append(item)
        channel_ids = {cast(str, item["channel_id"]) for item in page}
        if len(channel_ids) != 1:
            raise ValueError("history pages must contain one channel.")
        pages.setdefault(next(iter(channel_ids)), []).append(page)
    return pages


def _root_messages(value: object) -> dict[tuple[str, str], dict[str, object]]:
    """Index configured root messages without exposing their content in evidence."""
    if not isinstance(value, list):
        raise ValueError("root_messages must be a list.")
    raw_items = cast(list[object], value)
    if len(raw_items) > _MAX_CONFIGURED_ROOT_MESSAGES:
        raise ValueError("root_messages exceeds the configured message bound.")
    result: dict[tuple[str, str], dict[str, object]] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise ValueError("root_messages items must be objects.")
        item = cast(dict[str, object], raw_item)
        message_id = item.get("id")
        channel_id = item.get("channel_id")
        if not isinstance(message_id, str) or not isinstance(channel_id, str):
            raise ValueError("root_messages require string id and channel_id.")
        if _serialized_size(item) > _MAX_CONFIGURED_OBJECT_BYTES:
            raise ValueError("root message exceeds the configured size bound.")
        result[(channel_id, message_id)] = item
    return result


def _serialized_size(value: Mapping[str, object]) -> int:
    """Return bounded JSON size for one provider fixture object."""
    try:
        return len(
            json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Provider fixture contains a non-serializable value."
        ) from error


def _safe_category(scenario: str, *, thread: bool = False) -> str | None:
    """Map fake controls to the backend's bounded provider categories."""
    if scenario in {"transport_unknown", "timeout", "thread_create_committed_unknown"}:
        return "transport_unknown"
    if scenario in {"server_error", "provider_5xx_unknown", "ambiguous"}:
        return "provider_5xx_unknown"
    if scenario in {"malformed_json", "response_malformed"}:
        return "response_malformed"
    if scenario == "response_shape_invalid":
        return "response_shape_invalid"
    if scenario == "response_channel_mismatch":
        return "response_channel_mismatch"
    if scenario == "thread_response_invalid" or thread:
        return "thread_response_invalid"
    if scenario in {"credentials_invalid", "unauthorized"}:
        return "credentials_invalid"
    if scenario in {"forbidden", "permission_denied"}:
        return "permission_denied"
    if scenario in {"not_found", "message_not_found"}:
        return "message_not_found"
    if scenario == "rate_limited":
        return "rate_limited"
    if scenario in {"rejected", "provider_rejected"}:
        return "provider_rejected"
    return None


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


def _multipart_or_json_object(raw_body: bytes) -> dict[str, object]:
    """Parse only the multipart JSON envelope, never file names or bytes."""
    match = _MULTIPART_JSON_PAYLOAD.search(raw_body)
    if match is not None:
        return _json_object_or_empty(match.group(1))
    return _json_object_or_empty(raw_body)


def _multipart_file_evidence(raw_body: bytes) -> tuple[int, int]:
    """Extract multipart file count and bytes without retaining file contents."""
    file_parts = _MULTIPART_FILE_CONTENT.findall(raw_body)
    return len(file_parts), sum(len(file_part) for file_part in file_parts)


def _application_command_ids(path: str) -> tuple[str, str | None]:
    """Extract bounded application/Guild identities from command registration paths."""
    parts = path.strip("/").split("/")
    try:
        application_id = parts[parts.index("applications") + 1]
    except ValueError:
        application_id = "unknown"
    except IndexError:
        application_id = "unknown"
    guild_id: str | None = None
    if "guilds" in parts:
        try:
            guild_id = parts[parts.index("guilds") + 1]
        except IndexError:
            guild_id = None
    return application_id, guild_id


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
