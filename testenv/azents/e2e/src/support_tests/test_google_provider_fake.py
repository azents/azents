"""Synthetic provider decoding, proof-of-possession and signatures without sockets."""

import base64
import hashlib
import json
from http.client import HTTPMessage
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import ValidationError

from support.google_provider_fake import (
    CLIENT_ID,
    CLIENT_SECRET,
    FILE_BYTES,
    SCOPE,
    Handler,
    Receipt,
    ResourceWrite,
    Scenario,
    encode,
    signed_identity,
)
from support.google_provider_fixture import write_material


class Wire(Handler):
    def __init__(self, path: str, body: bytes, *, bearer: str | None = None) -> None:
        self.path = path
        self.headers = HTTPMessage()
        self.headers["Content-Length"] = str(len(body))
        self.headers["Host"] = "www.googleapis.com"
        self.headers["Content-Type"] = "application/json"
        if bearer is not None:
            self.headers["Authorization"] = "Bearer " + bearer
        self.rfile = BytesIO(body)
        self.payload: object = None
        self.status: int | None = None
        self.response_headers: dict[str, str] = {}

    def send_response(self, code: int, message: str | None = None) -> None:
        self.status = code

    def send_header(self, keyword: str, value: str) -> None:
        self.response_headers[keyword] = value

    def end_headers(self) -> None:
        pass

    def json_response(self, status: int, payload: object) -> None:
        self.status = status
        self.payload = payload

    def bytes_response(self, status: int, payload: bytes, content_type: str) -> None:
        self.status = status
        self.payload = payload


@pytest.fixture()
def provider(tmp_path: Path) -> type[Handler]:
    write_material(tmp_path)
    private = serialization.load_pem_private_key(
        (tmp_path / "identity.key").read_bytes(), password=None
    )
    assert isinstance(private, rsa.RSAPrivateKey)
    Handler.key = private
    Handler.certificate = (tmp_path / "identity.pem").read_text()
    Handler.receipts.clear()
    Handler.tokens.clear()
    Handler.renewals.clear()
    Handler.uploads.clear()
    Handler.calls.clear()
    Handler.effects.clear()
    Handler.exchanges = 0
    Handler.refreshes = 0
    Handler.downloads = 0
    Handler.uploaded_bytes = 0
    Handler.scenario = "partial"
    return Handler


def test_ephemeral_tls_identity_and_signed_nonce_proof(provider: type[Handler]) -> None:
    receipt = Receipt(
        "exact-nonce",
        "challenge",
        "openid",
        "fixture-subject",
        "https://azents-web-gateway:8443/oauth/google/callback",
    )
    encoded = signed_identity(provider.key, receipt)
    header, payload, signature = encoded.split(".")
    certificate = x509.load_pem_x509_certificate(provider.certificate.encode())
    public = certificate.public_key()
    assert isinstance(public, rsa.RSAPublicKey)
    public.verify(
        base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
        (header + "." + payload).encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert claims["nonce"] == "exact-nonce"
    assert claims["iss"] == "https://accounts.google.com" and claims["aud"] == CLIENT_ID


def test_pkce_code_exchange_is_one_use(provider: type[Handler]) -> None:
    verifier = "x" * 43
    provider.receipts["code"] = Receipt(
        "nonce",
        encode(hashlib.sha256(verifier.encode()).digest()),
        "openid email",
        "fixture",
        "https://azents-web-gateway:8443/oauth/google/callback",
    )
    fields = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": "code",
        "code_verifier": verifier,
        "redirect_uri": provider.receipts["code"].redirect,
    }
    first = Wire("/token", urlencode(fields).encode())
    first.do_POST()
    assert first.status == 200
    repeated = Wire("/token", urlencode(fields).encode())
    repeated.do_POST()
    assert repeated.status == 400 and repeated.payload == {"error": "invalid_grant"}
    assert len(provider.tokens) == 1


