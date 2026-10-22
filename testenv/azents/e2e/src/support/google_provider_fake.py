"""Synthetic fixed-host Google OAuth/identity and direct Workspace API prerequisite.

Public SDKs construct every product request. Only this disposable network peer
stands in for Google; no product URL override or verifier replacement is used.
Resource observations contain operation names and byte counts, never credentials
or mail/file contents. This peer is not a Google interoperability certification.
"""

import base64
import dataclasses
import hashlib
import json
import secrets
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar, Literal
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import BaseModel, ConfigDict

HOSTS = (
    "accounts.google.com",
    "oauth2.googleapis.com",
    "www.googleapis.com",
    "gmail.googleapis.com",
    "apis.google.com",
)
CLIENT_ID = "google-e2e-operator"
CLIENT_SECRET = "google-e2e-synthetic-secret"
SCOPE = "https://www.googleapis.com/auth/"
CALENDAR_SCOPE = SCOPE + "calendar.events.readonly"
FILE_BYTES = b"GOOGLE_E2E_FILE_BYTES\n"

# Disposable browser peer for the documented Picker builder/callback boundary.
# It never stores credentials or grants file access; live Picker remains untested.
PICKER_SCRIPT = b"""
(() => {
  class PickerBuilder {
    setOAuthToken(value) { this.token = value; return this; }
    setDeveloperKey(value) { this.key = value; return this; }
    setAppId(value) { this.app = value; return this; }
    setOrigin(value) { this.origin = value; return this; }
    addView(value) { return this; }
    setCallback(value) { this.callback = value; return this; }
    build() {
      if (!this.token?.startsWith("synthetic-access-") ||
          !this.key || !this.app || this.origin !== location.origin) {
        throw new Error("Invalid synthetic Picker context");
      }
      let element = null;
      const callback = this.callback;
      this.token = null;
      const dispose = () => { element?.remove(); element = null; };
      return {
        setVisible(visible) {
          if (!visible) { dispose(); return; }
          element = document.createElement("dialog");
          element.setAttribute("role", "dialog");
          element.setAttribute("aria-label", "Synthetic Google Picker");
          for (const [label, result] of [
            ["Synthetic Picker select", {action: "picked", docs: [{id: "app-file"}]}],
            ["Synthetic Picker cancel", {action: "cancel"}],
          ]) {
            const button = document.createElement("button");
            button.textContent = label;
            button.onclick = () => callback(result);
            element.append(button);
          }
          document.body.append(element);
          element.showModal();
        },
        dispose,
      };
    }
  }
  window.google = {picker: {PickerBuilder, ViewId: {DOCS: "docs"}}};
  window.gapi = {load(name, options) { options.callback(); }};
})();
"""


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    scenario: Literal[
        "partial",
        "full",
        "empty",
        "missing_scope",
        "no_renewal",
        "changed_account",
        "expiring",
        "revoked",
        "mixed_drive",
        "picker_broad",
        "picker_unknown",
    ]


class ResourceWrite(BaseModel):
    """Decode the bounded SDK resource body at the synthetic ingress."""

    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)
    summary: str | None = None
    name: str | None = None
    raw: str | None = None
    mimeType: str | None = None
    type: str | None = None
    role: str | None = None


@dataclasses.dataclass(frozen=True)
class Receipt:
    nonce: str
    challenge: str
    scopes: str
    subject: str
    redirect: str


def encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def signed_identity(key: rsa.RSAPrivateKey, receipt: Receipt) -> str:
    now = int(time.time())
    header = encode(json.dumps({"alg": "RS256", "kid": "synthetic-google"}).encode())
    payload = encode(
        json.dumps(
            {
                "iss": "https://accounts.google.com",
                "aud": CLIENT_ID,
                "sub": receipt.subject,
                "iat": now,
                "exp": now + 3600,
                "nonce": receipt.nonce,
                "email": receipt.subject + "@example.invalid",
                "email_verified": True,
            }
        ).encode()
    )
    signing_input = (header + "." + payload).encode()
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return header + "." + payload + "." + encode(signature)


