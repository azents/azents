"""Platform GitHub App identity binding and legacy migration."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.github_credentials import GitHubSecrets, GitHubSecretsAppPlatform
from azents.core.github_system_setting import validate_platform_github_app_id
from azents.core.system_setting import (
    SystemDataMigrationOutcome,
    SystemSettingEnvironment,
)
from azents.repos.github_platform_system_setting.repository import (
    PlatformGitHubAppSystemSettingRepository,
)
from azents.repos.system_setting.data import StoredSystemDataMigration
from azents.services.system_setting.data import SystemDataMigrationResult
from azents.services.system_setting.service import (
    SystemDataMigrationRunner,
    get_system_setting_environment,
)

_BIND_LEGACY_PLATFORM_GITHUB_APP = "bind_legacy_platform_github_app_v1"
_PLATFORM_APP_ID_ENV = "AZ_GITHUB_PLATFORM_APP_ID"
_github_secrets_adapter: TypeAdapter[GitHubSecrets] = TypeAdapter(GitHubSecrets)


@dataclasses.dataclass(frozen=True)
class PlatformGitHubAppBindingCounts:
    """Non-sensitive row counts changed by one identity binding operation."""

    installation_count: int
    toolkit_count: int


@dataclasses.dataclass(frozen=True)
class PlatformGitHubAppToolkitBindingImpact:
    """Toolkit binding IDs needed for redacted impact aggregation."""

    affected_toolkit_ids: frozenset[str]
    unbound_toolkit_count: int


@dataclasses.dataclass(frozen=True)
class PlatformGitHubAppBindingService:
    """Inspect and atomically bind persisted GitHub resources."""

    repository: Annotated[
        PlatformGitHubAppSystemSettingRepository,
        Depends(PlatformGitHubAppSystemSettingRepository),
    ]
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)]

    async def bind_unbound(
        self,
        session: AsyncSession,
        *,
        app_id: str,
    ) -> PlatformGitHubAppBindingCounts:
        """Bind every unbound installation and Platform Toolkit credential."""
        validate_platform_github_app_id(app_id)
        installation_count = await self.repository.bind_unbound_installations(
            session,
            app_id=app_id,
        )
        toolkit_count = 0
        for item in await self.repository.list_platform_toolkit_credentials(session):
            credentials = self._decode(item.encrypted_credentials)
            if credentials.app_id is not None:
                continue
            bound = credentials.model_copy(update={"app_id": app_id})
            await self.repository.update_platform_toolkit_credentials(
                session,
                toolkit_id=item.toolkit_id,
                encrypted_credentials=self.cipher.encrypt(bound.model_dump_json()),
            )
            toolkit_count += 1
        return PlatformGitHubAppBindingCounts(
            installation_count=installation_count,
            toolkit_count=toolkit_count,
        )

    async def inspect_toolkit_impact(
        self,
        session: AsyncSession,
        *,
        current_app_id: str | None,
    ) -> PlatformGitHubAppToolkitBindingImpact:
        """Classify current-bound and unbound Platform Toolkit credentials."""
        affected: set[str] = set()
        unbound_count = 0
        for item in await self.repository.list_platform_toolkit_credentials(session):
            credentials = self._decode(item.encrypted_credentials)
            if credentials.app_id is None:
                unbound_count += 1
                if current_app_id is None:
                    affected.add(item.toolkit_id)
            elif credentials.app_id == current_app_id:
                affected.add(item.toolkit_id)
        return PlatformGitHubAppToolkitBindingImpact(
            affected_toolkit_ids=frozenset(affected),
            unbound_toolkit_count=unbound_count,
        )

    async def inspect_current_toolkit_impact(
        self,
        session: AsyncSession,
        *,
        effective_app_id: str,
    ) -> PlatformGitHubAppToolkitBindingImpact:
        """Return Platform Toolkits with null or mismatched App identity."""
        affected: set[str] = set()
        unbound_count = 0
        for item in await self.repository.list_platform_toolkit_credentials(session):
            credentials = self._decode(item.encrypted_credentials)
            if credentials.app_id is None:
                unbound_count += 1
                affected.add(item.toolkit_id)
            elif credentials.app_id != effective_app_id:
                affected.add(item.toolkit_id)
        return PlatformGitHubAppToolkitBindingImpact(
            affected_toolkit_ids=frozenset(affected),
            unbound_toolkit_count=unbound_count,
        )

    def _decode(self, encrypted_credentials: str) -> GitHubSecretsAppPlatform:
        plaintext = self.cipher.decrypt(encrypted_credentials)
        credentials = _github_secrets_adapter.validate_json(plaintext)
        if not isinstance(credentials, GitHubSecretsAppPlatform):
            raise ValueError(
                "Platform GitHub Toolkit config has incompatible credentials."
            )
        return credentials


@dataclasses.dataclass(frozen=True)
class PlatformGitHubAppBindingMigration:
    """Run the one-time upgrade binding from the environment App ID."""

    runner: Annotated[SystemDataMigrationRunner, Depends()]
    binding_service: Annotated[PlatformGitHubAppBindingService, Depends()]
    environment: Annotated[
        SystemSettingEnvironment,
        Depends(get_system_setting_environment),
    ]

    async def run(self) -> StoredSystemDataMigration:
        """Run or return the durable legacy binding outcome."""

        async def operation(session: AsyncSession) -> SystemDataMigrationResult:
            if not self.environment.contains(_PLATFORM_APP_ID_ENV):
                return SystemDataMigrationResult(
                    outcome=SystemDataMigrationOutcome.SKIPPED,
                    metadata={"reason": "environment_app_id_absent"},
                )
            app_id = validate_platform_github_app_id(
                self.environment.get_present(_PLATFORM_APP_ID_ENV)
            )
            counts = await self.binding_service.bind_unbound(
                session,
                app_id=app_id,
            )
            return SystemDataMigrationResult(
                outcome=SystemDataMigrationOutcome.APPLIED,
                metadata={
                    "installation_count": counts.installation_count,
                    "toolkit_count": counts.toolkit_count,
                },
            )

        return await self.runner.run(
            name=_BIND_LEGACY_PLATFORM_GITHUB_APP,
            operation=operation,
        )
