"""Admin-managed provider OAuth System Settings service."""

from typing import Annotated
from urllib.parse import urlsplit

import httpx
from fastapi import Depends
from pydantic import ValidationError

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.external_account_oauth import (
    DISCORD_IDENTITY_AUTHORIZE_URL,
    DISCORD_IDENTITY_TOKEN_URL,
    DISCORD_IDENTITY_USERINFO_URL,
    SLACK_IDENTITY_AUTHORIZE_URL,
    SLACK_IDENTITY_TOKEN_URL,
    SLACK_IDENTITY_USERINFO_URL,
)
from azents.core.external_account_oauth_system_setting import (
    DiscordIdentityOAuthConfig,
    DiscordIdentityOAuthSecrets,
    ExternalAccountOAuthConfig,
    ExternalAccountOAuthSecrets,
)
from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingHealthStatus,
    SystemSettingSecretAction,
    SystemSettingSection,
)
from azents.repos.system_setting.data import StoredSystemSetting
from azents.services.system_setting.data import (
    SystemSettingHealthResult,
    SystemSettingMutation,
    SystemSettingMutationResult,
    SystemSettingState,
)
from azents.services.system_setting.service import SystemSettingsService

from .data import (
    ExternalAccountOAuthDetail,
    ExternalAccountOAuthEffectiveStatus,
    ExternalAccountOAuthFieldState,
    ExternalAccountOAuthHealthState,
)


class ExternalAccountOAuthSystemSettingService:
    """Resolve and mutate one provider OAuth System Settings Section."""

    def __init__(
        self,
        system_settings: Annotated[SystemSettingsService, Depends()],
        config: Annotated[Config, Depends(get_config)],
    ) -> None:
        self.system_settings = system_settings
        self.config = config

    async def get_detail(self, provider: str) -> ExternalAccountOAuthDetail:
        """Return a redacted provider detail projection."""
        section = _section_for_provider(provider)
        state = await self.system_settings.get_state(section)
        return self._project(provider=provider, state=state)

    async def patch(
        self,
        *,
        provider: str,
        expected_version: int,
        config_patch: dict[str, object],
        client_secret_action: SystemSettingSecretAction | None,
        actor_user_id: str,
    ) -> SystemSettingMutationResult:
        """Apply one direct optimistic provider OAuth patch."""
        section = _section_for_provider(provider)
        secret_actions: dict[str, SystemSettingSecretAction] = {}
        if client_secret_action is not None:
            secret_actions["client_secret"] = client_secret_action
        return await self.system_settings.mutate(
            SystemSettingMutation(
                section=section,
                expected_version=expected_version,
                config_patch=config_patch,
                secret_actions=secret_actions,
                actor_user_id=actor_user_id,
            )
        )

    async def check_health(
        self,
        *,
        provider: str,
        actor_user_id: str,
    ) -> ExternalAccountOAuthDetail:
        """Record a bounded local health result for one provider Section."""
        section = _section_for_provider(provider)
        resolved = await self.system_settings.resolve(section)
        try:
            self._require_complete(provider, resolved)
            callback_url = _callback_url(self.config.web_url, provider)
            if callback_url is None:
                raise _ProviderOAuthUnavailable("callback_url_unavailable")
            await _check_provider_endpoint(provider)
        except ValueError, ValidationError:
            result = SystemSettingHealthResult(
                status=SystemSettingHealthStatus.INVALID,
                code="provider_oauth_incomplete",
                message="Provider OAuth configuration is incomplete or invalid.",
                action_hint="Configure the provider OAuth client ID and secret.",
                metadata=None,
            )
        except _ProviderOAuthUnavailable as error:
            result = SystemSettingHealthResult(
                status=SystemSettingHealthStatus.UNAVAILABLE,
                code=str(error),
                message="Provider OAuth is unavailable from the configured server.",
                action_hint="Verify the public callback URL and provider endpoints.",
                metadata=None,
            )
        else:
            result = SystemSettingHealthResult(
                status=SystemSettingHealthStatus.HEALTHY,
                code="provider_oauth_reachable",
                message="Provider OAuth configuration and endpoint are reachable.",
                action_hint=(
                    "Complete a user connection to verify provider credentials."
                ),
                metadata=None,
            )
        await self.system_settings.record_health(
            section=section,
            expected_generation=resolved.effective_generation,
            result=result,
            actor_user_id=actor_user_id,
        )
        return await self.get_detail(provider)

    def _project(
        self,
        *,
        provider: str,
        state: SystemSettingState,
    ) -> ExternalAccountOAuthDetail:
        resolved = state.resolved
        current = state.current
        secret_configured = _secret_configured(current)
        if provider == "slack":
            config = _require_slack_config(resolved)
            fields = (
                ("client_id", False, config.client_id),
                ("client_secret", True, None),
            )
        else:
            config = _require_discord_config(resolved)
            fields = (
                ("application_id", False, config.application_id),
                ("client_secret", True, None),
            )
        configured_count = sum(
            int(secret_configured if secret else value is not None)
            for _, secret, value in fields
        )
        callback_url = _callback_url(self.config.web_url, provider)
        if configured_count == 0:
            status = ExternalAccountOAuthEffectiveStatus.NOT_CONFIGURED
        elif configured_count < 2:
            status = ExternalAccountOAuthEffectiveStatus.INCOMPLETE
        elif callback_url is None:
            status = ExternalAccountOAuthEffectiveStatus.UNAVAILABLE
        else:
            status = ExternalAccountOAuthEffectiveStatus.READY
        projected_fields = tuple(
            ExternalAccountOAuthFieldState(
                name=name,
                secret=secret,
                value=value,
                configured=secret_configured if secret else value is not None,
                source=resolved.field_sources[name],
                fallback_configured=False,
                fallback_last_changed_at=(
                    current.updated_at if current is not None else None
                ),
            )
            for name, secret, value in fields
        )
        health = (
            ExternalAccountOAuthHealthState(
                status=state.health.status,
                code=state.health.code,
                message=state.health.message,
                action_hint=state.health.action_hint,
                checked_at=state.health.checked_at,
            )
            if state.health is not None
            else None
        )
        if health is not None and health.status is SystemSettingHealthStatus.INVALID:
            status = ExternalAccountOAuthEffectiveStatus.INVALID
        if (
            health is not None
            and health.status is SystemSettingHealthStatus.UNAVAILABLE
        ):
            status = ExternalAccountOAuthEffectiveStatus.UNAVAILABLE
        return ExternalAccountOAuthDetail(
            section=resolved.section.value,
            provider=provider,
            schema_version=resolved.schema_version,
            admin_version=resolved.admin_version,
            effective_status=status,
            callback_url=callback_url,
            fields=projected_fields,
            health=health,
        )

    @staticmethod
    def _require_complete(
        provider: str,
        resolved: ResolvedSystemSetting,
    ) -> None:
        if provider == "slack":
            config = _require_slack_config(resolved)
            secrets = resolved.secrets
            if not isinstance(secrets, ExternalAccountOAuthSecrets):
                raise TypeError("Unexpected Slack OAuth secret model.")
            if config.client_id is None or secrets.client_secret is None:
                raise ValueError("Slack OAuth configuration is incomplete.")
            return
        config = _require_discord_config(resolved)
        secrets = resolved.secrets
        if not isinstance(secrets, DiscordIdentityOAuthSecrets):
            raise TypeError("Unexpected Discord OAuth secret model.")
        if config.application_id is None or secrets.client_secret is None:
            raise ValueError("Discord OAuth configuration is incomplete.")


