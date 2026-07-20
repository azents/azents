"""Platform GitHub App identity binding inspection."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.github_credentials import GitHubSecretsAppPlatform
from azents.repos.github_platform_system_setting.repository import (
    PlatformGitHubAppSystemSettingRepository,
)


@dataclasses.dataclass(frozen=True)
class PlatformGitHubAppToolkitBindingImpact:
    """Toolkit IDs affected by one App identity comparison."""

    affected_toolkit_ids: frozenset[str]


@dataclasses.dataclass(frozen=True)
class PlatformGitHubAppBindingService:
    """Inspect persisted Platform GitHub App identity bindings."""

    repository: Annotated[
        PlatformGitHubAppSystemSettingRepository,
        Depends(PlatformGitHubAppSystemSettingRepository),
    ]
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)]

    async def inspect_toolkits_bound_to(
        self,
        session: AsyncSession,
        *,
        app_id: str,
    ) -> PlatformGitHubAppToolkitBindingImpact:
        """Return Toolkits bound to one current App identity."""
        affected: set[str] = set()
        for item in await self.repository.list_platform_toolkit_credentials(session):
            credentials = self._decode_current(item.encrypted_credentials)
            if credentials.app_id == app_id:
                affected.add(item.toolkit_id)
        return PlatformGitHubAppToolkitBindingImpact(
            affected_toolkit_ids=frozenset(affected),
        )

    async def inspect_toolkits_mismatched_with(
        self,
        session: AsyncSession,
        *,
        effective_app_id: str,
    ) -> PlatformGitHubAppToolkitBindingImpact:
        """Return Toolkits whose App identity differs from the effective App."""
        affected: set[str] = set()
        for item in await self.repository.list_platform_toolkit_credentials(session):
            credentials = self._decode_current(item.encrypted_credentials)
            if credentials.app_id != effective_app_id:
                affected.add(item.toolkit_id)
        return PlatformGitHubAppToolkitBindingImpact(
            affected_toolkit_ids=frozenset(affected),
        )

    def _decode_current(
        self,
        encrypted_credentials: str,
    ) -> GitHubSecretsAppPlatform:
        """Decode a Platform Toolkit credential with its required App ID."""
        return GitHubSecretsAppPlatform.model_validate_json(
            self.cipher.decrypt(encrypted_credentials)
        )
