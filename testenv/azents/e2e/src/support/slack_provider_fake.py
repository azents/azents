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
_MAX_CONFIGURED_FILE_BYTES = 8 * 1024 * 1024
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
            self.provider_app_id = "A-E2E"
            self.provider_team_id = "T-E2E"
            self.provider_bot_user_id = "U-BOT-E2E"
            self.granted_scopes = (
                "app_mentions:read",
                "channels:history",
                "channels:read",
                "groups:history",
                "groups:read",
                "chat:write",
                "commands",
                "users:read",
                "files:read",
                "files:write",
            )
            self.delivery_scenarios: dict[str, str] = {
                "chat.postMessage": "delivered",
                "chat.update": "delivered",
                "chat.delete": "delivered",
            }
            self.file_scenarios: dict[str, str] = {
                "files.info": "available",
                "file.download": "available",
                "files.getUploadURLExternal": "available",
                "file.upload": "available",
                "files.completeUploadExternal": "available",
            }
            self.view_scenarios: dict[str, str] = {
                "views.open": "available",
                "views.update": "available",
            }
            self.files: dict[str, dict[str, object]] = {}
            self.uploads: dict[str, dict[str, object]] = {}
            self.history_pages: list[list[dict[str, object]]] = []
            self.socket_sessions: list[dict[str, object]] = [
                {"envelopes": [], "disconnect_reason": None}
            ]
            self.request_counts: dict[str, int] = {}
            self.requests: list[dict[str, object]] = []
            self.deliveries: list[dict[str, object]] = []
            self.views: list[dict[str, object]] = []
            self._transient_views: dict[str, dict[str, object]] = {}
            self.socket_connections = 0
            self.socket_envelope_ids: list[str] = []
            self.socket_acknowledgements: list[str] = []
            self._message_sequence = 0
            self._upload_sequence = 0
            self._view_sequence = 0

    def configure(self, payload: dict[str, object]) -> None:
        """Apply one bounded deterministic provider scenario."""
        allowed = {
            "auth_scenario",
            "membership_scenario",
            "history_scenario",
            "permalink_scenario",
            "provider_app_id",
            "provider_team_id",
            "provider_bot_user_id",
            "granted_scopes",
            "delivery_scenarios",
            "file_scenarios",
            "view_scenarios",
            "files",
            "history_pages",
            "socket_sessions",
        }
        if set(payload) - allowed:
            raise ValueError("Unsupported Slack fake configuration field.")
        with self.lock:
            for name in (
                "auth_scenario",
                "membership_scenario",
                "history_scenario",
                "permalink_scenario",
                "provider_app_id",
                "provider_team_id",
                "provider_bot_user_id",
            ):
                value = payload.get(name)
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError(f"{name} must be a string.")
                    setattr(self, name, value)
            granted_scopes = payload.get("granted_scopes")
            if granted_scopes is not None:
                if not isinstance(granted_scopes, list) or not all(
                    isinstance(scope, str)
                    for scope in cast(list[object], granted_scopes)
                ):
                    raise ValueError("granted_scopes must be a list of strings.")
                self.granted_scopes = tuple(cast(list[str], granted_scopes))
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
            file_scenarios = payload.get("file_scenarios")
            if file_scenarios is not None:
                if not isinstance(file_scenarios, dict):
                    raise ValueError("file_scenarios must be an object.")
                self.file_scenarios = {
                    str(key): str(value)
                    for key, value in cast(
                        dict[object, object],
                        file_scenarios,
                    ).items()
                }
            view_scenarios = payload.get("view_scenarios")
            if view_scenarios is not None:
                if not isinstance(view_scenarios, dict):
                    raise ValueError("view_scenarios must be an object.")
                self.view_scenarios = {
                    str(key): str(value)
                    for key, value in cast(
                        dict[object, object],
                        view_scenarios,
                    ).items()
                }
            files = payload.get("files")
            if files is not None:
                self.files = _configured_files(files)
            history_pages = payload.get("history_pages")
            if history_pages is not None:
                self.history_pages = _object_pages(history_pages)
            socket_sessions = payload.get("socket_sessions")
            if socket_sessions is not None:
                self.socket_sessions = _socket_sessions(socket_sessions)
            self.request_counts = {}
            self.requests = []
            self.deliveries = []
            self.views = []
            self._transient_views = {}
            self.uploads = {}
            self.socket_connections = 0
            self.socket_envelope_ids = []
            self.socket_acknowledgements = []
            self._upload_sequence = 0
            self._view_sequence = 0

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

    def next_upload(self, *, expected_length: int) -> tuple[str, str]:
        """Allocate one deterministic temporary upload identity and path."""
        with self.lock:
            self._upload_sequence += 1
            file_id = f"F-UPLOAD-{self._upload_sequence}"
            upload_path = f"/upload/{file_id}"
            self.uploads[file_id] = {
                "expected_length": expected_length,
                "received_length": None,
                "uploaded": False,
            }
            return file_id, upload_path

    def record_upload(
        self,
        *,
        file_id: str,
        received_length: int,
        content_sha256: str,
    ) -> bool:
        """Record sanitized upload length and digest evidence."""
        with self.lock:
            upload = self.uploads.get(file_id)
            if upload is None:
                return False
            expected_length = upload.get("expected_length")
            matched = expected_length == received_length
            upload["received_length"] = received_length
            upload["content_sha256"] = content_sha256
            upload["uploaded"] = matched
            return matched

    def record_view(
        self,
        *,
        operation: str,
        requested_view_id: str | None,
        callback_id: str | None,
        private_metadata: str | None,
        route_ids: list[str],
        has_submit: bool,
    ) -> tuple[str, str]:
        """Record bounded view evidence without persisting signed metadata."""
        with self.lock:
            self._view_sequence += 1
            view_id = requested_view_id or f"V-E2E-{self._view_sequence}"
            view_hash = f"hash-{self._view_sequence}"
            control_scope = _view_control_scope(callback_id)
            self.views.append(
                {
                    "operation": operation,
                    "control_scope": control_scope,
                    "route_count": len(route_ids),
                    "has_submit": has_submit,
                    "outcome": "delivered",
                }
            )
            self._transient_views[control_scope] = {
                "view_id": view_id,
                "view_hash": view_hash,
                "private_metadata": private_metadata,
                "route_ids": route_ids,
            }
            return view_id, view_hash

    def transient_view(self, control_scope: str) -> dict[str, object] | None:
        """Return one test-local signed view handoff outside persistent evidence."""
        with self.lock:
            view = self._transient_views.get(control_scope)
            return dict(view) if view is not None else None

    def completed_uploads(
        self,
        file_ids: list[str],
    ) -> tuple[bool, int]:
        """Return whether every ordered ID uploaded and its aggregate byte count."""
        with self.lock:
            total_bytes = 0
            for file_id in file_ids:
                upload = self.uploads.get(file_id)
                if upload is None or upload.get("uploaded") is not True:
                    return False, 0
                received_length = upload.get("received_length")
                if not isinstance(received_length, int):
                    return False, 0
                total_bytes += received_length
            return True, total_bytes

    def evidence(self) -> dict[str, object]:
        """Return sanitized evidence suitable for test assertions and failure output."""
        with self.lock:
            return {
                "request_counts": dict(self.request_counts),
                "requests": list(self.requests),
                "deliveries": list(self.deliveries),
                "views": list(self.views),
                "socket": {
                    "connections": self.socket_connections,
                    "envelope_ids": list(self.socket_envelope_ids),
                    "acknowledgements": list(self.socket_acknowledgements),
                    "configured_sessions": len(self.socket_sessions),
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
        if parsed.path == "/__testenv/transient-view":
            scope = parse_qs(parsed.query).get("scope", [""])[0]
            self._json_response(200, self.state.transient_view(scope) or {})
            return
        if parsed.path.startswith("/files/"):
            provider_file_id = parsed.path.removeprefix("/files/")
            self.state.record_request(
                "file.download",
                method="GET",
                metadata={"file": provider_file_id},
            )
            self._file_download(provider_file_id)
            return
        operation = parsed.path.removeprefix("/api/")
        query = parse_qs(parsed.query)
        metadata = _query_metadata(query)
        self.state.record_request(operation, method="GET", metadata=metadata)
        if operation == "conversations.info":
            self._conversation_info()
            return
        if operation == "users.info":
            self._user_info(query)
            return
        if operation in {"conversations.history", "conversations.replies"}:
            self._conversation_history(query)
            return
        if operation == "chat.getPermalink":
            self._permalink(query)
            return
        if operation == "bots.info":
            self._bot_info(query)
            return
        if operation == "files.info":
            self._file_info(query)
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
        if self.path.startswith("/upload/"):
            file_id = urlparse(self.path).path.removeprefix("/upload/")
            self._file_upload(file_id)
            return
        parsed_path = urlparse(self.path)
        operation = parsed_path.path.removeprefix("/api/")
        query = {
            key: _form_value(key, values)
            for key, values in parse_qs(
                parsed_path.query,
                keep_blank_values=True,
            ).items()
        }
        body = {**query, **self._json_body()}
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
        if operation in {"views.open", "views.update"}:
            self._view_mutation(operation, body)
            return
        if operation == "files.getUploadURLExternal":
            self._get_upload_url(body)
            return
        if operation == "files.completeUploadExternal":
            self._complete_upload(body)
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
                "team_id": self.state.provider_team_id,
                "user_id": self.state.provider_bot_user_id,
                "bot_id": "B-E2E",
            },
            headers={"X-OAuth-Scopes": ",".join(self.state.granted_scopes)},
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
                    "app_id": self.state.provider_app_id,
                },
            },
        )

    def _view_mutation(
        self,
        operation: str,
        body: dict[str, object],
    ) -> None:
        """Capture bounded selector state without retaining triggers or visible text."""
        with self.state.lock:
            scenario = self.state.view_scenarios.get(operation, "available")
        if scenario == "trigger_expired":
            self._json_response(200, {"ok": False, "error": "trigger_expired"})
            return
        if scenario == "invalid_hash":
            self._json_response(200, {"ok": False, "error": "invalid_hash"})
            return
        if self._common_failure(scenario):
            return
        view = body.get("view")
        typed_view = cast(dict[str, object], view) if isinstance(view, dict) else {}
        route_ids = _selector_route_ids(typed_view)
        callback_id = _optional_string(typed_view, "callback_id")
        private_metadata = _optional_string(typed_view, "private_metadata")
        view_id, view_hash = self.state.record_view(
            operation=operation,
            requested_view_id=_optional_string(body, "view_id"),
            callback_id=callback_id,
            private_metadata=private_metadata,
            route_ids=route_ids,
            has_submit=isinstance(typed_view.get("submit"), dict),
        )
        self._json_response(
            200,
            {
                "ok": True,
                "view": {
                    "id": view_id,
                    "hash": view_hash,
                },
            },
        )

    def _user_info(self, query: dict[str, list[str]]) -> None:
        scenario = self.state.auth_scenario
        if self._common_failure(scenario):
            return
        user_id = query.get("user", ["unknown"])[0]
        self._json_response(
            200,
            {
                "ok": True,
                "user": {
                    "id": user_id,
                    "name": user_id.lower(),
                    "real_name": f"User {user_id}",
                    "profile": {
                        "display_name": f"User {user_id}",
                        "real_name": f"User {user_id}",
                    },
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
                    "name": "e2e",
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

    def _conversation_history(self, query: dict[str, list[str]]) -> None:
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

    def _file_info(self, query: dict[str, list[str]]) -> None:
        scenario = self.state.file_scenarios.get("files.info", "available")
        if self._file_failure(scenario):
            return
        provider_file_id = query.get("file", [""])[0]
        with self.state.lock:
            configured = self.state.files.get(provider_file_id)
            metadata = dict(configured) if configured is not None else None
        if metadata is None:
            self._json_response(200, {"ok": False, "error": "file_not_found"})
            return
        metadata.pop("_content", None)
        host = self.headers.get("Host") or f"slack-fake:{_HTTP_PORT}"
        metadata["url_private_download"] = f"http://{host}/files/{provider_file_id}"
        if scenario == "malformed":
            metadata["id"] = "F-MISMATCH"
        self._json_response(200, {"ok": True, "file": metadata})

    def _file_download(self, provider_file_id: str) -> None:
        scenario = self.state.file_scenarios.get("file.download", "available")
        if scenario == "ambiguous":
            self._close_connection()
            return
        if scenario == "timeout":
            time.sleep(21)
            return
        if scenario == "rate_limited":
            self._json_response(
                429,
                {"ok": False, "error": "ratelimited"},
                headers={"Retry-After": "1"},
            )
            return
        if scenario == "revoked":
            self._json_response(401, {"ok": False, "error": "token_revoked"})
            return
        if scenario == "missing_scope":
            self._json_response(403, {"ok": False, "error": "missing_scope"})
            return
        if scenario in {"missing", "rejected"}:
            status = 404 if scenario == "missing" else 400
            self._json_response(status, {"ok": False, "error": "file_not_found"})
            return
        if scenario == "unavailable":
            self._json_response(503, {"ok": False, "error": "unavailable"})
            return
        with self.state.lock:
            configured = self.state.files.get(provider_file_id)
            content = configured.get("_content") if configured is not None else None
        if not isinstance(content, bytes):
            self._json_response(404, {"ok": False, "error": "file_not_found"})
            return
        declared_length = len(content)
        if scenario == "size_mismatch":
            declared_length += 1
        self._bytes_response(
            200,
            content,
            headers={"Content-Length": str(declared_length)},
        )

    def _get_upload_url(self, body: dict[str, object]) -> None:
        scenario = self.state.file_scenarios.get(
            "files.getUploadURLExternal",
            "available",
        )
        if self._file_failure(scenario):
            return
        length = body.get("length")
        if isinstance(length, bool) or not isinstance(length, int) or length <= 0:
            self._json_response(200, {"ok": False, "error": "invalid_arguments"})
            return
        file_id, upload_path = self.state.next_upload(expected_length=length)
        host = self.headers.get("Host") or f"slack-fake:{_HTTP_PORT}"
        self._json_response(
            200,
            {
                "ok": True,
                "upload_url": f"http://{host}{upload_path}",
                "file_id": file_id,
            },
        )

    def _file_upload(self, file_id: str) -> None:
        scenario = self.state.file_scenarios.get("file.upload", "available")
        content_length = int(self.headers.get("Content-Length", "0"))
        content = self.rfile.read(content_length)
        self.state.record_request(
            "file.upload",
            method="POST",
            metadata={
                "file": file_id,
                "content_length": content_length,
                "received_length": len(content),
                "content_sha256": hashlib.sha256(content).hexdigest(),
            },
        )
        if scenario == "ambiguous":
            self._close_connection()
            return
        if scenario == "timeout":
            time.sleep(21)
            return
        if scenario == "rate_limited":
            self._bytes_response(429, b"rate_limited")
            return
        if scenario == "unavailable":
            self._bytes_response(503, b"unavailable")
            return
        matched = self.state.record_upload(
            file_id=file_id,
            received_length=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
        )
        if scenario in {"rejected", "size_mismatch"} or not matched:
            self._bytes_response(400, b"rejected")
            return
        self._bytes_response(200, b"OK")

    def _complete_upload(self, body: dict[str, object]) -> None:
        scenario = self.state.file_scenarios.get(
            "files.completeUploadExternal",
            "available",
        )
        if scenario == "ambiguous":
            self._close_connection()
            return
        if scenario == "timeout":
            time.sleep(21)
            return
        if self._file_failure(scenario):
            return
        files = _object_list_or_empty(body.get("files"))
        file_ids: list[str] = []
        for item in files:
            file_id = item.get("id")
            if not isinstance(file_id, str) or not file_id:
                self._json_response(
                    200,
                    {"ok": False, "error": "file_not_found"},
                )
                return
            file_ids.append(file_id)
        completed, total_bytes = self.state.completed_uploads(file_ids)
        if not files or not completed:
            self._json_response(200, {"ok": False, "error": "file_not_found"})
            return
        delivery: dict[str, object] = {
            "operation": "files.completeUploadExternal",
            "channel": _optional_string(body, "channel_id"),
            "thread_ts": _optional_string(body, "thread_ts"),
            "file_ids": file_ids,
            "file_count": len(file_ids),
            "total_bytes": total_bytes,
            "has_initial_comment": _optional_string(body, "initial_comment")
            is not None,
            "outcome": "delivered",
        }
        with self.state.lock:
            self.state.deliveries.append(delivery)
        self._json_response(200, {"ok": True, "files": []})

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
        approval_request_id = _approval_request_id(body)
        action_ids, selector_admission_id = _selector_control_evidence(body)
        delivery: dict[str, object] = {
            "operation": operation,
            "channel": _optional_string(body, "channel"),
            "thread_ts": _optional_string(body, "thread_ts"),
            "message_ts": timestamp,
            "outcome": "delivered",
            "approval_request_id": approval_request_id,
        }
        session_path = _session_path(body)
        if session_path is not None:
            delivery["session_path"] = session_path
        presence_state = _session_presence_state(body)
        if presence_state is not None:
            delivery["safe_category"] = f"session_presence_{presence_state}"
        if action_ids:
            delivery["action_ids"] = action_ids
        if selector_admission_id is not None:
            delivery["selector_admission_id"] = selector_admission_id
        blocks = body.get("blocks")
        typed_blocks = cast(list[object], blocks) if isinstance(blocks, list) else []
        if (
            operation == "chat.update"
            and isinstance(blocks, list)
            and any(
                isinstance(block, dict)
                and cast(dict[str, object], block).get("type") == "plan"
                for block in typed_blocks
            )
        ):
            delivery["text"] = _optional_string(body, "text")
            delivery["blocks"] = blocks
        with self.state.lock:
            self.state.deliveries.append(delivery)
        self._json_response(200, {"ok": True, "ts": timestamp})

    def _file_failure(self, scenario: str) -> bool:
        if scenario == "ambiguous":
            self._close_connection()
            return True
        if scenario == "timeout":
            time.sleep(21)
            return True
        if scenario == "missing_scope":
            self._json_response(200, {"ok": False, "error": "missing_scope"})
            return True
        if scenario in {"missing", "rejected"}:
            self._json_response(200, {"ok": False, "error": "file_not_found"})
            return True
        return self._common_failure(scenario)

    def _close_connection(self) -> None:
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()

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
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("application/x-www-form-urlencoded"):
            try:
                encoded = raw_body.decode()
            except UnicodeDecodeError:
                return {}
            return {
                key: _form_value(key, values)
                for key, values in parse_qs(
                    encoded,
                    keep_blank_values=True,
                ).items()
            }
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

    def _bytes_response(
        self,
        status: int,
        body: bytes,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        if headers is None or "Content-Length" not in headers:
            self.send_header("Content-Length", str(len(body)))
        if headers is not None:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


class SlackWebSocketHandler(socketserver.BaseRequestHandler):
    """Serve a minimal deterministic Socket Mode WebSocket."""

    state: ClassVar[FakeState] = STATE
    socket_timeout_seconds: ClassVar[float] = 10

    def handle(self) -> None:
        """Perform the handshake, send configured envelopes, and capture ACKs."""
        request = cast(socket.socket, self.request)
        request.settimeout(self.socket_timeout_seconds)
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
            session_index = min(
                self.state.socket_connections,
                len(self.state.socket_sessions) - 1,
            )
            self.state.socket_connections += 1
            session = self.state.socket_sessions[session_index]
            envelopes = _object_list(session.get("envelopes"))
            disconnect_reason = session.get("disconnect_reason")
            assert disconnect_reason is None or isinstance(disconnect_reason, str)
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
            acknowledged_id = _receive_websocket_acknowledgement(request)
            if acknowledged_id is None:
                return
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
            return
        while True:
            try:
                if not _receive_websocket_text(request):
                    return
            except TimeoutError:
                continue
            except ConnectionError:
                return
            except OSError:
                return


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


def _object_list_or_empty(value: object) -> list[dict[str, object]]:
    """Return structured objects when a provider payload has the expected shape."""
    try:
        return _object_list(value)
    except ValueError:
        return []


def _socket_sessions(value: object) -> list[dict[str, object]]:
    """Validate bounded per-connection Socket Mode fake behavior."""
    sessions = _object_list(value)
    if not sessions:
        raise ValueError("socket_sessions must contain at least one session.")
    result: list[dict[str, object]] = []
    for session in sessions:
        if set(session) - {"envelopes", "disconnect_reason"}:
            raise ValueError("Unsupported Socket Mode session field.")
        envelopes = _object_list(session.get("envelopes"))
        disconnect_reason = session.get("disconnect_reason")
        if disconnect_reason is not None and not isinstance(disconnect_reason, str):
            raise ValueError("Socket Mode disconnect reason must be a string.")
        result.append(
            {
                "envelopes": envelopes,
                "disconnect_reason": disconnect_reason,
            }
        )
    return result


def _form_value(key: str, values: list[str]) -> object:
    """Restore typed Slack form fields while preserving identifiers as strings."""
    if len(values) != 1:
        return values
    value = values[0]
    if key == "length":
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(parsed, int) and not isinstance(parsed, bool):
            return parsed
        return value
    if key not in {"files", "blocks"}:
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _object_pages(value: object) -> list[list[dict[str, object]]]:
    if not isinstance(value, list):
        raise ValueError("history_pages must be a list.")
    return [_object_list(page) for page in cast(list[object], value)]


def _configured_files(value: object) -> dict[str, dict[str, object]]:
    """Parse bounded fake file metadata and keep content outside evidence."""
    allowed = {
        "id",
        "name",
        "title",
        "mimetype",
        "size",
        "mode",
        "external_type",
        "file_access",
        "is_external",
        "deleted",
        "content_base64",
    }
    files: dict[str, dict[str, object]] = {}
    for item in _object_list(value):
        if set(item) - allowed:
            raise ValueError("Unsupported configured Slack file field.")
        provider_file_id = item.get("id")
        if not isinstance(provider_file_id, str) or not provider_file_id:
            raise ValueError("Configured Slack files require an ID.")
        encoded_content = item.get("content_base64")
        if not isinstance(encoded_content, str):
            raise ValueError("Configured Slack files require base64 content.")
        try:
            content = base64.b64decode(encoded_content, validate=True)
        except ValueError as error:
            raise ValueError("Configured Slack file content is invalid.") from error
        if len(content) > _MAX_CONFIGURED_FILE_BYTES:
            raise ValueError("Configured Slack file content is too large.")
        metadata: dict[str, object] = {
            key: field for key, field in item.items() if key != "content_base64"
        }
        metadata.setdefault("size", len(content))
        metadata["_content"] = content
        files[provider_file_id] = metadata
    return files


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _approval_request_id(payload: dict[str, object]) -> str | None:
    """Return the access-request ID from visible fallback text or Block Kit URLs."""
    values = [_optional_string(payload, "text")]
    for block in _object_list_or_empty(payload.get("blocks")):
        for element in _object_list_or_empty(block.get("elements")):
            url = element.get("url")
            if isinstance(url, str):
                values.append(url)
    for value in values:
        if value is None:
            continue
        match = _APPROVAL_PATH.search(value)
        if match is not None:
            return match.group(1)
    return None


def _selector_control_evidence(
    payload: dict[str, object],
) -> tuple[list[str], str | None]:
    """Return selector action IDs and its opaque admission without visible copy."""
    action_ids: list[str] = []
    selector_admission_id: str | None = None
    for block in _object_list_or_empty(payload.get("blocks")):
        for element in _object_list_or_empty(block.get("elements")):
            action_id = element.get("action_id")
            if not isinstance(action_id, str) or not action_id:
                continue
            action_ids.append(action_id)
            if action_id == "azents_agent_selector_open":
                value = element.get("value")
                if isinstance(value, str) and value:
                    selector_admission_id = value
    return action_ids, selector_admission_id


def _query_metadata(query: dict[str, list[str]]) -> dict[str, object]:
    return {
        key: values[0]
        for key, values in query.items()
        if key in {"channel", "user", "ts", "message_ts", "cursor", "limit", "file"}
        and values
    }


def _body_metadata(body: dict[str, object]) -> dict[str, object]:
    metadata: dict[str, object] = {
        key: value
        for key, value in body.items()
        if key in {"channel", "channel_id", "thread_ts", "ts"}
        and isinstance(value, str)
    }
    length = body.get("length")
    if isinstance(length, int) and not isinstance(length, bool):
        metadata["length"] = length
    files = body.get("files")
    if isinstance(files, list):
        metadata["file_count"] = len(cast(list[object], files))
    return metadata


def _session_path(body: dict[str, object]) -> str | None:
    """Extract only the relative Azents Session route from one control payload."""
    for block in _object_list_or_empty(body.get("blocks")):
        for element in _object_list_or_empty(block.get("elements")):
            if element.get("action_id") != "view_azents_session":
                continue
            url = element.get("url")
            if not isinstance(url, str):
                return None
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return None
            return parsed.path if parsed.path.startswith("/w/") else None
    return None


def _session_presence_state(body: dict[str, object]) -> str | None:
    """Classify Session presence without retaining Agent-authored display text."""
    if _session_path(body) is None:
        return None
    for block in _object_list_or_empty(body.get("blocks")):
        text = block.get("text")
        if not isinstance(text, dict):
            continue
        rendered = cast(dict[str, object], text).get("text")
        if not isinstance(rendered, str):
            continue
        if rendered.endswith(" joined this conversation."):
            return "joined"
        if rendered.endswith(" left this conversation."):
            return "left"
    return None


def _selector_route_ids(view: dict[str, object]) -> list[str]:
    """Extract only bounded selector option identities from one modal payload."""
    route_ids: list[str] = []
    for block in _object_list_or_empty(view.get("blocks")):
        element = block.get("element")
        if not isinstance(element, dict):
            continue
        options = cast(dict[str, object], element).get("options")
        for option in _object_list_or_empty(options):
            value = option.get("value")
            if isinstance(value, str) and value:
                route_ids.append(value)
    return route_ids


def _view_control_scope(callback_id: str | None) -> str:
    """Classify a supported Slack modal without retaining callback metadata."""
    if callback_id == "azents_agent_selector":
        return "selector"
    if callback_id == "azents_conversation_setup":
        return "setup"
    if callback_id == "azents_conversation_settings":
        return "settings"
    return "unknown"


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
    _send_websocket_frame(connection, opcode=0x1, payload=text.encode())


def _send_websocket_frame(
    connection: socket.socket,
    *,
    opcode: int,
    payload: bytes,
) -> None:
    header = bytearray([0x80 | opcode])
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
    while True:
        first, second = _receive_exact(connection, 2)
        opcode = first & 0x0F
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
        if opcode == 0x8:
            return ""
        if opcode == 0x9:
            _send_websocket_frame(connection, opcode=0xA, payload=bytes(payload))
            continue
        if opcode == 0xA:
            continue
        if opcode == 0x1:
            return payload.decode()
        raise ConnectionError("Unsupported WebSocket frame.")


def _receive_websocket_acknowledgement(connection: socket.socket) -> str | None:
    """Wait for one ACK while the client connection remains open."""
    previous_timeout = connection.gettimeout()
    connection.settimeout(None)
    try:
        while True:
            try:
                acknowledgement = _receive_websocket_text(connection)
            except OSError:
                return None
            if not acknowledgement:
                return None
            try:
                payload: object = json.loads(acknowledgement)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            acknowledged_id = cast(dict[str, object], payload).get("envelope_id")
            if isinstance(acknowledged_id, str):
                return acknowledged_id
    finally:
        connection.settimeout(previous_timeout)


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
