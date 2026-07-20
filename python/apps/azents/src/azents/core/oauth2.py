"""OAuth2 authentication flow utilities.

Provides pure functions required for OAuth2 Authorization Code Grant flow.
"""

import base64
import dataclasses
import datetime
import hashlib
import json
import os
import secrets
import urllib.parse

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, model_validator


class OAuthTokenErrorResponse(BaseModel):
    """OAuth2 error response.

    RFC 6749 Section 5.2 Parses error responses or non-standard error formats.
    If ``error`` field exists, treat it as provider error.
    """

    error: str
    error_description: str | None = None


class OAuthTokenResponse(BaseModel):
    """OAuth2 token response.

    Validate and parse JSON response from OAuth provider.
    Convert ``expires_in`` in seconds to ``expires_at`` datetime when present.
    """

    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None
    expires_at: datetime.datetime | None = None
    token_type: str = "Bearer"

    @model_validator(mode="after")
    def _compute_expires_at(self) -> "OAuthTokenResponse":
        """Convert ``expires_in`` to ``expires_at``."""
        if self.expires_at is None and self.expires_in is not None:
            self.expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
                seconds=self.expires_in
            )
        return self


def generate_pkce_pair() -> tuple[str, str]:
    """Create PKCE code_verifier and code_challenge pair.

    code_verifier: 64-byte URL-safe random token
    code_challenge: SHA256(code_verifier) → base64url(no padding)

    :return: (code_verifier, code_challenge) tuple
    """
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def build_authorization_url(
    auth_url: str,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    state: str,
    *,
    code_challenge: str | None = None,
    resource: str | None = None,
) -> str:
    """Create OAuth2 authorization URL.

    :param auth_url: OAuth2 authorization endpoint URL
    :param client_id: OAuth2 client ID
    :param redirect_uri: Redirect URI after authorization completion
    :param scopes: OAuth2 scope list to request
    :param state: State parameter for CSRF protection
    :param code_challenge: PKCE code_challenge (S256)
    :param resource: RFC 8707 resource indicator
    :return: Completed authorization URL
    """
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if scopes:
        params["scope"] = " ".join(scopes)
    if code_challenge is not None:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    if resource is not None:
        params["resource"] = resource

    return f"{auth_url}?{urllib.parse.urlencode(params)}"


