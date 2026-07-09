"""xAI OAuth provider client implementation."""

import base64
import datetime
import json
from typing import Any, assert_never

import httpx
from azcommon.result import Failure, Result, Success
from pydantic import ValidationError

from azents.core.xai_oauth import (
    XAI_OAUTH_DEVICE_CODE_URL,
    XAI_OAUTH_SCOPE,
    XAI_OAUTH_TOKEN_URL,
    XaiOAuthConnectionMethod,
)

from .data import (
    DeviceUserCode,
    ProviderEntitlementDenied,
    ProviderPending,
    ProviderRejected,
    ProviderUnavailable,
    TokenSet,
)

_DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"


class XaiOAuthClient:
    """xAI OAuth endpoint invocation client."""

    def __init__(self, http_client: httpx.AsyncClient, *, client_id: str) -> None:
        """Inject HTTP client and configured OAuth client id."""
        self._http_client = http_client
        self._client_id = client_id

    async def request_device_user_code(
        self,
    ) -> Result[
        DeviceUserCode,
        ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
    ]:
        """Request Device user-code."""
        try:
            response = await self._http_client.post(
                XAI_OAUTH_DEVICE_CODE_URL,
                data={"client_id": self._client_id, "scope": XAI_OAUTH_SCOPE},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            return Failure(ProviderUnavailable(reason=str(exc)))

        if not response.is_success:
            return Failure(_provider_error(response))
        try:
            body = response.json()
            if not isinstance(body, dict):
                return Failure(
                    ProviderUnavailable(reason="Provider response was invalid")
                )
            interval = body.get("interval", 5)
            verification_uri = (
                body.get("verification_uri_complete") or body["verification_uri"]
            )
            return Success(
                DeviceUserCode(
                    device_code=body["device_code"],
                    user_code=body["user_code"],
                    verification_uri=verification_uri,
                    interval_seconds=int(interval),
                    expires_in_seconds=int(body["expires_in"]),
                )
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            return Failure(ProviderUnavailable(reason=str(exc)))

    async def poll_device_tokens(
        self,
        *,
        device_code: str,
        connection_method: XaiOAuthConnectionMethod,
    ) -> Result[
        TokenSet,
        ProviderPending
        | ProviderRejected
        | ProviderEntitlementDenied
        | ProviderUnavailable,
    ]:
        """Poll Device authentication completion once."""
        try:
            response = await self._http_client.post(
                XAI_OAUTH_TOKEN_URL,
                data={
                    "grant_type": _DEVICE_CODE_GRANT_TYPE,
                    "client_id": self._client_id,
                    "device_code": device_code,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            return Failure(ProviderUnavailable(reason=str(exc)))

        if response.is_success:
            token_result = _token_set_from_response(response, connection_method)
            match token_result:
                case Success(tokens):
                    return Success(tokens)
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(token_result)

        try:
            body = response.json()
        except ValueError:
            return Failure(_provider_error(response))
        if isinstance(body, dict):
            error = body.get("error")
            if error == "authorization_pending":
                return Failure(ProviderPending(session_id=device_code))
            if error == "slow_down":
                return Failure(ProviderPending(session_id=device_code))
        return Failure(_provider_error(response))

    async def refresh_tokens(
        self,
        *,
        refresh_token: str,
        connection_method: XaiOAuthConnectionMethod,
    ) -> Result[
        TokenSet,
        ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
    ]:
        """Refresh token using Refresh token grant."""
        try:
            response = await self._http_client.post(
                XAI_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self._client_id,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            return Failure(ProviderUnavailable(reason=str(exc)))

        if not response.is_success:
            return Failure(_provider_error(response))
        return _token_set_from_response(
            response, connection_method, default_refresh_token=refresh_token
        )


def _token_set_from_response(
    response: httpx.Response,
    connection_method: XaiOAuthConnectionMethod,
    *,
    default_refresh_token: str | None = None,
) -> Result[
    TokenSet,
    ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
]:
    """Convert Token endpoint success response to internal token model."""
    try:
        body = response.json()
        if not isinstance(body, dict):
            return Failure(ProviderUnavailable(reason="Provider response was invalid"))
        expires_in = int(body.get("expires_in", 3600))
        id_token = body.get("id_token")
        if id_token is not None and not isinstance(id_token, str):
            return Failure(ProviderUnavailable(reason="Provider response was invalid"))
        claims = (
            _decode_unverified_jwt_payload(id_token) if id_token is not None else {}
        )
        next_refresh_token = body.get("refresh_token") or default_refresh_token
        if not isinstance(next_refresh_token, str):
            return Failure(ProviderUnavailable(reason="Provider response was invalid"))
        return Success(
            TokenSet(
                access_token=body["access_token"],
                refresh_token=next_refresh_token,
                id_token=id_token,
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(seconds=expires_in),
                account_id=_optional_str(claims.get("sub")),
                email=_optional_str(claims.get("email")),
                connection_method=connection_method,
            )
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        return Failure(ProviderUnavailable(reason=str(exc)))


def _provider_error(
    response: httpx.Response,
) -> ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable:
    """Convert Provider error to internal error."""
    reason = f"xAI OAuth provider returned HTTP {response.status_code}"
    if response.status_code == 403:
        return ProviderEntitlementDenied(reason=reason)
    if response.status_code == 429 or 500 <= response.status_code:
        return ProviderUnavailable(reason=reason)
    return ProviderRejected(reason=reason)


def _decode_unverified_jwt_payload(token: str) -> dict[str, Any]:
    """Extract only ID token payload metadata without signature verification."""
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode((payload + padding).encode())
        data = json.loads(decoded)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _optional_str(value: object) -> str | None:
    """Return only string metadata."""
    return value if isinstance(value, str) and value else None
