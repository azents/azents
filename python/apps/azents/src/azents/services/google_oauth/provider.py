"""Supported SDK-owned Google OAuth exchange and signed identity verification."""

import asyncio
import dataclasses
import datetime
import functools
import json
from collections.abc import AsyncIterator
from typing import Annotated

import google.auth.exceptions
import google.auth.transport.requests
import httpx
import httpx2
import requests
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oauth2.client import OAuth2Client
from fastapi import Depends
from google.oauth2 import id_token
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.google_oauth import (
    GoogleIdentity,
    GoogleOAuthError,
    GoogleSetup,
    GoogleTokens,
)
from azents.core.google_system_setting import GoogleApplicationRegistration
from azents.core.google_workspace_policy import GOOGLE_PICKER_SCOPE
from azents.core.oauth2 import _OAuthHttpTransport

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleTokenResponse(BaseModel):
    """Preserve provider evidence before SDK refresh/default scope normalization."""

    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)
    access_token: str = Field(min_length=1, repr=False)
    token_type: str = "Bearer"
    expires_in: int = Field(gt=0)
    refresh_token: str | None = Field(default=None, repr=False, min_length=1)
    scope: str | None = None
    id_token: str | None = Field(default=None, repr=False, min_length=1)
    _received_at: datetime.datetime = PrivateAttr(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )

    def tokens(self) -> GoogleTokens:
        """Scope omission is unknown; an explicit empty string is verified empty."""
        if "scope" in self.model_fields_set and self.scope is None:
            raise GoogleOAuthError(
                "invalid_response", "Google scope evidence is invalid."
            )
        if self.token_type.casefold() != "bearer":
            raise GoogleOAuthError(
                "invalid_response", "Google token type is unsupported."
            )
        return GoogleTokens(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            expires_at=self._received_at + datetime.timedelta(seconds=self.expires_in),
            granted_scopes=(
                None if self.scope is None else tuple(sorted(set(self.scope.split())))
            ),
        )


class _GoogleProviderErrorPayload(BaseModel):
    """Use only a safe known error identifier, not provider description content."""

    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)
    error: str


class _GoogleIdentityClaims(BaseModel):
    """Decode claims only after supported signed-token verification."""

    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)
    iss: str
    sub: str = Field(min_length=1)
    nonce: str
    email: str | None = None
    email_verified: bool | None = None


def _raise_provider_rejection(payload: object) -> None:
    if isinstance(payload, dict) and "error" in payload:
        error = _GoogleProviderErrorPayload.model_validate(payload)
        reason = (
            "invalid_grant"
            if error.error == "invalid_grant"
            else "invalid_client"
            if error.error in {"invalid_client", "unauthorized_client"}
            else "provider_rejected"
        )
        raise GoogleOAuthError(reason, "Google authorization was rejected.")


@dataclasses.dataclass
class _GoogleTokenDecoder:
    """Compliance hook saves exact typed evidence, not normalized SDK token state."""

    response: GoogleTokenResponse | None

    def decode(self, response: httpx2.Response) -> httpx2.Response:
        payload: object = response.json()
        _raise_provider_rejection(payload)
        self.response = GoogleTokenResponse.model_validate(payload)
        self.response.tokens()
        normalized: dict[str, str | int] = {
            "access_token": self.response.access_token,
            "token_type": self.response.token_type,
            "expires_in": self.response.expires_in,
        }
        if self.response.refresh_token is not None:
            normalized["refresh_token"] = self.response.refresh_token
        return httpx2.Response(
            response.status_code,
            headers=[
                (key, value)
                for key, value in response.headers.multi_items()
                if key.lower() != "content-length"
            ],
            json=normalized,
            request=response.request,
        )

    def result(self) -> GoogleTokenResponse:
        if self.response is None:
            raise AssertionError("Google OAuth SDK did not decode a token response.")
        return self.response


async def get_google_http_client(
    config: Annotated[Config, Depends(get_config)],
) -> AsyncIterator[httpx.AsyncClient]:
    """Own bounded proxy-compatible Google OAuth transport at the DI boundary."""
    async with httpx.AsyncClient(
        proxy=config.mcp_proxy_url,
        timeout=10.0,
        follow_redirects=False,
    ) as client:
        yield client


