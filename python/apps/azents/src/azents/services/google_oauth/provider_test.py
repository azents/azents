"""Exercise SDK-owned token grants and real signed identity verification."""

import json
import time
from unittest.mock import create_autospec
from urllib.parse import parse_qs, urlsplit

import google.auth.transport.requests
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from azents.core.config import Config
from azents.core.google_oauth import GoogleOAuthError, GoogleSetup
from azents.core.google_policy import GoogleTask
from azents.core.google_system_setting import GoogleApplicationRegistration
from azents.services.google_oauth.provider import (
    GoogleOAuthProvider,
    GoogleTokenResponse,
)


def _setup() -> GoogleSetup:
    return GoogleSetup(
        client_id="client",
        effective_generation="generation",
        redirect_uri="https://app.example.invalid/oauth/google/callback",
        state_nonce="state-nonce",
        oidc_nonce="identity-nonce",
        code_verifier="x" * 43,
        tasks=(GoogleTask.CALENDAR_READ,),
        timeout=30.0,
        target=None,
    )


def _config() -> Config:
    config = create_autospec(Config, instance=True)
    config.mcp_proxy_url = None
    return config


@pytest.mark.asyncio
async def test_authorization_request_sends_offline_and_distinct_oidc_nonce() -> None:
    async with httpx.AsyncClient() as client:
        provider = GoogleOAuthProvider(client, _config())
        query = parse_qs(
            urlsplit(
                provider.authorization_url(
                    _setup(), "encrypted-state", "pkce-challenge"
                )
            ).query
        )
    assert query["state"] == ["encrypted-state"]
    assert query["nonce"] == ["identity-nonce"]
    assert query["access_type"] == ["offline"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [_setup().redirect_uri]
    assert "prompt" not in query
    assert "include_granted_scopes" not in query
    assert "gmail" not in query["scope"][0]


@pytest.mark.asyncio
async def test_exchange_keeps_provider_scope_before_sdk_normalization() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        body = parse_qs(request.content.decode())
        assert body["grant_type"] == ["authorization_code"]
        assert body["code_verifier"] == ["x" * 43]
        return httpx.Response(
            200,
            json={
                "access_token": "test-access",
                "refresh_token": "test-renewal",
                "expires_in": 3600,
                "scope": "openid email",
                "id_token": "test-signed-identity",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GoogleOAuthProvider(client, _config())
        receipt = await provider.exchange(
            GoogleApplicationRegistration(
                "client", "test-secret", "generation", _setup().redirect_uri
            ),
            _setup(),
            "test-code",
        )
    assert receipt.tokens().granted_scopes == ("email", "openid")
    assert receipt.id_token == "test-signed-identity"


@pytest.mark.asyncio
async def test_refresh_omission_does_not_fabricate_scope_or_refresh_token() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "access_token": "fresh-access",
                    "expires_in": 3600,
                },
            )
        )
    ) as client:
        refreshed = await GoogleOAuthProvider(client, _config()).refresh(
            GoogleApplicationRegistration(
                "client", "secret", "g", _setup().redirect_uri
            ),
            "old-renewal",
        )
    assert refreshed.granted_scopes is None
    assert refreshed.refresh_token is None


@pytest.mark.parametrize("scope", [None, ""])
def test_missing_and_empty_scope_are_not_the_same(scope: str | None) -> None:
    payload: dict[str, object] = {"access_token": "access", "expires_in": 300}
    if scope is not None:
        payload["scope"] = scope
    tokens = GoogleTokenResponse.model_validate(payload).tokens()
    assert tokens.granted_scopes == (None if scope is None else ())


def test_explicit_null_scope_is_malformed_not_verified_empty() -> None:
    receipt = GoogleTokenResponse.model_validate(
        {
            "access_token": "access",
            "expires_in": 300,
            "scope": None,
        }
    )
    with pytest.raises(GoogleOAuthError, match="scope evidence"):
        receipt.tokens()


@pytest.mark.asyncio
async def test_http_error_uses_known_identifier_without_provider_description() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                400,
                json={
                    "error": "invalid_grant",
                    "error_description": "SECRET-CONTENT",
                },
            )
        )
    ) as client:
        with pytest.raises(GoogleOAuthError) as caught:
            await GoogleOAuthProvider(client, _config()).refresh(
                GoogleApplicationRegistration(
                    "client", "secret", "g", "https://app.invalid"
                ),
                "old-renewal",
            )
    assert caught.value.code == "invalid_grant"
    assert "SECRET-CONTENT" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["none", "issuer", "audience", "nonce", "signature"])
async def test_identity_verifies_signature_and_exact_context(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode()
    )
    certs = json.dumps({"test-key": public}).encode()

    class CertificateResponse:
        status = 200
        data = certs

    class CertificateRequest:
        def __call__(
            self,
            url: str,
            method: str = "GET",
            timeout: float = 5.0,
        ) -> CertificateResponse:
            assert method == "GET"
            assert timeout == 5.0
            return CertificateResponse()

    monkeypatch.setattr(
        google.auth.transport.requests,
        "Request",
        lambda session: CertificateRequest(),
    )
    now = int(time.time())
    signing_key = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if fault == "signature"
        else key
    )
    encoded = jwt.encode(
        {
            "iss": "https://wrong.invalid"
            if fault == "issuer"
            else "https://accounts.google.com",
            "aud": "other-client" if fault == "audience" else "client",
            "sub": "verified-subject",
            "iat": now,
            "exp": now + 3600,
            "nonce": "wrong" if fault == "nonce" else "identity-nonce",
            "email": "test@example.invalid",
            "email_verified": True,
        },
        signing_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    receipt = GoogleTokenResponse.model_validate(
        {
            "access_token": "access",
            "expires_in": 300,
            "id_token": encoded,
        }
    )
    async with httpx.AsyncClient() as client:
        provider = GoogleOAuthProvider(client, _config())
        if fault != "none":
            with pytest.raises(GoogleOAuthError) as caught:
                await provider.identity(receipt, "client", "identity-nonce")
            assert caught.value.code == "invalid_identity"
        else:
            identity = await provider.identity(receipt, "client", "identity-nonce")
            assert identity.subject == "verified-subject"
            assert identity.email == "test@example.invalid"