class _ProviderOAuthUnavailable(Exception):
    """Provider OAuth endpoint or callback is unavailable."""


async def _check_provider_endpoint(provider: str) -> None:
    """Check authorization, token, and identity endpoints without credentials."""
    endpoints = (
        (
            SLACK_IDENTITY_AUTHORIZE_URL,
            SLACK_IDENTITY_TOKEN_URL,
            SLACK_IDENTITY_USERINFO_URL,
        )
        if provider == "slack"
        else (
            DISCORD_IDENTITY_AUTHORIZE_URL,
            DISCORD_IDENTITY_TOKEN_URL,
            DISCORD_IDENTITY_USERINFO_URL,
        )
    )
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            for endpoint in endpoints:
                response = await client.get(endpoint)
                if response.status_code >= 500:
                    raise _ProviderOAuthUnavailable("provider_endpoint_unreachable")
    except _ProviderOAuthUnavailable:
        raise
    except Exception:
        raise _ProviderOAuthUnavailable("provider_endpoint_unreachable") from None


def _section_for_provider(provider: str) -> SystemSettingSection:
    if provider == "slack":
        return SystemSettingSection.SLACK_IDENTITY_OAUTH
    if provider == "discord":
        return SystemSettingSection.DISCORD_IDENTITY_OAUTH
    raise ValueError("Unsupported external account OAuth provider.")


def _callback_url(web_url: str, provider: str) -> str | None:
    parsed = urlsplit(web_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return None
    return f"{web_url.rstrip('/')}/oauth/external-account/{provider}/callback"


def _secret_configured(current: StoredSystemSetting | None) -> bool:
    if current is None:
        return False
    metadata = current.secret_metadata.get("client_secret")
    return isinstance(metadata, dict) and metadata.get("configured") is True


def _require_slack_config(
    resolved: ResolvedSystemSetting,
) -> ExternalAccountOAuthConfig:
    if not isinstance(resolved.config, ExternalAccountOAuthConfig):
        raise TypeError("Unexpected Slack OAuth config model.")
    return resolved.config


def _require_discord_config(
    resolved: ResolvedSystemSetting,
) -> DiscordIdentityOAuthConfig:
    if not isinstance(resolved.config, DiscordIdentityOAuthConfig):
        raise TypeError("Unexpected Discord OAuth config model.")
    return resolved.config
