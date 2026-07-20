"""Platform GitHub App System Settings domain service tests."""

from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
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
from azents.rdb.models.github_user_installation import RDBGithubUserInstallation
from azents.rdb.session import SessionManager
from azents.repos.github_platform_system_setting.repository import (
    PlatformGitHubAppSystemSettingRepository,
)
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.services.system_setting.data import (
    SystemSettingActivated,
    SystemSettingCandidatePending,
    SystemSettingMutation,
)
from azents.services.system_setting.service import (
    SystemSettingsService,
    get_system_setting_registry,
)

from .binding import PlatformGitHubAppBindingService
from .client import (
    PlatformGitHubAppExternalValidation,
    PlatformGitHubAppValidationClient,
)
from .data import PlatformGitHubAppEffectiveStatus
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
    cipher = CredentialCipher(key)
    impact_repository = PlatformGitHubAppSystemSettingRepository()
    generic = SystemSettingsService(
        session_manager=session_manager,
        repository=SystemSettingRepository(),
        registry=get_system_setting_registry(),
        cipher=cipher,
        environment=SystemSettingEnvironment(values={}),
        generation_hasher=SystemSettingGenerationHasher(key),
    )
    return PlatformGitHubAppSystemSettingService(
        system_settings=generic,
        validation_client=validation_client,
        impact_repository=impact_repository,
        binding_service=PlatformGitHubAppBindingService(
            repository=impact_repository,
            cipher=cipher,
        ),
        session_manager=session_manager,
    )


def _valid_client() -> PlatformGitHubAppValidationClient:
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
    return cast(PlatformGitHubAppValidationClient, client)


async def _add_unbound_installation(
    session_manager: SessionManager[AsyncSession],
    *,
    email: str,
) -> str:
    async with session_manager() as session:
        user = await UserRepository().create(session, UserCreate(email=email))
        installation = RDBGithubUserInstallation(
            user_id=user.id,
            platform_app_id=None,
            installation_id=9876,
            account_login="legacy-org",
            account_type="Organization",
            account_avatar_url="",
        )
        session.add(installation)
        await session.flush()
        return installation.id


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


async def test_first_configuration_can_leave_unbound_legacy_resources(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Explicit leave-unbound activation preserves legacy ownership ambiguity."""
    installation_id = await _add_unbound_installation(
        rdb_session_manager,
        email="github-binding-leave@example.com",
    )
    service = _service(rdb_session_manager, _valid_client())

    result = await service.patch(_mutation(_private_key()))

    assert isinstance(result, SystemSettingCandidatePending)
    assert result.candidate.impact is not None
    assert set(result.candidate.impact["confirmation_actions"]) == {
        "claim_unbound_legacy",
        "leave_unbound",
    }
    await service.confirm_candidate(
        candidate_id=result.candidate.id,
        expected_version=0,
        confirmation_action="leave_unbound",
        actor_user_id=None,
    )
    detail = await service.get_detail()
    assert (
        detail.effective_status is PlatformGitHubAppEffectiveStatus.RECONNECT_REQUIRED
    )
    assert detail.binding_impact is not None
    assert detail.binding_impact.unbound_installation_count == 1
    async with rdb_session_manager() as session:
        row = await session.scalar(
            select(RDBGithubUserInstallation).where(
                RDBGithubUserInstallation.id == installation_id
            )
        )
    assert row is not None
    assert row.platform_app_id is None


async def test_first_configuration_can_claim_unbound_legacy_resources(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Explicit claim binds legacy rows in the activation transaction."""
    installation_id = await _add_unbound_installation(
        rdb_session_manager,
        email="github-binding-claim@example.com",
    )
    service = _service(rdb_session_manager, _valid_client())

    result = await service.patch(_mutation(_private_key()))

    assert isinstance(result, SystemSettingCandidatePending)
    await service.confirm_candidate(
        candidate_id=result.candidate.id,
        expected_version=0,
        confirmation_action="claim_unbound_legacy",
        actor_user_id=None,
    )
    detail = await service.get_detail()
    assert detail.effective_status is PlatformGitHubAppEffectiveStatus.READY
    assert detail.binding_impact is not None
    assert detail.binding_impact.affected_installation_count == 0
    async with rdb_session_manager() as session:
        row = await session.scalar(
            select(RDBGithubUserInstallation).where(
                RDBGithubUserInstallation.id == installation_id
            )
        )
    assert row is not None
    assert row.platform_app_id == "123"
