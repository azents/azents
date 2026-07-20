"""Platform GitHub App System Settings domain service tests."""

from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.system_setting import (
    SystemSettingEnvironment,
    SystemSettingGenerationHasher,
    SystemSettingSecretAction,
    SystemSettingSecretActionType,
    SystemSettingSection,
    SystemSettingValidationStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.github_platform_system_setting.repository import (
    PlatformGitHubAppSystemSettingRepository,
)
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.services.system_setting.data import (
    SystemSettingActivated,
    SystemSettingCandidatePending,
    SystemSettingMutation,
)
from azents.services.system_setting.service import (
    SystemSettingsService,
    get_system_setting_registry,
)

from .client import (
    PlatformGitHubAppExternalValidation,
    PlatformGitHubAppValidationClient,
)
from .service import PlatformGitHubAppSystemSettingService


def _private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def _service(
    session_manager: SessionManager[AsyncSession],
    validation_client: PlatformGitHubAppValidationClient,
) -> PlatformGitHubAppSystemSettingService:
    key = Fernet.generate_key().decode()
    generic = SystemSettingsService(
        session_manager=session_manager,
        repository=SystemSettingRepository(),
        registry=get_system_setting_registry(),
        cipher=CredentialCipher(key),
        environment=SystemSettingEnvironment(values={}),
        generation_hasher=SystemSettingGenerationHasher(key),
    )
    return PlatformGitHubAppSystemSettingService(
        system_settings=generic,
        validation_client=validation_client,
        impact_repository=PlatformGitHubAppSystemSettingRepository(),
        session_manager=session_manager,
    )


def _mutation(private_key: str) -> SystemSettingMutation:
    return SystemSettingMutation(
        section=SystemSettingSection.PLATFORM_GITHUB_APP,
        expected_version=0,
        config_patch={"app_id": "123", "client_id": "Iv1.client"},
        secret_actions={
            "private_key": SystemSettingSecretAction(
                action=SystemSettingSecretActionType.REPLACE,
                value=private_key,
            ),
            "client_secret": SystemSettingSecretAction(
                action=SystemSettingSecretActionType.REPLACE,
                value="client-secret",
            ),
        },
        actor_user_id=None,
    )


async def test_valid_candidate_without_impact_auto_activates(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A first valid App with no legacy resources activates immediately."""
    client = cast(Any, Mock())
    client.validate = AsyncMock(
        return_value=PlatformGitHubAppExternalValidation(
            status=SystemSettingValidationStatus.VALID,
            code=None,
            message=None,
            action_hint=None,
            metadata={"app_slug": "azents-test"},
        )
    )
    service = _service(
        rdb_session_manager,
        cast(PlatformGitHubAppValidationClient, client),
    )

    result = await service.patch(_mutation(_private_key()))
    detail = await service.get_detail()

    assert isinstance(result, SystemSettingActivated)
    assert detail.admin_version == 1
    assert detail.app_slug == "azents-test"
    assert all(field.value is None for field in detail.fields if field.secret)


async def test_invalid_private_key_never_calls_github(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Local validation persists a sanitized invalid candidate without egress."""
    client = cast(Any, Mock())
    client.validate = AsyncMock()
    service = _service(
        rdb_session_manager,
        cast(PlatformGitHubAppValidationClient, client),
    )

    result = await service.patch(_mutation("not-a-private-key"))

    assert isinstance(result, SystemSettingCandidatePending)
    assert result.candidate.validation_status is SystemSettingValidationStatus.INVALID
    assert result.candidate.validation_code == "platform_github_app_invalid"
    client.validate.assert_not_awaited()
