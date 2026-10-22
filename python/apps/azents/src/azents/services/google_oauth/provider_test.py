"""Exercise SDK-owned token grants and real signed identity verification."""

import json
import logging
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
from azents.core.google_policy import GoogleService
from azents.core.google_system_setting import GoogleApplicationRegistration
from azents.core.google_tool_groups import groups_for_services
from azents.core.google_workspace_policy import GOOGLE_PICKER_SCOPE
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
        services=(GoogleService.CALENDAR,),
        oauth_request_scopes=(
            "https://www.googleapis.com/auth/calendar.events.readonly",
            "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
        ),
        timeout=30.0,
        target=None,
        tool_groups=groups_for_services((GoogleService.CALENDAR,)),
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
    assert query["prompt"] == ["consent"]
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
    def respond(request: httpx.Request) -> httpx.Response:
        body = parse_qs(request.content.decode())
        assert body["grant_type"] == ["refresh_token"]
        assert "prompt" not in body
        return httpx.Response(
            200,
            json={"access_token": "fresh-access", "expires_in": 3600},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        refreshed = await GoogleOAuthProvider(client, _config()).refresh(
            GoogleApplicationRegistration(
                "client", "secret", "g", _setup().redirect_uri
            ),
            "old-renewal",
        )
    assert refreshed.granted_scopes is None
    assert refreshed.refresh_token is None


@pytest.mark.parametrize("returned_scope", [None, GOOGLE_PICKER_SCOPE])
async def test_picker_sdk_requests_exact_scope_without_inventing_receipt(
    returned_scope: str | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    requests: list[httpx.Request] = []
    caplog.set_level(logging.DEBUG)

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = parse_qs(request.content.decode())
        assert body["scope"] == [GOOGLE_PICKER_SCOPE]
        assert body["grant_type"] == ["refresh_token"]
        assert body["refresh_token"] == ["SERVER-REFRESH-CANARY"]
        payload: dict[str, object] = {
            "access_token": "PICKER-ACCESS-CANARY",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        if returned_scope is not None:
            payload["scope"] = returned_scope
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        receipt = await GoogleOAuthProvider(client, _config()).refresh_picker(
            GoogleApplicationRegistration(
                "client", "SERVER-SECRET-CANARY", "g", _setup().redirect_uri
            ),
            "SERVER-REFRESH-CANARY",
        )
    assert len(requests) == 1
    assert receipt.scope == returned_scope
    assert receipt.refresh_token is None
    assert ("scope" in receipt.model_fields_set) == (returned_scope is not None)
    assert all(
        value not in caplog.text
        for value in (
            "PICKER-ACCESS-CANARY",
            "SERVER-REFRESH-CANARY",
            "SERVER-SECRET-CANARY",
        )
    )


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
