"""ChatGPT OAuth provider client implementation."""

import asyncio
import base64
import datetime

import httpx
from azcommon.result import Failure, Result, Success
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

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


class _ProviderWire(BaseModel):
    """Validate consumed provider fields while ignoring opaque extensions."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _DeviceCodeWire(_ProviderWire):
    device_auth_id: str
    user_code: str
    interval: int = 5

    @model_validator(mode="before")
    @classmethod
    def compatible_user_code(cls, raw: object) -> object:
        if isinstance(raw, dict):
            return {**raw, "user_code": raw.get("user_code") or raw.get("usercode")}
        return raw

    @field_validator("interval", mode="before")
    @classmethod
    def coerce_interval(cls, value: object) -> int:
        if not isinstance(value, (str, int, float)):
            raise ValueError("Provider interval is invalid")
        return int(value)


class _AuthorizationWire(_ProviderWire):
    authorization_code: str
    code_verifier: str


class _TokenWire(_ProviderWire):
    access_token: str
    refresh_token: str | None = None
    id_token: str | None = None
    expires_in: int = 3600

    @field_validator("refresh_token", mode="before")
    @classmethod
    def preserve_refresh_fallback(cls, value: object) -> object:
        """Retain the provider's existing falsy-value fallback semantics."""
        return value or None

    @field_validator("expires_in", mode="before")
    @classmethod
    def coerce_expiry(cls, value: object) -> int:
        return _DeviceCodeWire.coerce_interval(value)


class _ClaimsWire(_ProviderWire):
    account: str | None = Field(default=None, alias="https://api.openai.com/auth")
    sub: str | None = None
    email: str | None = None
    plan_type: str | None = None
    chatgpt_plan_type: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def optional_metadata(cls, value: object) -> str | None:
        return value if isinstance(value, str) and value else None


class ChatGPTOAuthClient:
    """ChatGPT OAuth endpoint invocation client."""

    def __init__(self, http_client: httpx.AsyncClient, *, token_url: str) -> None:
        """Inject the HTTP client and OAuth token endpoint."""
        self.http_client = http_client
        self._token_url = token_url

    async def request_device_user_code(
        self,
    ) -> Result[DeviceUserCode, ProviderRejected | ProviderUnavailable]:
        """Request Device user-code."""
        try:
            response = await self.http_client.post(
                resolve_chatgpt_oauth_device_user_code_url(),
                json={"client_id": CHATGPT_OAUTH_CLIENT_ID},
            )
        except asyncio.CancelledError:
            raise
        except httpx.HTTPError:
            return Failure(ProviderUnavailable(reason="Provider request failed"))

        if not response.is_success:
            return Failure(_provider_error(response))
        try:
            body = _DeviceCodeWire.model_validate(response.json())
            return Success(
                DeviceUserCode(
                    device_auth_id=body.device_auth_id,
                    user_code=body.user_code,
                    interval_seconds=body.interval,
                )
            )
        except KeyError, TypeError, ValueError, ValidationError:
            return Failure(ProviderUnavailable(reason="Provider response was invalid"))

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
            response = await self.http_client.post(
                resolve_chatgpt_oauth_device_token_url(),
                json={"device_auth_id": device_auth_id, "user_code": user_code},
            )
        except asyncio.CancelledError:
            raise
        except httpx.HTTPError:
            return Failure(ProviderUnavailable(reason="Provider request failed"))

        if response.is_success:
            try:
                body = _AuthorizationWire.model_validate(response.json())
                return Success(
                    DeviceAuthorizationCode(
                        authorization_code=body.authorization_code,
                        code_verifier=body.code_verifier,
                    )
                )
            except KeyError, TypeError, ValueError, ValidationError:
                return Failure(
                    ProviderUnavailable(reason="Provider response was invalid")
                )
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
            response = await self.http_client.post(
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
        except asyncio.CancelledError:
            raise
        except httpx.HTTPError:
            return Failure(ProviderUnavailable(reason="Provider request failed"))

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
            response = await self.http_client.post(
                self._token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CHATGPT_OAUTH_CLIENT_ID,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except asyncio.CancelledError:
            raise
        except httpx.HTTPError:
            return Failure(ProviderUnavailable(reason="Provider request failed"))

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
        body = _TokenWire.model_validate(response.json())
        expires_in = body.expires_in
        id_token = body.id_token
        claims = (
            _decode_unverified_jwt_payload(id_token)
            if id_token is not None
            else _ClaimsWire()
        )
        next_refresh_token = body.refresh_token or default_refresh_token
        if not isinstance(next_refresh_token, str):
            return Failure(ProviderUnavailable(reason="Provider response was invalid"))
        return Success(
            TokenSet(
                access_token=body.access_token,
                refresh_token=next_refresh_token,
                id_token=id_token,
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(seconds=expires_in),
                account_id=claims.account or claims.sub,
                email=claims.email,
                plan_type=claims.plan_type or claims.chatgpt_plan_type,
                connection_method=connection_method,
            )
        )
    except KeyError, TypeError, ValueError, ValidationError:
        return Failure(ProviderUnavailable(reason="Provider response was invalid"))


def _provider_error(response: httpx.Response) -> ProviderRejected | ProviderUnavailable:
    """Convert Provider error to internal error."""
    reason = f"ChatGPT OAuth provider returned HTTP {response.status_code}"
    if response.status_code == 429 or 500 <= response.status_code:
        return ProviderUnavailable(reason=reason)
    return ProviderRejected(reason=reason)


def _decode_unverified_jwt_payload(token: str) -> _ClaimsWire:
    """Extract only ID token payload metadata without signature verification."""
    parts = token.split(".")
    if len(parts) < 2:
        return _ClaimsWire()
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode((payload + padding).encode())
        return _ClaimsWire.model_validate_json(decoded)
    except ValueError:
        return _ClaimsWire()