@dataclasses.dataclass(frozen=True)
class GoogleOAuthProvider:
    """Provider I/O is called only between completed repository operations."""

    http_client: Annotated[httpx.AsyncClient, Depends(get_google_http_client)]
    config: Annotated[Config, Depends(get_config)]

    def authorization_url(
        self, setup: GoogleSetup, state: str, code_challenge: str
    ) -> str:
        """Include distinct OIDC nonce/offline grant and SDK-owned PKCE request."""
        sdk = OAuth2Client(
            session=None,
            client_id=setup.client_id,
            redirect_uri=setup.redirect_uri,
            scope=" ".join(setup.oauth_request_scopes),
        )
        url, _state = sdk.create_authorization_url(
            GOOGLE_AUTHORIZATION_URL,
            state=state,
            nonce=setup.oidc_nonce,
            code_challenge=code_challenge,
            code_challenge_method="S256",
            access_type="offline",
            prompt="consent",
        )
        return url

    async def exchange(
        self, registration: GoogleApplicationRegistration, setup: GoogleSetup, code: str
    ) -> GoogleTokenResponse:
        """Exchange once through Authlib without replacing returned scope evidence."""
        decoder = _GoogleTokenDecoder(None)
        try:
            async with AsyncOAuth2Client(
                client_id=registration.client_id,
                client_secret=registration.client_secret,
                token_endpoint_auth_method="client_secret_post",
                transport=_OAuthHttpTransport(self.http_client),
            ) as sdk:
                sdk.register_compliance_hook("access_token_response", decoder.decode)
                await sdk.fetch_token(
                    GOOGLE_TOKEN_URL,
                    grant_type="authorization_code",
                    code=code,
                    redirect_uri=setup.redirect_uri,
                    code_verifier=setup.code_verifier,
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPStatusError as error:
            self._http_rejection(error)
        except httpx.RequestError:
            raise GoogleOAuthError(
                "provider_unavailable", "Google authorization could not be verified."
            ) from None
        except ValidationError, json.JSONDecodeError:
            raise GoogleOAuthError(
                "invalid_response", "Google authorization response is invalid."
            ) from None
        return decoder.result()

    async def refresh(
        self, registration: GoogleApplicationRegistration, refresh_token: str
    ) -> GoogleTokens:
        """Renew through SDK; callers preserve only same-current-grant omissions."""
        decoder = _GoogleTokenDecoder(None)
        try:
            async with AsyncOAuth2Client(
                client_id=registration.client_id,
                client_secret=registration.client_secret,
                token_endpoint_auth_method="client_secret_post",
                transport=_OAuthHttpTransport(self.http_client),
            ) as sdk:
                sdk.register_compliance_hook("refresh_token_response", decoder.decode)
                await sdk.refresh_token(
                    GOOGLE_TOKEN_URL,
                    refresh_token=refresh_token,
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPStatusError as error:
            self._http_rejection(error)
        except httpx.RequestError:
            raise GoogleOAuthError(
                "provider_unavailable", "Google renewal could not be verified."
            ) from None
        except ValidationError, json.JSONDecodeError:
            raise GoogleOAuthError(
                "invalid_response", "Google renewal response is invalid."
            ) from None
        return decoder.result().tokens()

    async def refresh_picker(
        self, registration: GoogleApplicationRegistration, refresh_token: str
    ) -> GoogleTokenResponse:
        """Request precisely app-file scope; retain actual receipt evidence."""
        decoder = _GoogleTokenDecoder(None)
        try:
            async with AsyncOAuth2Client(
                client_id=registration.client_id,
                client_secret=registration.client_secret,
                token_endpoint_auth_method="client_secret_post",
                transport=_OAuthHttpTransport(self.http_client),
            ) as sdk:
                sdk.register_compliance_hook("refresh_token_response", decoder.decode)
                await sdk.refresh_token(
                    GOOGLE_TOKEN_URL,
                    refresh_token=refresh_token,
                    scope=GOOGLE_PICKER_SCOPE,
                    headers={"Accept": "application/json"},
                )
        except asyncio.CancelledError:
            raise
        except httpx.HTTPStatusError as error:
            self._http_rejection(error)
        except httpx.RequestError:
            raise GoogleOAuthError(
                "provider_unavailable", "Google Picker credential outcome is uncertain."
            ) from None
        except ValidationError, json.JSONDecodeError, OverflowError:
            raise GoogleOAuthError(
                "invalid_response", "Google Picker credential response is invalid."
            ) from None
        return decoder.result()

    async def identity(
        self, receipt: GoogleTokenResponse, client_id: str, oidc_nonce: str
    ) -> GoogleIdentity:
        """Verify signed Google claims with SDK before inspecting subject or nonce."""
        if receipt.id_token is None:
            raise GoogleOAuthError(
                "invalid_identity",
                "Google did not provide verifiable account identity.",
            )

        def verify() -> GoogleIdentity:
            with requests.Session() as session:
                if self.config.mcp_proxy_url is not None:
                    session.proxies.update(
                        {
                            "http": self.config.mcp_proxy_url,
                            "https": self.config.mcp_proxy_url,
                        }
                    )
                request = google.auth.transport.requests.Request(session=session)
                claims = _GoogleIdentityClaims.model_validate(
                    id_token.verify_oauth2_token(
                        receipt.id_token,
                        functools.partial(request, timeout=5.0),
                        audience=client_id,
                    )
                )
                if claims.nonce != oidc_nonce:
                    raise GoogleOAuthError(
                        "invalid_identity", "Google identity nonce does not match."
                    )
                return GoogleIdentity(
                    issuer=claims.iss,
                    subject=claims.sub,
                    email=claims.email if claims.email_verified is True else None,
                )

        try:
            async with asyncio.timeout(10):
                return await asyncio.to_thread(verify)
        except google.auth.exceptions.TransportError, requests.RequestException:
            raise GoogleOAuthError(
                "provider_unavailable", "Google identity verification is unavailable."
            ) from None
        except google.auth.exceptions.GoogleAuthError:
            raise GoogleOAuthError(
                "invalid_identity", "Google account identity could not be verified."
            ) from None
        except TimeoutError:
            raise GoogleOAuthError(
                "provider_unavailable", "Google account verification timed out."
            ) from None
        except GoogleOAuthError:
            raise
        except ValueError:
            raise GoogleOAuthError(
                "invalid_identity", "Google signed account identity is invalid."
            ) from None

    @staticmethod
    def _http_rejection(error: httpx.HTTPStatusError) -> None:
        try:
            payload: object = error.response.json()
            _raise_provider_rejection(payload)
        except ValidationError, json.JSONDecodeError:
            pass
        reason = (
            "provider_unavailable"
            if error.response.status_code >= 500
            else "provider_rejected"
        )
        raise GoogleOAuthError(reason, "Google credential operation failed.") from None
