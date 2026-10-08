"""Platform GitHub App identity binding inspection."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from pydantic import TypeAdapter

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.github_credentials import (
    GitHubSecretsAppPlatform,
    GitHubSecretsAppPlatformUser,
)
from azents.core.github_system_setting_data import PlatformGitHubAppToolkitBindingImpact
from azents.rdb.session_capabilities import ReadSession
from azents.repos.github_platform_system_setting.repository import (
    PlatformGitHubAppSystemSettingRepository,
)


@dataclasses.dataclass(frozen=True)
class PlatformGitHubAppBindingRepository:
    """Inspect persisted Platform GitHub App identity bindings."""

    repository: Annotated[
        PlatformGitHubAppSystemSettingRepository,
        Depends(PlatformGitHubAppSystemSettingRepository),
    ]
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)]

    async def inspect_toolkits_bound_to(
        self,
        session: ReadSession,
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
        session: ReadSession,
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
    ) -> GitHubSecretsAppPlatform | GitHubSecretsAppPlatformUser:
        """Decode either Platform authority with its required App binding."""
        adapter = TypeAdapter[GitHubSecretsAppPlatform | GitHubSecretsAppPlatformUser](
            GitHubSecretsAppPlatform | GitHubSecretsAppPlatformUser
        )
        return adapter.validate_json(self.cipher.decrypt(encrypted_credentials))