async def exchange_authorization_code(
    token_url: str,
    client_id: str,
    client_secret: str | None,
    code: str,
    redirect_uri: str,
    *,
    code_verifier: str | None = None,
    resource: str | None = None,
    proxy_url: str | None = None,
) -> OAuthTokenResponse:
    """Exchange authorization code for tokens.

    :param token_url: OAuth2 token endpoint URL
    :param client_id: OAuth2 client ID
    :param client_secret: OAuth2 client secret
    :param code: Authorization code
    :param redirect_uri: Redirect URI used for authorization
    :param code_verifier: PKCE code_verifier
    :param resource: RFC 8707 resource indicator
    :param proxy_url: Egress proxy URL; direct connection when None
    :return: Token response
    :raises httpx.HTTPStatusError: On token exchange failure
    """
    post_data: dict[str, str] = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if client_secret is not None:
        post_data["client_secret"] = client_secret
    if code_verifier is not None:
        post_data["code_verifier"] = code_verifier
    if resource is not None:
        post_data["resource"] = resource

    async with httpx.AsyncClient(proxy=proxy_url) as client:
        response = await client.post(
            token_url,
            data=post_data,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()

    data = response.json()
    return parse_token_response(data)


async def refresh_access_token(
    token_url: str,
    client_id: str,
    client_secret: str | None,
    refresh_token: str,
    *,
    proxy_url: str | None = None,
) -> OAuthTokenResponse:
    """Refresh access token with refresh token.

    :param token_url: OAuth2 token endpoint URL
    :param client_id: OAuth2 client ID
    :param client_secret: OAuth2 client secret
    :param refresh_token: Refresh token
    :param proxy_url: Egress proxy URL; direct connection when None
    :return: Refreshed token response
    :raises httpx.HTTPStatusError: On token refresh failure
    """
    post_data: dict[str, str] = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }
    if client_secret is not None:
        post_data["client_secret"] = client_secret

    async with httpx.AsyncClient(proxy=proxy_url) as client:
        response = await client.post(
            token_url,
            data=post_data,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()

    data = response.json()
    return parse_token_response(data)


def parse_token_response(data: object) -> OAuthTokenResponse:
    """Parse token response.

    Some providers return errors as HTTP 200 + ``{"error": "..."}``. Detect both
    RFC 6749 Section 5.2 error format and non-standard formats.

    :param data: JSON response returned by provider
    :return: Parsed token response
    :raises ValidationError: When token response format is invalid
    :raises OAuthTokenError: When provider returned an error
    """
    if isinstance(data, dict) and "error" in data:
        error_resp = OAuthTokenErrorResponse.model_validate(data)
        detail = error_resp.error
        if error_resp.error_description:
            detail = f"{detail}: {error_resp.error_description}"
        raise OAuthTokenError(detail)

    return OAuthTokenResponse.model_validate(data)


class OAuthTokenError(Exception):
    """Provider returned HTTP 200 with error body."""


# ---------------------------------------------------------------------------
# AES-GCM based OAuth state encryption
# ---------------------------------------------------------------------------


def _derive_aes_key(secret_key: str) -> bytes:
    """Derive AES-256 key from secret_key string."""
    return hashlib.sha256(secret_key.encode()).digest()


def _encrypt_state(payload: dict[str, object], secret_key: str) -> str:
    """Encrypt JSON payload with AES-GCM and return base64url string."""
    key = _derive_aes_key(secret_key)
    iv = os.urandom(12)
    plaintext = json.dumps(payload, separators=(",", ":")).encode()
    ct = AESGCM(key).encrypt(iv, plaintext, None)
    return base64.urlsafe_b64encode(iv + ct).rstrip(b"=").decode("ascii")


def _decrypt_state(state: str, secret_key: str) -> dict[str, object] | None:
    """Decrypt AES-GCM encrypted state. Return None on failure."""
    try:
        # Restore base64url padding
        padded = state + "=" * (-len(state) % 4)
        raw = base64.urlsafe_b64decode(padded)
        if len(raw) < 13:  # 12-byte IV + at least 1 byte
            return None
        iv, ct = raw[:12], raw[12:]
        key = _derive_aes_key(secret_key)
        plaintext = AESGCM(key).decrypt(iv, ct, None)
        data: object = json.loads(plaintext)
        if not isinstance(data, dict):
            return None
        return data
    except Exception:  # noqa: BLE001
        return None


def create_oauth_state(
    toolkit_id: str,
    user_id: str,
    secret_key: str,
    *,
    code_verifier: str | None = None,
) -> str:
    """Create OAuth state parameter encrypted with AES-GCM.

    State is opaque ciphertext, so internal info such as toolkit_id, user_id, and
    code_verifier is not exposed in the URL.

    :param toolkit_id: Toolkit ID
    :param user_id: User ID
    :param secret_key: Encryption key
    :param code_verifier: PKCE code_verifier; omitted when None
    :return: Encrypted state string
    """
    payload: dict[str, object] = {
        "tid": toolkit_id,
        "uid": user_id,
        "n": secrets.token_urlsafe(16),
    }
    if code_verifier is not None:
        payload["cv"] = code_verifier
    return _encrypt_state(payload, secret_key)


def verify_oauth_state(
    state: str, secret_key: str
) -> tuple[str, str, str | None] | None:
    """Decrypt and verify encrypted OAuth state.

    :param state: Encrypted state string
    :param secret_key: Encryption key
    :return: On success, (toolkit_id, user_id, code_verifier or None); on failure, None
    """
    data = _decrypt_state(state, secret_key)
    if data is None:
        return None
    tid = data.get("tid")
    uid = data.get("uid")
    if not isinstance(tid, str) or not isinstance(uid, str):
        return None
    cv = data.get("cv")
    return (tid, uid, cv if isinstance(cv, str) else None)


def create_toolkit_oauth_state(
    *,
    toolkit_id: str,
    workspace_id: str,
    user_id: str,
    redirect_uri: str,
    code_verifier: str,
    secret_key: str,
) -> str:
    """Create encrypted state for toolkit-level OAuth.

    :param toolkit_id: Toolkit ID
    :param workspace_id: Workspace ID
    :param user_id: User ID that started the manager-owned flow
    :param redirect_uri: OAuth redirect URI used for authorization
    :param code_verifier: PKCE code_verifier
    :param secret_key: Encryption key
    :return: Encrypted state string
    """
    payload: dict[str, object] = {
        "type": "toolkit_oauth",
        "tid": toolkit_id,
        "wid": workspace_id,
        "uid": user_id,
        "ru": redirect_uri,
        "cv": code_verifier,
        "n": secrets.token_urlsafe(16),
    }
    return _encrypt_state(payload, secret_key)


def verify_toolkit_oauth_state(
    state: str, secret_key: str
) -> tuple[str, str, str, str, str] | None:
    """Verify encrypted toolkit-level OAuth state.

    :param state: Encrypted state string
    :param secret_key: Encryption key
    :return: toolkit_id, workspace_id, user_id, redirect_uri, code_verifier tuple
    """
    data = _decrypt_state(state, secret_key)
    if data is None or data.get("type") != "toolkit_oauth":
        return None
    tid = data.get("tid")
    wid = data.get("wid")
    uid = data.get("uid")
    redirect_uri = data.get("ru")
    code_verifier = data.get("cv")
    if not isinstance(tid, str):
        return None
    if not isinstance(wid, str):
        return None
    if not isinstance(uid, str):
        return None
    if not isinstance(redirect_uri, str):
        return None
    if not isinstance(code_verifier, str):
        return None
    return (tid, wid, uid, redirect_uri, code_verifier)


@dataclasses.dataclass(frozen=True)
class PlatformOAuthState:
    """Verified GitHub Platform OAuth protocol state."""

    effective_generation: str


def create_platform_oauth_state(
    secret_key: str,
    *,
    effective_generation: str,
) -> str:
    """Create encrypted state for GitHub Platform OAuth.

    :param secret_key: Encryption key
    :param effective_generation: Effective System Setting generation at OAuth start
    :return: Encrypted state string
    """
    payload: dict[str, object] = {
        "type": "installations",
        "generation": effective_generation,
        "n": secrets.token_urlsafe(16),
    }
    return _encrypt_state(payload, secret_key)


def verify_platform_oauth_state(
    state: str,
    secret_key: str,
) -> PlatformOAuthState | None:
    """Verify GitHub Platform OAuth state.

    :param state: Encrypted state string
    :param secret_key: Encryption key
    :return: Verified state or None
    """
    data = _decrypt_state(state, secret_key)
    if data is None or data.get("type") != "installations":
        return None
    effective_generation = data.get("generation")
    if not isinstance(effective_generation, str):
        return None
    return PlatformOAuthState(effective_generation=effective_generation)
