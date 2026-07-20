"""Platform GitHub App identity binding tests."""

import json
from collections.abc import Awaitable, Callable
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from azcommon.datetime import tznow
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.github_credentials import GitHubSecretsAppPlatform
from azents.core.system_setting import (
    SystemDataMigrationOutcome,
    SystemSettingEnvironment,
)
from azents.repos.github_platform_system_setting.data import (
    PlatformGitHubAppToolkitCredential,
)
from azents.repos.github_platform_system_setting.repository import (
    PlatformGitHubAppSystemSettingRepository,
)
from azents.repos.system_setting.data import StoredSystemDataMigration
from azents.services.system_setting.data import SystemDataMigrationResult
from azents.services.system_setting.service import SystemDataMigrationRunner

from .binding import (
    PlatformGitHubAppBindingCounts,
    PlatformGitHubAppBindingMigration,
    PlatformGitHubAppBindingService,
)


def _legacy_platform_credentials() -> str:
    return json.dumps(
        {
            "type": "github_app_platform",
            "installations": [
                {
                    "installation_id": "1234",
                    "account_login": "azents-test",
                    "account_type": "Organization",
                    "account_avatar_url": None,
                }
            ],
        }
    )


async def test_bind_unbound_adds_app_id_and_reencrypts_credentials() -> None:
    """Legacy Platform Toolkit credentials receive only the durable App ID."""
    cipher = CredentialCipher(Fernet.generate_key().decode())
    repository = cast(Any, Mock())
    repository.bind_unbound_installations = AsyncMock(return_value=2)
    repository.list_platform_toolkit_credentials = AsyncMock(
        return_value=[
            PlatformGitHubAppToolkitCredential(
                toolkit_id="toolkit-1",
                encrypted_credentials=cipher.encrypt(_legacy_platform_credentials()),
            )
        ]
    )
    repository.update_platform_toolkit_credentials = AsyncMock()
    service = PlatformGitHubAppBindingService(
        repository=cast(PlatformGitHubAppSystemSettingRepository, repository),
        cipher=cipher,
    )

    counts = await service.bind_unbound(
        cast(AsyncSession, object()),
        app_id="98765",
    )

    assert counts == PlatformGitHubAppBindingCounts(
        installation_count=2,
        toolkit_count=1,
    )
    call = repository.update_platform_toolkit_credentials.await_args
    assert call is not None
    encrypted = call.kwargs["encrypted_credentials"]
    decoded = GitHubSecretsAppPlatform.model_validate_json(cipher.decrypt(encrypted))
    assert decoded.app_id == "98765"
    assert decoded.installations[0].installation_id == "1234"


async def test_binding_migration_skips_permanently_when_env_is_absent() -> None:
    """An absent upgrade-time App ID records a skipped marker."""
    migration, binding = _migration(SystemSettingEnvironment(values={}))

    result = await migration.run()

    assert result.outcome is SystemDataMigrationOutcome.SKIPPED
    assert result.metadata == {"reason": "environment_app_id_absent"}
    binding.bind_unbound.assert_not_awaited()


@pytest.mark.parametrize("value", ["", "not-numeric", "１２３"])
async def test_binding_migration_rejects_invalid_present_app_id(value: str) -> None:
    """Present invalid values fail before any rows or marker are written."""
    migration, binding = _migration(
        SystemSettingEnvironment(values={"AZ_GITHUB_PLATFORM_APP_ID": value})
    )

    with pytest.raises(ValueError):
        await migration.run()

    binding.bind_unbound.assert_not_awaited()


async def test_binding_migration_records_only_non_sensitive_counts() -> None:
    """Applied marker metadata excludes the App identity and credentials."""
    migration, binding = _migration(
        SystemSettingEnvironment(values={"AZ_GITHUB_PLATFORM_APP_ID": "123"})
    )
    binding.bind_unbound.return_value = PlatformGitHubAppBindingCounts(
        installation_count=4,
        toolkit_count=3,
    )

    result = await migration.run()

    assert result.outcome is SystemDataMigrationOutcome.APPLIED
    assert result.metadata == {"installation_count": 4, "toolkit_count": 3}
    assert "123" not in repr(result.metadata)


def _migration(
    environment: SystemSettingEnvironment,
) -> tuple[PlatformGitHubAppBindingMigration, AsyncMock]:
    binding = AsyncMock(spec=PlatformGitHubAppBindingService)
    runner = cast(Any, Mock())

    async def run(
        *,
        name: str,
        operation: Callable[[AsyncSession], Awaitable[SystemDataMigrationResult]],
    ) -> StoredSystemDataMigration:
        migration_result = await operation(cast(AsyncSession, object()))
        return StoredSystemDataMigration(
            name=name,
            outcome=migration_result.outcome,
            metadata=migration_result.metadata,
            completed_at=tznow(),
        )

    runner.run = AsyncMock(side_effect=run)
    migration = PlatformGitHubAppBindingMigration(
        runner=cast(SystemDataMigrationRunner, runner),
        binding_service=cast(PlatformGitHubAppBindingService, binding),
        environment=environment,
    )
    return migration, binding
