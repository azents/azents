"""Sanitized external validation for Platform GitHub App settings."""

import asyncio
import secrets
from dataclasses import dataclass
from typing import TypeGuard

import httpx
from githubkit import BaseAuthStrategy, GitHub, OAuthWebAuthStrategy, UnauthAuthStrategy
from githubkit.exception import AuthExpiredError, RequestError, RequestFailed

from azents.core.github_auth import create_github_app_jwt
from azents.core.github_system_setting import PlatformGitHubAppEffective
from azents.core.system_setting import SystemSettingValidationStatus


@dataclass(frozen=True)
class PlatformGitHubAppExternalValidation:
    """Sanitized GitHub validation result."""

    status: SystemSettingValidationStatus
    code: str | None
    message: str | None
    action_hint: str | None
    metadata: dict[str, object] | None


class PlatformGitHubAppValidationClient:
    """Validate App JWT identity and OAuth client credentials."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        app_url: str,
        oauth_token_url: str,
    ) -> None:
        self.http_client = http_client
        self.app_url = app_url
        self.oauth_token_url = oauth_token_url

    async def validate(
        self,
        effective: PlatformGitHubAppEffective,
    ) -> PlatformGitHubAppExternalValidation:
        """Return a bounded result without retaining provider response bodies."""
        jwt_token = create_github_app_jwt(effective.app_id, effective.private_key)
        try:
            async with self._sdk(self.app_url.removesuffix("/app")) as sdk:
                result = await sdk.rest.apps.async_get_authenticated(
                    headers={
                        "Authorization": f"Bearer {jwt_token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    }
                )
                app_response = result.raw_response
        except asyncio.CancelledError:
            raise
        except RequestFailed as exc:
            app_response = exc.response.raw_response
        except RequestError, httpx.RequestError:
            return self._unavailable()
        if app_response.status_code in {429} or app_response.status_code >= 500:
            return self._unavailable()
        if app_response.status_code >= 400:
            return self._invalid(
                code="github_app_credentials_invalid",
                message="GitHub rejected the App ID or private key.",
                action_hint="Verify the App ID and replace the private key.",
            )
        app_data = self._json_object(app_response)
        returned_app_id = app_data.get("id")
        returned_client_id = app_data.get("client_id")
        slug = app_data.get("slug")
        if str(returned_app_id) != effective.app_id:
            return self._invalid(
                code="github_app_id_mismatch",
                message="GitHub returned a different App identity.",
                action_hint="Verify the configured App ID.",
            )
        if returned_client_id != effective.client_id:
            return self._invalid(
                code="github_client_id_mismatch",
                message="GitHub returned a different OAuth Client ID.",
                action_hint="Verify the configured Client ID.",
            )
        if not isinstance(slug, str) or not slug:
            return self._unavailable(code="github_app_response_invalid")

        try:
            strategy = OAuthWebAuthStrategy(
                effective.client_id,
                effective.client_secret,
                f"azents-validation-{secrets.token_urlsafe(24)}",
            )
            await strategy.async_exchange_token(
                self._sdk(
                    self.oauth_token_url.removesuffix("/login/oauth/access_token")
                )
            )
            oauth_data: dict[str, object] = {}
        except asyncio.CancelledError:
            raise
        except AuthExpiredError as exc:
            raw = exc.args[1] if len(exc.args) > 1 else None
            oauth_data = raw if _is_string_object_dict(raw) else {}
        except RequestFailed as exc:
            response = exc.response.raw_response
            if response.status_code == 429 or response.status_code >= 500:
                return self._unavailable()
            oauth_data = self._json_object(response)
        except ValueError, TypeError:
            oauth_data = {}
        except RequestError, httpx.RequestError:
            return self._unavailable()
        error = oauth_data.get("error")
        if error != "bad_verification_code":
            if error in {"temporarily_unavailable", "server_error"}:
                return self._unavailable()
            return self._invalid(
                code="github_oauth_credentials_invalid",
                message="GitHub rejected the OAuth Client ID or Client Secret.",
                action_hint="Verify the Client ID and replace the Client Secret.",
            )
        return PlatformGitHubAppExternalValidation(
            status=SystemSettingValidationStatus.VALID,
            code=None,
            message=None,
            action_hint=None,
            metadata={"app_slug": slug},
        )

    def _sdk(self, base_url: str) -> GitHub[BaseAuthStrategy]:
        """Retain transport injection while the SDK owns request construction."""
        return GitHub[BaseAuthStrategy](
            auth=UnauthAuthStrategy(),
            base_url=base_url,
            async_transport=_ValidationTransport(self.http_client),
            auto_retry=False,
            http_cache=False,
            follow_redirects=False,
            timeout=self.http_client.timeout,
        )

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, object]:
        try:
            data: object = response.json()
        except ValueError:
            return {}
        return data if _is_string_object_dict(data) else {}

    @staticmethod
    def _invalid(
        *,
        code: str,
        message: str,
        action_hint: str,
    ) -> PlatformGitHubAppExternalValidation:
        return PlatformGitHubAppExternalValidation(
            status=SystemSettingValidationStatus.INVALID,
            code=code,
            message=message,
            action_hint=action_hint,
            metadata=None,
        )

    @staticmethod
    def _unavailable(
        *,
        code: str = "github_unavailable",
    ) -> PlatformGitHubAppExternalValidation:
        return PlatformGitHubAppExternalValidation(
            status=SystemSettingValidationStatus.UNAVAILABLE,
            code=code,
            message="GitHub validation is temporarily unavailable.",
            action_hint="Retry validation after GitHub recovers.",
            metadata=None,
        )


def _is_string_object_dict(value: object) -> TypeGuard[dict[str, object]]:
    """Return whether a value is a dictionary with string keys."""
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


class _ValidationTransport(httpx.AsyncBaseTransport):
    """Delegate SDK requests without taking ownership of the injected client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request.extensions["timeout"] = self.client.timeout.as_dict()
        return await self.client.send(request, stream=True)