def test_fixture_controls_and_sdk_resource_body_decode() -> None:
    with pytest.raises(ValidationError):
        Scenario.model_validate({"scenario": "unknown"})
    with pytest.raises(ValidationError):
        Scenario.model_validate({"scenario": "partial", "token": "not-admitted"})
    assert ResourceWrite.model_validate({"raw": "wire-base64"}).raw == "wire-base64"
    with pytest.raises(ValidationError):
        ResourceWrite.model_validate({"raw": {"credential": "not-a-message"}})


def test_direct_scope_denial_has_no_provider_effect(provider: type[Handler]) -> None:
    provider.tokens["read"] = Receipt(
        "", "", SCOPE + "calendar.events.readonly", "fixture", ""
    )
    request = Wire("/calendar/v3/calendars/primary/events", b"{}", bearer="read")
    request.do_POST()
    assert request.status == 403
    assert provider.calls == [] and provider.effects == []
    allowed = Wire("/calendar/v3/calendars/primary/events", b"", bearer="read")
    allowed.do_GET()
    assert allowed.status == 200 and provider.calls == ["calendar.list_events"]


def test_drive_mixed_boundary_and_exact_file_bytes(provider: type[Handler]) -> None:
    provider.tokens["mixed"] = Receipt(
        "", "", SCOPE + "drive.readonly " + SCOPE + "drive.file", "fixture", ""
    )
    whole = Wire("/drive/v3/files/whole-only?alt=media", b"", bearer="mixed")
    whole.do_GET()
    assert whole.status == 200 and whole.payload == FILE_BYTES
    assert provider.downloads == len(FILE_BYTES)
    denied = Wire("/drive/v3/files/whole-only", b"{}", bearer="mixed")
    denied.do_PATCH()
    assert denied.status == 403 and provider.effects == []
    app = Wire("/drive/v3/files/app-file", b"{}", bearer="mixed")
    app.do_PATCH()
    assert app.status == 200 and provider.effects == ["drive.update_file"]
    provider.tokens["file-only"] = Receipt("", "", SCOPE + "drive.file", "fixture", "")
    outside = Wire("/drive/v3/files/whole-only", b"", bearer="file-only")
    outside.do_GET()
    assert outside.status == 403


def test_picker_minimal_refresh_does_not_rewrite_current_grant(
    provider: type[Handler],
) -> None:
    original = Receipt(
        "", "", SCOPE + "drive.readonly " + SCOPE + "drive.file", "fixture", ""
    )
    provider.renewals["renewal"] = original
    fields = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": "renewal",
        "scope": SCOPE + "drive.file",
    }
    scoped = Wire("/token", urlencode(fields).encode())
    scoped.do_POST()
    assert scoped.status == 200 and isinstance(scoped.payload, dict)
    assert scoped.payload["scope"] == SCOPE + "drive.file"
    assert provider.renewals["renewal"] == original
    assert "refresh_token" not in scoped.payload
    state = Wire("/__testenv/state", b"")
    state.do_GET()
    assert "synthetic-access" not in json.dumps(state.payload)


def test_resumable_sdk_upload_receipt_counts_only_committed_bytes(
    provider: type[Handler],
) -> None:
    provider.tokens["file-only"] = Receipt("", "", SCOPE + "drive.file", "fixture", "")
    start = Wire(
        "/upload/drive/v3/files?uploadType=resumable",
        b'{"name":"roundtrip.txt","mimeType":"text/plain"}',
        bearer="file-only",
    )
    start.do_POST()
    assert start.status == 200
    assert provider.effects == [] and provider.uploaded_bytes == 0
    location = start.response_headers["Location"]
    upload = Wire(
        location.removeprefix("https://www.googleapis.com"),
        FILE_BYTES,
        bearer="file-only",
    )
    upload.headers.replace_header("Content-Type", "text/plain")
    upload.do_PUT()
    assert upload.status == 200 and isinstance(upload.payload, dict)
    assert upload.payload["sha256Checksum"] == hashlib.sha256(FILE_BYTES).hexdigest()
    assert provider.effects == ["drive.create_file"]
    assert provider.uploaded_bytes == len(FILE_BYTES)
