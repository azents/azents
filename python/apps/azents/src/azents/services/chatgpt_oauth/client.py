"""ChatGPT OAuth provider client implementation."""

import base64
import datetime
import json
from typing import Any

import httpx
from azcommon.result import Failure, Result, Success
from pydantic import ValidationError

from azents.core.chatgpt_oauth import (
    CHATGPT_OAUTH_CLIENT_ID,
    ChatGPTOAuthConnectionMethod,
    resolve_chatgpt_oauth_device_token_url,
    resolve_chatgpt_oauth_device_user_code_url,
)

from .data import (
    DeviceAuthorizationCode,
    DeviceUserCode,
    ProviderPending,
    ProviderRejected,
    ProviderUnavailable,
    TokenSet,
)


class ChatGPTOAuthClient:
    """ChatGPT OAuth endpoint invocation client."""

    def __init__(self, http_client: httpx.AsyncClient, *, token_url: str) -> None:
        """Inject the HTTP client and OAuth token endpoint."""
        self._http_client = http_client
        self._token_url = token_url

    async def request_device_user_code(
        self,
    ) -> Result[DeviceUserCode, ProviderRejected | ProviderUnavailable]:
        """Request Device user-code."""
        try:
            response = await self._http_client.post(
                resolve_chatgpt_oauth_device_user_code_url(),
                json={"client_id": CHATGPT_OAUTH_CLIENT_ID},
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
            return Success(
                DeviceUserCode(
                    device_auth_id=body["device_auth_id"],
                    user_code=body.get("user_code") or body["usercode"],
                    interval_seconds=int(interval),
                )
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            return Failure(ProviderUnavailable(reason=str(exc)))

    async def poll_device_authorization_code(
        self,
        *,
        device_auth_id: str,
        user_code: str,
    ) -> Result[
        DeviceAuthorizationCode,
        ProviderPending | ProviderRejected | ProviderUnavailable,
    ]:
        """Poll Device authentication completion once."""
        try:
            response = await self._http_client.post(
                resolve_chatgpt_oauth_device_token_url(),
                json={"device_auth_id": device_auth_id, "user_code": user_code},
            )
        except httpx.HTTPError as exc:
            return Failure(ProviderUnavailable(reason=str(exc)))

        if response.is_success:
            try:
                body = response.json()
                if not isinstance(body, dict):
                    return Failure(
                        ProviderUnavailable(reason="Provider response was invalid")
                    )
                return Success(
                    DeviceAuthorizationCode(
                        authorization_code=body["authorization_code"],
                        code_verifier=body["code_verifier"],
                    )
                )
            except (KeyError, TypeError, ValueError, ValidationError) as exc:
                return Failure(ProviderUnavailable(reason=str(exc)))
        if response.status_code in {403, 404}:
            return Failure(ProviderPending(session_id=device_auth_id))
        return Failure(_provider_error(response))

    async def exchange_authorization_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        connection_method: ChatGPTOAuthConnectionMethod,
    ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
        """Exchange Authorization code for token."""
        try:
            response = await self._http_client.post(
                self._token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": CHATGPT_OAUTH_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            return Failure(ProviderUnavailable(reason=str(exc)))

        if not response.is_success:
            return Failure(_provider_error(response))
        return _token_set_from_response(response, connection_method)

    async def refresh_tokens(
        self,
        *,
        refresh_token: str,
        connection_method: ChatGPTOAuthConnectionMethod,
    ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
        """Refresh token using Refresh token grant."""
        try:
            response = await self._http_client.post(
                self._token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CHATGPT_OAUTH_CLIENT_ID,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
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
    connection_method: ChatGPTOAuthConnectionMethod,
    *,
    default_refresh_token: str | None = None,
) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
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
                account_id=_optional_str(claims.get("https://api.openai.com/auth"))
                or _optional_str(claims.get("sub")),
                email=_optional_str(claims.get("email")),
                plan_type=_optional_str(claims.get("plan_type"))
                or _optional_str(claims.get("chatgpt_plan_type")),
                connection_method=connection_method,
            )
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        return Failure(ProviderUnavailable(reason=str(exc)))


def _provider_error(response: httpx.Response) -> ProviderRejected | ProviderUnavailable:
    """Convert Provider error to internal error."""
    reason = f"ChatGPT OAuth provider returned HTTP {response.status_code}"
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
