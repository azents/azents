"""Sanitized external validation for Platform GitHub App settings."""

import secrets
from dataclasses import dataclass

import httpx

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
            app_response = await self.http_client.get(
                self.app_url,
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        except httpx.RequestError:
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
            oauth_response = await self.http_client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                json={
                    "client_id": effective.client_id,
                    "client_secret": effective.client_secret,
                    "code": f"azents-validation-{secrets.token_urlsafe(24)}",
                },
            )
        except httpx.RequestError:
            return self._unavailable()
        if oauth_response.status_code in {429} or oauth_response.status_code >= 500:
            return self._unavailable()
        oauth_data = self._json_object(oauth_response)
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

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, object]:
        try:
            data: object = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

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
