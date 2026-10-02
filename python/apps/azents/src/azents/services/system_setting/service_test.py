"""Provider-neutral SystemSettingsService tests."""

import dataclasses
import datetime

import pytest
from cryptography.fernet import Fernet
from pydantic import BaseModel, ValidationError
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession

import azents.repos.system_setting.operations as service_module
from azents.core.crypto import CredentialCipher
from azents.core.external_channel_file import (
    DEFAULT_EXTERNAL_CHANNEL_OUTBOUND_MAX_ACTION_BYTES,
    DEFAULT_EXTERNAL_CHANNEL_OUTBOUND_MAX_FILE_BYTES,
)
from azents.core.external_channel_file_system_setting import (
    ExternalChannelFilesConfig,
    ExternalChannelFilesSecrets,
)
from azents.core.system_setting import (
    SystemSettingActivationMode,
    SystemSettingCandidateExpired,
    SystemSettingCandidateReplaced,
    SystemSettingDefinition,
    SystemSettingEnvironment,
    SystemSettingEnvironmentBinding,
    SystemSettingEnvironmentFieldReadOnly,
    SystemSettingFieldSource,
    SystemSettingFieldTarget,
    SystemSettingGenerationHasher,
    SystemSettingHealthStatus,
    SystemSettingRegistry,
    SystemSettingSecretAction,
    SystemSettingSecretActionType,
    SystemSettingSection,
    SystemSettingValidationStatus,
    SystemSettingVersionConflict,
)
from azents.core.system_setting_data import (
    SystemSettingActivated,
    SystemSettingCandidatePending,
    SystemSettingCandidateValidationResult,
    SystemSettingCandidateValidationSnapshot,
    SystemSettingHealthResult,
    SystemSettingMutation,
)
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.core.system_setting_registry import get_system_setting_registry
from azents.rdb.session import SessionManager
from azents.repos.github_platform_system_setting.binding import (
    PlatformGitHubAppBindingRepository,
)
from azents.repos.github_platform_system_setting.operations import (
    PlatformGitHubAppImpactRepository,
)
from azents.repos.github_platform_system_setting.repository import (
    PlatformGitHubAppSystemSettingRepository,
)
from azents.repos.system_setting.operations import SystemSettingsRepository
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.services.system_setting.service import SystemSettingsService


class _Config(BaseModel):
    endpoint: str | None = None
    label: str | None = None


class _Secrets(BaseModel):
    token: str | None = None


def _validate(_config: BaseModel, _secrets: BaseModel) -> None:
    """Accept complete test payloads."""


def _definition(
    activation_mode: SystemSettingActivationMode,
) -> SystemSettingDefinition:
    return SystemSettingDefinition(
        section=SystemSettingSection.PLATFORM_GITHUB_APP,
        schema_version=1,
        config_model=_Config,
        secret_model=_Secrets,
        activation_mode=activation_mode,
        environment_bindings=(
            SystemSettingEnvironmentBinding(
                field_name="endpoint",
                environment_variable="AZ_TEST_ENDPOINT",
                target=SystemSettingFieldTarget.CONFIG,
            ),
            SystemSettingEnvironmentBinding(
                field_name="token",
                environment_variable="AZ_TEST_TOKEN",
                target=SystemSettingFieldTarget.SECRET,
            ),
        ),
        candidate_ttl=datetime.timedelta(hours=24),
        local_validator=_validate,
    )


