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
    Handler,
    McpRequest,
    Receipt,
    Scenario,
    encode,
    signed_identity,
)
from support.google_provider_fixture import write_material


class Wire(Handler):
    def __init__(self, path: str, body: bytes) -> None:
        self.path = path
        self.headers = HTTPMessage()
        self.headers["Content-Length"] = str(len(body))
        self.rfile = BytesIO(body)
        self.payload: object = None
        self.status: int | None = None

    def json_response(self, status: int, payload: object) -> None:
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
    Handler.calls.clear()
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


def test_fixture_controls_and_mcp_wire_fail_closed() -> None:
    with pytest.raises(ValidationError):
        Scenario.model_validate({"scenario": "unknown"})
    with pytest.raises(ValidationError):
        Scenario.model_validate({"scenario": "partial", "token": "not-admitted"})
    with pytest.raises(ValidationError):
        McpRequest.model_validate({"jsonrpc": "1.0", "method": "tools/list"})
    with pytest.raises(ValidationError):
        McpRequest.model_validate(
            {"jsonrpc": "2.0", "method": "tools/list", "credential": "not-admitted"}
        )
