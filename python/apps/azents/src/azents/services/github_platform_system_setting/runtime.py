"""Operation-boundary Platform GitHub App settings resolution."""

import dataclasses
import enum
from typing import Annotated

from fastapi import Depends

from azents.core.github_credentials import GitHubSecretsAppPlatform
from azents.core.github_system_setting import (
    PlatformGitHubAppConfig,
    PlatformGitHubAppSecrets,
)
from azents.core.system_setting import SystemSettingSection
from azents.services.system_setting.service import SystemSettingsService


@dataclasses.dataclass(frozen=True)
class ResolvedPlatformGitHubApp:
    """Typed effective Platform GitHub App snapshot for one operation."""

    app_id: str | None
    client_id: str | None
    private_key: str | None
    client_secret: str | None
    effective_generation: str


class PlatformGitHubAppAuthorizationReason(enum.StrEnum):
    """Stable Public reason for a Platform Toolkit reconnect requirement."""

    APP_IDENTITY_CHANGED = "app_identity_changed"
    LEGACY_BINDING_UNBOUND = "legacy_binding_unbound"


@dataclasses.dataclass(frozen=True)
class PlatformGitHubAppAuthorizationState:
    """Redacted Public authorization state for one Platform Toolkit."""

    type: str
    status: str
    reason: PlatformGitHubAppAuthorizationReason


@dataclasses.dataclass(frozen=True)
class PlatformGitHubAppRuntimeService:
    """Resolve current Platform GitHub settings without process-local caching."""

    system_settings: Annotated[SystemSettingsService, Depends()]

    async def resolve(self) -> ResolvedPlatformGitHubApp:
        """Resolve one coherent effective snapshot for the current operation."""
        resolved = await self.system_settings.resolve(
            SystemSettingSection.PLATFORM_GITHUB_APP
        )
        if not isinstance(resolved.config, PlatformGitHubAppConfig):
            raise TypeError("Unexpected Platform GitHub App config model.")
        if not isinstance(resolved.secrets, PlatformGitHubAppSecrets):
            raise TypeError("Unexpected Platform GitHub App secret model.")
        return ResolvedPlatformGitHubApp(
            app_id=resolved.config.app_id,
            client_id=resolved.config.client_id,
            private_key=resolved.secrets.private_key,
            client_secret=resolved.secrets.client_secret,
            effective_generation=resolved.effective_generation,
        )

    @staticmethod
    def authorization_state(
        credentials: GitHubSecretsAppPlatform,
        *,
        effective_app_id: str | None,
    ) -> PlatformGitHubAppAuthorizationState | None:
        """Project only reconnect status and a stable reason."""
        if credentials.app_id is None:
            return PlatformGitHubAppAuthorizationState(
                type="github_platform_app",
                status="reconnect_required",
                reason=(PlatformGitHubAppAuthorizationReason.LEGACY_BINDING_UNBOUND),
            )
        if credentials.app_id != effective_app_id:
            return PlatformGitHubAppAuthorizationState(
                type="github_platform_app",
                status="reconnect_required",
                reason=PlatformGitHubAppAuthorizationReason.APP_IDENTITY_CHANGED,
            )
        return None