def _service(
    session_manager: SessionManager[AsyncSession],
    *,
    activation_mode: SystemSettingActivationMode = SystemSettingActivationMode.DIRECT,
    environment: dict[str, str] | None = None,
    key: str | None = None,
) -> SystemSettingsService:
    encryption_key = key or Fernet.generate_key().decode()
    cipher = CredentialCipher(encryption_key)
    query = PlatformGitHubAppSystemSettingRepository()
    return SystemSettingsService(
        repository=SystemSettingsRepository(
            session_manager=session_manager,
            repository=SystemSettingRepository(),
            payloads=SystemSettingPayloadResolver(
                registry=SystemSettingRegistry(
                    definitions=(_definition(activation_mode),)
                ),
                cipher=cipher,
                environment=SystemSettingEnvironment(values=environment or {}),
                generation_hasher=SystemSettingGenerationHasher(encryption_key),
            ),
            github_impact=PlatformGitHubAppImpactRepository(
                session_manager=session_manager,
                impact_repository=query,
                bindings=PlatformGitHubAppBindingRepository(
                    repository=query, cipher=cipher
                ),
            ),
        )
    )


def _registered_service(
    session_manager: SessionManager[AsyncSession],
) -> SystemSettingsService:
    encryption_key = Fernet.generate_key().decode()
    service = _service(session_manager, key=encryption_key)
    return SystemSettingsService(
        repository=dataclasses.replace(
            service.repository,
            payloads=dataclasses.replace(
                service.repository.payloads,
                registry=get_system_setting_registry(),
            ),
        )
    )


def _initial_mutation() -> SystemSettingMutation:
    return SystemSettingMutation(
        section=SystemSettingSection.PLATFORM_GITHUB_APP,
        expected_version=0,
        config_patch={"endpoint": "https://example.com", "label": "primary"},
        secret_actions={
            "token": SystemSettingSecretAction(
                action=SystemSettingSecretActionType.REPLACE,
                value="secret-value",
            )
        },
        actor_user_id=None,
    )


def test_compiled_registry_includes_external_channel_files() -> None:
    """The process registry exposes the provider-neutral file policy Section."""
    definition = get_system_setting_registry().get(
        SystemSettingSection.EXTERNAL_CHANNEL_FILES
    )

    assert definition.activation_mode is SystemSettingActivationMode.DIRECT
    assert definition.config_model is ExternalChannelFilesConfig
    assert definition.secret_model is ExternalChannelFilesSecrets


