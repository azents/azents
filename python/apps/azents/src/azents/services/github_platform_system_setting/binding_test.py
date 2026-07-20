"""Platform GitHub App binding inspection tests."""

from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.github_credentials import (
    GitHubInstallationTarget,
    GitHubSecretsAppPlatform,
)
from azents.repos.github_platform_system_setting.data import (
    PlatformGitHubAppToolkitCredential,
)
from azents.repos.github_platform_system_setting.repository import (
    PlatformGitHubAppSystemSettingRepository,
)

from .binding import PlatformGitHubAppBindingService


def _credential(cipher: CredentialCipher, app_id: str) -> str:
    """Create an encrypted current Platform Toolkit credential."""
    return cipher.encrypt(
        GitHubSecretsAppPlatform(
            app_id=app_id,
            installations=[
                GitHubInstallationTarget(
                    installation_id="1234",
                    account_login="azents-test",
                    account_type="Organization",
                    account_avatar_url=None,
                )
            ],
        ).model_dump_json()
    )


async def test_inspect_toolkits_bound_to_decrypts_current_credentials() -> None:
    """Only Toolkits bound to the requested App are returned."""
    cipher = CredentialCipher(Fernet.generate_key().decode())
    repository = cast(Any, Mock())
    repository.list_platform_toolkit_credentials = AsyncMock(
        return_value=[
            PlatformGitHubAppToolkitCredential(
                toolkit_id="toolkit-current",
                encrypted_credentials=_credential(cipher, "123"),
            ),
            PlatformGitHubAppToolkitCredential(
                toolkit_id="toolkit-other",
                encrypted_credentials=_credential(cipher, "456"),
            ),
        ]
    )
    service = PlatformGitHubAppBindingService(
        repository=cast(PlatformGitHubAppSystemSettingRepository, repository),
        cipher=cipher,
    )

    impact = await service.inspect_toolkits_bound_to(
        cast(AsyncSession, object()),
        app_id="123",
    )

    assert impact.affected_toolkit_ids == frozenset({"toolkit-current"})


async def test_inspect_toolkits_mismatched_with_requires_reconnect() -> None:
    """Only Toolkits from a different App identity require reconnect."""
    cipher = CredentialCipher(Fernet.generate_key().decode())
    repository = cast(Any, Mock())
    repository.list_platform_toolkit_credentials = AsyncMock(
        return_value=[
            PlatformGitHubAppToolkitCredential(
                toolkit_id="toolkit-current",
                encrypted_credentials=_credential(cipher, "123"),
            ),
            PlatformGitHubAppToolkitCredential(
                toolkit_id="toolkit-other",
                encrypted_credentials=_credential(cipher, "456"),
            ),
        ]
    )
    service = PlatformGitHubAppBindingService(
        repository=cast(PlatformGitHubAppSystemSettingRepository, repository),
        cipher=cipher,
    )

    impact = await service.inspect_toolkits_mismatched_with(
        cast(AsyncSession, object()),
        effective_app_id="123",
    )

    assert impact.affected_toolkit_ids == frozenset({"toolkit-other"})