class Handler(BaseHTTPRequestHandler):
    key: ClassVar[rsa.RSAPrivateKey]
    certificate: ClassVar[str]
    lock: ClassVar[threading.RLock] = threading.RLock()
    scenario: ClassVar[str] = "partial"
    receipts: ClassVar[dict[str, Receipt]] = {}
    tokens: ClassVar[dict[str, Receipt]] = {}
    renewals: ClassVar[dict[str, Receipt]] = {}
    calls: ClassVar[list[str]] = []
    effects: ClassVar[list[str]] = []
    exchanges: ClassVar[int] = 0
    refreshes: ClassVar[int] = 0
    downloads: ClassVar[int] = 0
    uploaded_bytes: ClassVar[int] = 0
    uploads: ClassVar[dict[str, ResourceWrite]] = {}

    def log_message(self, format: str, *args: object) -> None:
        """Never log codes, state, tokens or authorization-bearing URLs."""

    def bytes_response(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("ETag", '"synthetic-current"')
        self.end_headers()
        self.wfile.write(payload)

    def json_response(self, status: int, payload: object) -> None:
        self.bytes_response(status, json.dumps(payload).encode(), "application/json")

    def body(self) -> bytes:
        size = int(self.headers.get("Content-Length", "0"))
        if size < 0 or size > 262144:
            raise ValueError("Synthetic request is too large.")
        return self.rfile.read(size)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/health":
            self.json_response(200, {"status": "ok"})
        elif parsed.path == "/__testenv/state":
            with self.lock:
                payload = {
                    "scenario": self.scenario,
                    "exchanges": self.exchanges,
                    "refreshes": self.refreshes,
                    "calls": list(self.calls),
                    "effects": list(self.effects),
                    "downloads": self.downloads,
                    "uploaded_bytes": self.uploaded_bytes,
                }
            self.json_response(200, payload)
        elif parsed.path == "/oauth2/v1/certs":
            self.json_response(200, {"synthetic-google": self.certificate})
        elif parsed.path == "/js/api.js":
            self.bytes_response(200, PICKER_SCRIPT, "application/javascript")
        elif parsed.path == "/o/oauth2/v2/auth":
            self.authorize(parse_qs(parsed.query))
        else:
            self.resource("GET", b"")

    def authorize(self, fields: dict[str, list[str]]) -> None:
        required = {"state", "nonce", "redirect_uri", "scope", "code_challenge"}
        if (
            not required <= fields.keys()
            or fields.get("client_id") != [CLIENT_ID]
            or fields.get("prompt") != ["consent"]
            or fields.get("access_type") != ["offline"]
        ):
            self.json_response(400, {"error": "invalid_request"})
            return
        redirect = fields["redirect_uri"][0]
        destination = urlsplit(redirect)
        if (
            destination.hostname
            not in {"azents-web-gateway", "azents-web", "localhost", "127.0.0.1"}
            or destination.path != "/oauth/google/callback"
        ):
            self.json_response(400, {"error": "invalid_redirect"})
            return
        code = "e2e-google-" + secrets.token_hex(12)
        with self.lock:
            granted = (
                fields["scope"][0]
                if self.scenario == "full"
                else "openid email " + CALENDAR_SCOPE
            )
            if self.scenario == "empty":
                granted = "openid email"
            elif self.scenario in {"mixed_drive", "picker_broad", "picker_unknown"}:
                granted = (
                    "openid email " + SCOPE + "drive.readonly " + SCOPE + "drive.file"
                )
            self.receipts[code] = Receipt(
                fields["nonce"][0],
                fields["code_challenge"][0],
                granted,
                "replacement-account"
                if self.scenario == "changed_account"
                else "connected-account",
                redirect,
            )
        self.send_response(302)
        self.send_header(
            "Location",
            redirect + "?" + urlencode({"code": code, "state": fields["state"][0]}),
        )
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        try:
            body = self.body()
            if path == "/__testenv/scenario":
                selected = Scenario.model_validate_json(body)
                with self.lock:
                    Handler.scenario = selected.scenario
                    self.calls.clear()
                    self.effects.clear()
                    Handler.downloads = 0
                    Handler.uploaded_bytes = 0
                self.json_response(200, {"scenario": selected.scenario})
            elif path == "/token":
                self.token(body)
            else:
                self.resource("POST", body)
        except ValueError:
            self.json_response(400, {"error": "invalid_fixture_request"})

    def do_PATCH(self) -> None:
        self.resource("PATCH", self.body())

    def do_PUT(self) -> None:
        self.resource("PUT", self.body())

    def do_DELETE(self) -> None:
        self.resource("DELETE", b"")

    def token(self, body: bytes) -> None:
        fields = parse_qs(body.decode())
        if fields.get("client_id") != [CLIENT_ID] or fields.get("client_secret") != [
            CLIENT_SECRET
        ]:
            self.json_response(400, {"error": "invalid_client"})
            return
        grant = fields.get("grant_type")
        with self.lock:
            if grant == ["authorization_code"]:
                receipt = self.receipts.pop(fields.get("code", [""])[0], None)
                verifier = fields.get("code_verifier", [""])[0]
                if (
                    receipt is None
                    or fields.get("redirect_uri") != [receipt.redirect]
                    or encode(hashlib.sha256(verifier.encode()).digest())
                    != receipt.challenge
                ):
                    receipt = None
                Handler.exchanges += 1
            elif grant == ["refresh_token"]:
                receipt = self.renewals.get(fields.get("refresh_token", [""])[0])
                Handler.refreshes += 1
                if "prompt" in fields or self.scenario == "revoked":
                    receipt = None
            else:
                receipt = None
            if receipt is None:
                self.json_response(400, {"error": "invalid_grant"})
                return
            if grant == ["refresh_token"] and "scope" in fields:
                requested = frozenset(fields["scope"][0].split())
                if requested != {SCOPE + "drive.file"} or not requested <= set(
                    receipt.scopes.split()
                ):
                    self.json_response(400, {"error": "invalid_scope"})
                    return
                receipt = dataclasses.replace(receipt, scopes=SCOPE + "drive.file")
                if self.scenario == "picker_broad":
                    receipt = dataclasses.replace(receipt, scopes=SCOPE + "drive")
            access = "synthetic-access-" + secrets.token_hex(16)
            self.tokens[access] = receipt
            payload: dict[str, object] = {
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": 30
                if self.scenario == "expiring" and grant == ["authorization_code"]
                else 3600,
            }
            if grant == ["authorization_code"]:
                payload["id_token"] = signed_identity(self.key, receipt)
                if self.scenario != "no_renewal":
                    renewal = "synthetic-renewal-" + secrets.token_hex(16)
                    self.renewals[renewal] = receipt
                    payload["refresh_token"] = renewal
            if self.scenario not in {"missing_scope", "picker_unknown"}:
                payload["scope"] = receipt.scopes
        self.json_response(200, payload)

    def admitted(self, method: str, path: str) -> Receipt | None:
        """Emulate Google authorization independently of Azents local policy."""
        bearer = self.headers.get("Authorization", "").removeprefix("Bearer ")
        with self.lock:
            receipt = self.tokens.get(bearer)
            revoked = self.scenario == "revoked"
        if receipt is None or revoked:
            self.json_response(
                401, {"error": {"code": 401, "message": "Invalid credential"}}
            )
            return None
        scopes = set(receipt.scopes.split())
        read = method == "GET"
        valid = False
        if path.startswith("/calendar/v3/"):
            valid = bool(scopes & {SCOPE + "calendar", SCOPE + "calendar.events"})
            if read:
                valid |= bool(
                    scopes
                    & {
                        CALENDAR_SCOPE,
                        SCOPE + "calendar.readonly",
                        SCOPE + "calendar.calendarlist.readonly",
                    }
                )
            if path.endswith("/freeBusy"):
                valid = bool(
                    scopes
                    & {
                        SCOPE + "calendar.events.freebusy",
                        SCOPE + "calendar.freebusy",
                        SCOPE + "calendar",
                        SCOPE + "calendar.readonly",
                    }
                )
            if path == "/calendar/v3/calendars" and method == "POST":
                valid = bool(
                    scopes & {SCOPE + "calendar", SCOPE + "calendar.app.created"}
                )
        elif path.startswith("/gmail/v1/users/me/"):
            valid = bool(scopes & {"https://mail.google.com/", SCOPE + "gmail.modify"})
            if read:
                valid |= SCOPE + "gmail.readonly" in scopes
            elif path.endswith("/messages/send"):
                valid |= bool(scopes & {SCOPE + "gmail.send", SCOPE + "gmail.compose"})
            elif "/drafts" in path:
                valid |= SCOPE + "gmail.compose" in scopes
            if "/settings/filters" in path:
                valid = bool(
                    scopes
                    & {SCOPE + "gmail.settings.basic", "https://mail.google.com/"}
                )
        elif path.startswith(("/drive/v3/", "/upload/drive/v3/")):
            valid = SCOPE + "drive" in scopes
            if read:
                valid |= SCOPE + "drive.readonly" in scopes
            # A known non-app file is not eligible through drive.file alone.
            if "/whole-only" not in path:
                valid |= SCOPE + "drive.file" in scopes
        if not valid:
            self.json_response(
                403, {"error": {"code": 403, "message": "Insufficient Google access"}}
            )
            return None
        return receipt

    def record(self, operation: str, *, effect: bool = False) -> None:
        with self.lock:
            self.calls.append(operation)
            if effect:
                self.effects.append(operation)

    def resource(self, method: str, body: bytes) -> None:
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        if not path.startswith(
            ("/calendar/v3/", "/gmail/v1/", "/drive/v3/", "/upload/drive/v3/")
        ):
            self.json_response(404, {"error": "unknown_fixture_endpoint"})
            return
        if self.headers.get("Host", "").split(":")[0] not in {
            "www.googleapis.com",
            "gmail.googleapis.com",
        }:
            self.json_response(400, {"error": "wrong_fixture_host"})
            return
        receipt = self.admitted(method, path)
        if receipt is None:
            return
        try:
            value = (
                ResourceWrite.model_validate_json(body)
                if body and "json" in self.headers.get("Content-Type", "")
                else ResourceWrite()
            )
        except ValueError:
            self.json_response(400, {"error": "invalid_resource_body"})
            return
        if path.startswith("/calendar/v3/"):
            self.calendar(method, path, value)
        elif path.startswith("/gmail/v1/"):
            self.gmail(method, path, value, receipt)
        else:
            self.drive(method, path, parse_qs(parsed.query), body, value)

    def calendar(self, method: str, path: str, value: ResourceWrite) -> None:
        if path.endswith("/calendarList"):
            self.record("calendar.list_calendars")
            self.json_response(
                200,
                {
                    "items": [
                        {
                            "id": "primary",
                            "summary": "Fixture",
                            "timeZone": "UTC",
                            "accessRole": "owner",
                        }
                    ]
                },
            )
        elif path.endswith("/freeBusy"):
            self.record("calendar.query_freebusy")
            self.json_response(
                200,
                {
                    "timeMin": "2030-01-01T00:00:00Z",
                    "timeMax": "2030-01-02T00:00:00Z",
                    "calendars": {"primary": {"busy": []}},
                },
            )
        elif path == "/calendar/v3/calendars" and method == "POST":
            self.record("calendar.create_calendar", effect=True)
            self.json_response(
                200,
                {
                    "id": "secondary-fixture",
                    "summary": value.summary,
                    "timeZone": "UTC",
                },
            )
        elif "/events" in path:
            event = {
                "id": "event-fixture",
                "summary": "GOOGLE_E2E_READ_OK",
                "status": "confirmed",
                "start": {"dateTime": "2030-01-01T10:00:00Z"},
                "end": {"dateTime": "2030-01-01T11:00:00Z"},
            }
            if method == "GET":
                self.record(
                    "calendar.list_events"
                    if path.endswith("/events")
                    else "calendar.get_event"
                )
                self.json_response(
                    200, {"items": [event]} if path.endswith("/events") else event
                )
            else:
                self.record(
                    "calendar.create_event"
                    if method == "POST"
                    else "calendar.update_event",
                    effect=True,
                )
                self.json_response(
                    200,
                    {**event, **(value.model_extra or {}), "summary": value.summary},
                )
        else:
            self.json_response(404, {"error": "unsupported_calendar_fixture_operation"})

    def gmail(
        self, method: str, path: str, value: ResourceWrite, receipt: Receipt
    ) -> None:
        if path.endswith("/messages/send") and method == "POST":
            if value.raw is None:
                self.json_response(400, {"error": "missing_raw_message"})
                return
            raw = base64.urlsafe_b64decode(value.raw + "=" * (-len(value.raw) % 4))
            with self.lock:
                Handler.uploaded_bytes += len(raw)
            self.record("gmail.send_message", effect=True)
            self.json_response(
                200,
                {
                    "id": "sent-fixture",
                    "threadId": "thread-fixture",
                    "labelIds": ["SENT"],
                },
            )
        elif path.endswith("/settings/sendAs"):
            self.record("gmail.list_send_as")
            self.json_response(
                200,
                {
                    "sendAs": [
                        {
                            "sendAsEmail": receipt.subject + "@example.invalid",
                            "isPrimary": True,
                            "verificationStatus": "accepted",
                        }
                    ]
                },
            )
        elif "/settings/filters" in path:
            self.record(
                "gmail.create_filter" if method == "POST" else "gmail.list_filters",
                effect=method == "POST",
            )
            payload = {"id": "filter-fixture", **(value.model_extra or {})}
            self.json_response(
                200, payload if method == "POST" else {"filter": [payload]}
            )
        elif path.endswith("/attachments/attachment-fixture"):
            self.record("gmail.get_attachment")
            self.json_response(
                200, {"size": len(FILE_BYTES), "data": encode(FILE_BYTES)}
            )
        elif "/messages/" in path:
            self.record("gmail.get_message")
            self.json_response(
                200,
                {
                    "id": path.rsplit("/", 1)[1],
                    "threadId": "thread-fixture",
                    "labelIds": ["INBOX"],
                    "snippet": "Synthetic mail",
                    "payload": {
                        "mimeType": "multipart/mixed",
                        "headers": [
                            {"name": "From", "value": "sender@example.invalid"},
                            {
                                "name": "To",
                                "value": receipt.subject + "@example.invalid",
                            },
                            {"name": "Subject", "value": "Synthetic mail"},
                            {
                                "name": "Message-ID",
                                "value": "<fixture@example.invalid>",
                            },
                        ],
                        "parts": [
                            {
                                "partId": "0",
                                "mimeType": "text/plain",
                                "filename": "",
                                "body": {
                                    "size": 18,
                                    "data": encode(b"GOOGLE_E2E_MAIL_OK"),
                                },
                            },
                            {
                                "partId": "1",
                                "mimeType": "application/octet-stream",
                                "filename": "fixture.bin",
                                "body": {
                                    "size": len(FILE_BYTES),
                                    "attachmentId": "attachment-fixture",
                                },
                            },
                        ],
                    },
                },
            )
        elif path.endswith("/messages"):
            self.record("gmail.search_messages")
            self.json_response(
                200,
                {
                    "messages": [
                        {"id": "message-fixture", "threadId": "thread-fixture"}
                    ],
                    "resultSizeEstimate": 1,
                },
            )
        else:
            self.json_response(404, {"error": "unsupported_gmail_fixture_operation"})

    def drive(
        self,
        method: str,
        path: str,
        query: dict[str, list[str]],
        body: bytes,
        value: ResourceWrite,
    ) -> None:
        identifier = (
            path.rsplit("/files/", maxsplit=1)[-1].split("/", maxsplit=1)[0]
            if "/files/" in path
            else "app-file"
        )
        metadata = {
            "id": identifier,
            "name": "fixture.txt",
            "mimeType": "text/plain",
            "size": str(len(FILE_BYTES)),
            "sha256Checksum": hashlib.sha256(FILE_BYTES).hexdigest(),
            "ownedByMe": True,
            "isAppAuthorized": identifier != "whole-only",
            "capabilities": {
                "canDownload": True,
                "canEdit": True,
                "canModifyContent": True,
                "canCopy": True,
                "canShare": True,
            },
            "parents": [],
            "version": "1",
            "shared": False,
        }
        if "/permissions" in path:
            self.record(
                "drive.create_permission"
                if method == "POST"
                else "drive.list_permissions",
                effect=method == "POST",
            )
            permission = {
                "id": "permission-fixture",
                "type": value.type or "anyone",
                "role": value.role or "reader",
            }
            self.json_response(
                200, permission if method == "POST" else {"permissions": []}
            )
        elif method == "GET" and (
            query.get("alt") == ["media"] or path.endswith("/export")
        ):
            self.record("drive.download_file")
            with self.lock:
                Handler.downloads += len(FILE_BYTES)
            self.bytes_response(200, FILE_BYTES, "text/plain")
        elif method == "GET" and path == "/drive/v3/files":
            self.record("drive.search_files")
            self.json_response(200, {"files": [metadata], "incompleteSearch": False})
        elif method == "GET":
            self.record("drive.get_metadata")
            self.json_response(200, metadata)
        elif method == "POST" and query.get("uploadType") == ["resumable"]:
            upload_id = secrets.token_hex(12)
            with self.lock:
                self.uploads[upload_id] = value
            self.send_response(200)
            self.send_header(
                "Location",
                "https://www.googleapis.com/upload/drive/v3/files?upload_id="
                + upload_id,
            )
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif method == "PUT" and "upload_id" in query:
            with self.lock:
                pending = self.uploads.pop(query["upload_id"][0], None)
            if pending is None:
                self.json_response(404, {"error": "unknown_upload"})
                return
            self.record("drive.create_file", effect=True)
            with self.lock:
                Handler.uploaded_bytes += len(body)
            self.json_response(
                200,
                {
                    **metadata,
                    "id": "created-app-file",
                    "name": pending.name or "fixture.txt",
                    "size": str(len(body)),
                    "sha256Checksum": hashlib.sha256(body).hexdigest(),
                },
            )
        elif method == "POST":
            self.record("drive.create_file", effect=True)
            with self.lock:
                Handler.uploaded_bytes += len(body)
            self.json_response(
                200,
                {
                    **metadata,
                    "id": "created-app-file",
                    "name": value.name or "fixture.txt",
                },
            )
        elif method == "PATCH":
            self.record("drive.update_file", effect=True)
            self.json_response(200, metadata)
        else:
            self.json_response(404, {"error": "unsupported_drive_fixture_operation"})


def serve(root: Path) -> None:
    key = serialization.load_pem_private_key(
        (root / "identity.key").read_bytes(), password=None
    )
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("Synthetic identity requires RSA.")
    Handler.key = key
    Handler.certificate = (root / "identity.pem").read_text()
    control = ThreadingHTTPServer(("0.0.0.0", 8086), Handler)
    threading.Thread(target=control.serve_forever, daemon=True).start()
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(root / "tls.pem", root / "tls.key")
    server = ThreadingHTTPServer(("0.0.0.0", 443), Handler)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    import sys

    serve(Path(sys.argv[1]))
