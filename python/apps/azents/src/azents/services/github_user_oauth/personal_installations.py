"""Exact-account Platform GitHub installation acquisition with common SDK behavior."""

import dataclasses
import secrets
from typing import Annotated
from urllib.parse import urlencode

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.github_installation import GitHubInstallationSnapshot
from azents.core.oauth2 import (
    PersonalPlatformOAuthState,
    create_personal_platform_oauth_state,
    verify_personal_platform_oauth_state,
)
from azents.core.personal_toolkit import PersonalToolkitManager
from azents.core.toolkit_ownership import ToolkitOwnerKind, UserToolkitOwner
from azents.repos.toolkit.personal_management import PersonalToolkitManagementRepository
from azents.repos.toolkit_operations.data import PlatformToolkitAuthority
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.toolkit_oauth import service as common_oauth
from azents.services.toolkit_oauth.data import (
    GitHubInstallationProjection,
    ToolkitOAuthError,
    ToolkitOAuthFailureReason,
)


@dataclasses.dataclass(frozen=True)
class PersonalGitHubInstallationsService:
    """Reuse Platform acquisition with explicit personal Auth Session ownership."""

    repository: Annotated[
        PersonalToolkitManagementRepository,
        Depends(PersonalToolkitManagementRepository),
    ]
    config: Annotated[Config, Depends(get_config)]
    platform_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()]

    async def install_url(self, subject: PersonalToolkitManager) -> str:
        """Use the existing SDK App slug lookup after current personal admission."""
        await self.repository.authorize(subject)
        return await common_oauth.platform_install_url(self.platform_runtime)

    async def oauth_url(self, subject: PersonalToolkitManager) -> str:
        """Bind new installation acquisition to owner, exact login and current App."""
        await self.repository.authorize(subject)
        platform = await self.platform_runtime.resolve()
        if platform.client_id is None:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
                "GitHub Platform App OAuth is not configured.",
            )
        state = create_personal_platform_oauth_state(
            PersonalPlatformOAuthState(
                type="personal_platform_github_oauth",
                owner=UserToolkitOwner(
                    kind=ToolkitOwnerKind.USER,
                    user_id=subject.user_id,
                    workspace_id=subject.workspace_id,
                ),
                auth_session_id=subject.session_id,
                effective_generation=platform.effective_generation,
                nonce=secrets.token_urlsafe(32),
            ),
            self.config.credential_encryption.key,
        )
        redirect_uri = (
            f"{self.config.web_url}/oauth/github/callback"
            if self.config.web_url
            else ""
        )
        return "https://github.com/login/oauth/authorize?" + urlencode(
            {
                "client_id": platform.client_id,
                "redirect_uri": redirect_uri,
                "state": state,
            }
        )

    async def sync(
        self,
        subject: PersonalToolkitManager,
        *,
        code: str,
        state: str,
    ) -> tuple[GitHubInstallationProjection, ...]:
        """Store an owner/App snapshot after current admission around Provider I/O."""
        verified = verify_personal_platform_oauth_state(
            state, self.config.credential_encryption.key
        )
        if (
            verified is None
            or verified.owner.user_id != subject.user_id
            or verified.owner.workspace_id != subject.workspace_id
            or verified.auth_session_id != subject.session_id
        ):
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.INVALID_REQUEST,
                "Personal GitHub OAuth context does not match.",
            )
        await self.repository.authorize(subject)
        platform = await self.platform_runtime.resolve()
        if verified.effective_generation != platform.effective_generation:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.PLATFORM_SETTINGS_CHANGED,
                "Platform GitHub App changed. Restart OAuth.",
            )
        receipt = await common_oauth.exchange_platform_installations(
            self.config, platform, code
        )
        current = await self.platform_runtime.resolve()
        if current != platform:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.PLATFORM_SETTINGS_CHANGED,
                "Platform GitHub App changed. Restart OAuth.",
            )
        if platform.app_id is None:
            raise RuntimeError("Admitted Platform registration is incomplete")
        await self.repository.sync_platform_installations(
            subject,
            authority=PlatformToolkitAuthority(
                app_id=platform.app_id,
                app_id_source=platform.app_id_source,
                user_id=subject.user_id,
                installation_ids=frozenset(),
            ),
            effective_generation=platform.effective_generation,
            installations=[
                GitHubInstallationSnapshot(
                    installation_id=record.installation_id,
                    app_id=None,
                    account_login=record.account_login,
                    account_type=record.account_type,
                    account_avatar_url=record.account_avatar_url,
                )
                for record in receipt.records
            ],
        )
        await common_oauth.revoke_platform_installation_receipt(platform, receipt)
        return receipt.installations