async def test_external_channel_file_limits_resolve_defaults_without_storage(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """The typed defaults are effective before an administrator writes a row."""
    service = _registered_service(rdb_session_manager)

    resolved = await service.resolve(SystemSettingSection.EXTERNAL_CHANNEL_FILES)

    assert resolved.admin_version == 0
    assert isinstance(resolved.config, ExternalChannelFilesConfig)
    assert "inbound_max_file_bytes" not in resolved.config.model_dump()
    assert (
        resolved.config.outbound_max_file_bytes
        == DEFAULT_EXTERNAL_CHANNEL_OUTBOUND_MAX_FILE_BYTES
    )
    assert (
        resolved.config.outbound_max_action_bytes
        == DEFAULT_EXTERNAL_CHANNEL_OUTBOUND_MAX_ACTION_BYTES
    )
    assert isinstance(resolved.secrets, ExternalChannelFilesSecrets)


async def test_external_channel_file_limits_activate_directly_and_validate_aggregate(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A valid local policy activates immediately and an invalid one never writes."""
    service = _registered_service(rdb_session_manager)

    with pytest.raises(ValidationError, match="must be at least"):
        await service.mutate(
            SystemSettingMutation(
                section=SystemSettingSection.EXTERNAL_CHANNEL_FILES,
                expected_version=0,
                config_patch={
                    "outbound_max_file_bytes": 2,
                    "outbound_max_action_bytes": 1,
                },
                secret_actions={},
                actor_user_id=None,
            )
        )

    activated = await service.mutate(
        SystemSettingMutation(
            section=SystemSettingSection.EXTERNAL_CHANNEL_FILES,
            expected_version=0,
            config_patch={
                "outbound_max_file_bytes": 20,
                "outbound_max_action_bytes": 40,
            },
            secret_actions={},
            actor_user_id=None,
        )
    )

    assert isinstance(activated, SystemSettingActivated)
    assert activated.current.version == 1
    assert isinstance(activated.resolved.config, ExternalChannelFilesConfig)
    assert activated.resolved.config.outbound_max_file_bytes == 20
    assert activated.resolved.config.outbound_max_action_bytes == 40


async def test_direct_mutation_encrypts_secrets_and_writes_metadata_only_audit(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Current state stores ciphertext while audit records actions only."""
    service = _service(rdb_session_manager)

    result = await service.mutate(_initial_mutation())

    assert isinstance(result, SystemSettingActivated)
    assert result.current.version == 1
    assert result.current.encrypted_secrets is not None
    assert "secret-value" not in result.current.encrypted_secrets
    assert result.current.secret_metadata["token"]["configured"] is True
    assert isinstance(result.resolved.secrets, _Secrets)
    assert result.resolved.secrets.token == "secret-value"
    async with rdb_session_manager() as session:
        audit = await service.repository.repository.list_audit_events(
            session,
            section=SystemSettingSection.PLATFORM_GITHUB_APP,
            offset=0,
            limit=10,
        )
    assert audit.total == 1
    assert audit.items[0].changed_fields == ["endpoint", "label"]
    assert audit.items[0].secret_actions == {"token": "replace"}
    assert "secret-value" not in repr(audit.items[0])


async def test_environment_empty_value_overrides_admin_without_fallback(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A present empty environment value stays authoritative and read-only."""
    encryption_key = Fernet.generate_key().decode()
    admin_service = _service(rdb_session_manager, key=encryption_key)
    await admin_service.mutate(_initial_mutation())
    environment_service = _service(
        rdb_session_manager,
        environment={"AZ_TEST_TOKEN": ""},
        key=encryption_key,
    )

    resolved = await environment_service.resolve(
        SystemSettingSection.PLATFORM_GITHUB_APP
    )

    assert isinstance(resolved.secrets, _Secrets)
    assert resolved.secrets.token == ""
    assert resolved.field_sources["token"] is SystemSettingFieldSource.ENVIRONMENT
    with pytest.raises(SystemSettingEnvironmentFieldReadOnly):
        await environment_service.mutate(
            SystemSettingMutation(
                section=SystemSettingSection.PLATFORM_GITHUB_APP,
                expected_version=1,
                config_patch={},
                secret_actions={
                    "token": SystemSettingSecretAction(
                        action=SystemSettingSecretActionType.CLEAR,
                        value=None,
                    )
                },
                actor_user_id=None,
            )
        )


async def test_mutation_enforces_optimistic_current_version(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A stale Admin version cannot replace current state or candidates."""
    service = _service(rdb_session_manager)
    await service.mutate(_initial_mutation())

    with pytest.raises(SystemSettingVersionConflict):
        await service.mutate(_initial_mutation())


async def test_expired_candidate_is_deleted_even_when_cancel_reports_expiry(
    rdb_session_manager: SessionManager[AsyncSession],
    monkeypatch: MonkeyPatch,
) -> None:
    """Expiry errors occur after candidate ciphertext deletion commits."""
    created_at = datetime.datetime(2026, 7, 20, 0, 0, tzinfo=datetime.UTC)
    monkeypatch.setattr(service_module, "tznow", lambda: created_at)
    service = _service(
        rdb_session_manager,
        activation_mode=SystemSettingActivationMode.VALIDATED,
    )
    pending = await service.mutate(_initial_mutation())
    assert isinstance(pending, SystemSettingCandidatePending)
    monkeypatch.setattr(
        service_module,
        "tznow",
        lambda: created_at + datetime.timedelta(hours=25),
    )

    with pytest.raises(SystemSettingCandidateExpired):
        await service.cancel_candidate(
            section=SystemSettingSection.PLATFORM_GITHUB_APP,
            candidate_id=pending.candidate.id,
            actor_user_id=None,
        )

    async with rdb_session_manager() as session:
        candidate = await service.repository.repository.get_candidate(
            session,
            section=SystemSettingSection.PLATFORM_GITHUB_APP,
        )
    assert candidate is None


async def test_health_is_visible_only_for_the_current_effective_generation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A changed effective payload makes the previous health result stale."""
    service = _service(rdb_session_manager)
    activated = await service.mutate(_initial_mutation())
    assert isinstance(activated, SystemSettingActivated)
    await service.record_health(
        section=SystemSettingSection.PLATFORM_GITHUB_APP,
        expected_generation=activated.resolved.effective_generation,
        result=SystemSettingHealthResult(
            status=SystemSettingHealthStatus.HEALTHY,
            code=None,
            message=None,
            action_hint=None,
            metadata={"slug": "example"},
        ),
        actor_user_id=None,
    )
    current = await service.get_current_health(SystemSettingSection.PLATFORM_GITHUB_APP)
    assert current.health is not None

    changed = await service.mutate(
        SystemSettingMutation(
            section=SystemSettingSection.PLATFORM_GITHUB_APP,
            expected_version=1,
            config_patch={"label": "secondary"},
            secret_actions={},
            actor_user_id=None,
        )
    )
    assert isinstance(changed, SystemSettingActivated)
    stale = await service.get_current_health(SystemSettingSection.PLATFORM_GITHUB_APP)
    assert stale.health is None


async def test_valid_candidate_auto_activates_without_confirmation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A valid candidate with no impact activates in the validation transaction."""
    service = _service(
        rdb_session_manager,
        activation_mode=SystemSettingActivationMode.VALIDATED,
    )
    pending = await service.mutate(_initial_mutation())
    assert isinstance(pending, SystemSettingCandidatePending)

    async def validator(
        _snapshot: SystemSettingCandidateValidationSnapshot,
    ) -> SystemSettingCandidateValidationResult:
        return SystemSettingCandidateValidationResult(
            status=SystemSettingValidationStatus.VALID,
            code=None,
            message=None,
            action_hint=None,
            metadata={"slug": "example"},
            impact=None,
            confirmation_required=False,
        )

    result = await service.validate_candidate(
        section=SystemSettingSection.PLATFORM_GITHUB_APP,
        candidate_id=pending.candidate.id,
        validator=validator,
    )

    assert isinstance(result, SystemSettingActivated)
    assert result.current.version == 1
    assert result.current.validation_status is SystemSettingValidationStatus.VALID
    assert result.current.validation_metadata == {"slug": "example"}


async def test_replaced_candidate_fails_in_flight_validation_as_conflict(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """An in-flight mutation cannot validate a later replacement candidate."""
    service = _service(
        rdb_session_manager,
        activation_mode=SystemSettingActivationMode.VALIDATED,
    )
    first = await service.mutate(_initial_mutation())
    assert isinstance(first, SystemSettingCandidatePending)
    replacement_id: str | None = None

    async def validator(
        _snapshot: SystemSettingCandidateValidationSnapshot,
    ) -> SystemSettingCandidateValidationResult:
        nonlocal replacement_id
        replacement = await service.mutate(
            SystemSettingMutation(
                section=SystemSettingSection.PLATFORM_GITHUB_APP,
                expected_version=0,
                config_patch={"label": "replacement"},
                secret_actions={},
                actor_user_id=None,
            )
        )
        assert isinstance(replacement, SystemSettingCandidatePending)
        replacement_id = replacement.candidate.id
        return SystemSettingCandidateValidationResult(
            status=SystemSettingValidationStatus.VALID,
            code=None,
            message=None,
            action_hint=None,
            metadata=None,
            impact=None,
            confirmation_required=False,
        )

    with pytest.raises(SystemSettingCandidateReplaced) as exc_info:
        await service.validate_candidate(
            section=SystemSettingSection.PLATFORM_GITHUB_APP,
            candidate_id=first.candidate.id,
            validator=validator,
        )

    assert exc_info.value.candidate_id == first.candidate.id
    candidate = await service.get_candidate(SystemSettingSection.PLATFORM_GITHUB_APP)
    assert candidate is not None
    assert candidate.id == replacement_id
