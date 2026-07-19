"""Kimi OAuth provider client implementation."""

import datetime
from typing import assert_never

import httpx
from azcommon.result import Failure, Result, Success
from pydantic import ValidationError

from azents.core.kimi_oauth import (
    KIMI_OAUTH_CLIENT_ID,
    KimiOAuthConnectionMethod,
    build_kimi_compatibility_headers,
    resolve_kimi_oauth_device_code_url,
    resolve_kimi_oauth_token_url,
)

from .data import (
    DeviceUserCode,
    ProviderPending,
    ProviderRejected,
    ProviderSlowDown,
    ProviderUnavailable,
    TokenSet,
)

_DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"


class KimiOAuthClient:
    """Kimi OAuth endpoint invocation client."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        """Inject HTTP client."""
        self.http_client = http_client

    async def request_device_user_code(
        self,
        *,
        device_id: str,
    ) -> Result[DeviceUserCode, ProviderRejected | ProviderUnavailable]:
        """Request one Kimi device user code."""
        try:
            response = await self.http_client.post(
                resolve_kimi_oauth_device_code_url(),
                data={"client_id": KIMI_OAUTH_CLIENT_ID},
                headers=_headers(device_id=device_id),
            )
        except httpx.HTTPError:
            return Failure(ProviderUnavailable(reason="Kimi OAuth request failed"))

        if not response.is_success:
            return Failure(_provider_error(response))
        try:
            body = response.json()
            if not isinstance(body, dict):
                return Failure(
                    ProviderUnavailable(reason="Provider response was invalid")
                )
            verification_uri = body.get("verification_uri_complete") or body.get(
                "verification_uri"
            )
            if not isinstance(verification_uri, str) or not verification_uri:
                return Failure(
                    ProviderUnavailable(reason="Provider response was invalid")
                )
            return Success(
                DeviceUserCode(
                    device_code=body["device_code"],
                    user_code=body["user_code"],
                    verification_uri=verification_uri,
                    interval_seconds=max(int(body.get("interval") or 5), 1),
                    expires_in_seconds=max(int(body.get("expires_in") or 900), 1),
                )
            )
        except KeyError, TypeError, ValueError, ValidationError:
            return Failure(ProviderUnavailable(reason="Provider response was invalid"))

    async def poll_device_tokens(
        self,
        *,
        device_code: str,
        device_id: str,
        connection_method: KimiOAuthConnectionMethod,
    ) -> Result[
        TokenSet,
        ProviderPending | ProviderSlowDown | ProviderRejected | ProviderUnavailable,
    ]:
        """Poll Kimi device authentication completion once."""
        try:
            response = await self.http_client.post(
                resolve_kimi_oauth_token_url(),
                data={
                    "grant_type": _DEVICE_CODE_GRANT_TYPE,
                    "client_id": KIMI_OAUTH_CLIENT_ID,
                    "device_code": device_code,
                },
                headers=_headers(device_id=device_id),
            )
        except httpx.HTTPError:
            return Failure(ProviderUnavailable(reason="Kimi OAuth request failed"))

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
                return Failure(ProviderSlowDown(session_id=device_code))
        return Failure(_provider_error(response))

    async def refresh_tokens(
        self,
        *,
        refresh_token: str,
        device_id: str,
        connection_method: KimiOAuthConnectionMethod,
    ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
        """Refresh a Kimi token using the refresh-token grant."""
        try:
            response = await self.http_client.post(
                resolve_kimi_oauth_token_url(),
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": KIMI_OAUTH_CLIENT_ID,
                },
                headers=_headers(device_id=device_id),
            )
        except httpx.HTTPError:
            return Failure(ProviderUnavailable(reason="Kimi OAuth request failed"))

        if not response.is_success:
            return Failure(_provider_error(response))
        return _token_set_from_response(
            response,
            connection_method,
            default_refresh_token=refresh_token,
        )


def _headers(*, device_id: str) -> dict[str, str]:
    """Build form and compatibility headers without exposing the device id."""
    return {
        **build_kimi_compatibility_headers(device_id=device_id),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }


def _token_set_from_response(
    response: httpx.Response,
    connection_method: KimiOAuthConnectionMethod,
    *,
    default_refresh_token: str | None = None,
) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
    """Convert a Kimi token endpoint success response to internal data."""
    try:
        body = response.json()
        if not isinstance(body, dict):
            return Failure(ProviderUnavailable(reason="Provider response was invalid"))
        next_refresh_token = body.get("refresh_token") or default_refresh_token
        if not isinstance(next_refresh_token, str) or not next_refresh_token:
            return Failure(ProviderUnavailable(reason="Provider response was invalid"))
        access_token = body["access_token"]
        if not isinstance(access_token, str) or not access_token:
            return Failure(ProviderUnavailable(reason="Provider response was invalid"))
        expires_in = max(int(body.get("expires_in") or 3600), 1)
        return Success(
            TokenSet(
                access_token=access_token,
                refresh_token=next_refresh_token,
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(seconds=expires_in),
                connection_method=connection_method,
            )
        )
    except KeyError, TypeError, ValueError, ValidationError:
        return Failure(ProviderUnavailable(reason="Provider response was invalid"))


def _provider_error(
    response: httpx.Response,
) -> ProviderRejected | ProviderUnavailable:
    """Convert a provider HTTP status to a safe internal error."""
    reason = f"Kimi OAuth provider returned HTTP {response.status_code}"
    if response.status_code == 429 or response.status_code >= 500:
        return ProviderUnavailable(reason=reason)
    return ProviderRejected(reason=reason)
