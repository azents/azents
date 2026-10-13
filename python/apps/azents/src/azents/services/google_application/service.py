"""Google operator configuration without Toolkit-service dependency cycles."""

import dataclasses
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.google_system_setting import (
    GoogleApplicationConfigPatch,
    GoogleApplicationDetail,
    GoogleApplicationRegistration,
    GoogleApplicationSecrets,
    GoogleApplicationUnavailable,
    GooglePreparation,
    google_preparation,
    resolve_google_registration,
)
from azents.core.system_setting import SystemSettingSecretAction, SystemSettingSection
from azents.core.system_setting_data import SystemSettingMutation
from azents.services.system_setting.service import SystemSettingsService


@dataclasses.dataclass(frozen=True)
class GoogleApplicationService:
    """Resolve current configuration separately from account consent authority."""

    settings: Annotated[SystemSettingsService, Depends()]
    config: Annotated[Config, Depends(get_config)]

    def callback_url(self) -> str:
        """Build the stable registered deployment callback, not browser input."""
        base = self.config.web_url
        parsed = urlsplit(base or "")
        if not base or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise GoogleApplicationUnavailable("Google callback URL is unavailable.")
        if parsed.query or parsed.fragment:
            raise GoogleApplicationUnavailable("Google callback URL is invalid.")
        return base.rstrip("/") + "/oauth/google/callback"

    async def resolve(self) -> GoogleApplicationRegistration:
        """Return a complete detached client with exact configuration generation."""
        current = await self.settings.resolve(SystemSettingSection.GOOGLE_OAUTH)
        return resolve_google_registration(current, self.callback_url())

    async def preparation(self) -> GooglePreparation:
        """Describe local preparation without account tokens or provider claims."""
        current = await self.settings.resolve(SystemSettingSection.GOOGLE_OAUTH)
        try:
            redirect_uri = self.callback_url()
        except GoogleApplicationUnavailable:
            redirect_uri = None
        return google_preparation(current, redirect_uri)

    async def detail(self) -> GoogleApplicationDetail:
        """Redact operator credentials while preserving field-source ownership."""
        current = await self.settings.resolve(SystemSettingSection.GOOGLE_OAUTH)
        try:
            redirect_uri = self.callback_url()
        except GoogleApplicationUnavailable:
            redirect_uri = None
        preparation = google_preparation(current, redirect_uri)
        secrets = current.secrets
        if not isinstance(secrets, GoogleApplicationSecrets):
            raise TypeError("Unexpected Google application secrets.")
        return GoogleApplicationDetail(
            status=preparation.status,
            client_id=preparation.client_id,
            callback_url=preparation.callback_url,
            preview_verified=False,
            service_access_verified=False,
            section="google_oauth",
            schema_version=current.schema_version,
            admin_version=current.admin_version,
            client_id_source=current.field_sources["client_id"],
            client_secret_source=current.field_sources["client_secret"],
            client_secret_configured=secrets.client_secret is not None,
        )

    async def patch(
        self,
        *,
        expected_version: int,
        config_patch: GoogleApplicationConfigPatch,
        secret_action: SystemSettingSecretAction | None,
        actor_user_id: str,
    ) -> GoogleApplicationDetail:
        """Activate local preparation; do not pretend credentials were live-tested."""
        await self.settings.mutate(
            SystemSettingMutation(
                section=SystemSettingSection.GOOGLE_OAUTH,
                expected_version=expected_version,
                config_patch=dict(config_patch),
                secret_actions={}
                if secret_action is None
                else {"client_secret": secret_action},
                actor_user_id=actor_user_id,
            )
        )
        return await self.detail()
