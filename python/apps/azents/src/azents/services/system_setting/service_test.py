"""Provider-neutral SystemSettingsService tests."""

import datetime

import pytest
from cryptography.fernet import Fernet
from pydantic import BaseModel
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession

import azents.services.system_setting.service as service_module
from azents.core.crypto import CredentialCipher
from azents.core.system_setting import (
    SystemDataMigrationOutcome,
    SystemSettingActivationMode,
    SystemSettingCandidateExpired,
    SystemSettingDefinition,
    SystemSettingEnvironment,
    SystemSettingEnvironmentBinding,
    SystemSettingEnvironmentFieldReadOnly,
    SystemSettingFieldSource,
    SystemSettingFieldTarget,
    SystemSettingGenerationHasher,
    SystemSettingHealthStatus,
    SystemSettingImpactChanged,
    SystemSettingRegistry,
    SystemSettingSecretAction,
    SystemSettingSecretActionType,
    SystemSettingSection,
    SystemSettingValidationStatus,
    SystemSettingVersionConflict,
)
from azents.rdb.session import SessionManager
from azents.repos.system_setting.repository import (
    SystemDataMigrationRepository,
    SystemSettingRepository,
)
from azents.services.system_setting.data import (
    SystemDataMigrationResult,
    SystemSettingActivated,
    SystemSettingCandidatePending,
    SystemSettingCandidateValidationResult,
    SystemSettingCandidateValidationSnapshot,
    SystemSettingHealthResult,
    SystemSettingMutation,
)
from azents.services.system_setting.service import (
    SystemDataMigrationRunner,
    SystemSettingsService,
)


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
    return SystemSettingsService(
        session_manager=session_manager,
        repository=SystemSettingRepository(),
        registry=SystemSettingRegistry(
            definitions=(_definition(activation_mode),),
        ),
        cipher=CredentialCipher(encryption_key),
        environment=SystemSettingEnvironment(values=environment or {}),
        generation_hasher=SystemSettingGenerationHasher(encryption_key),
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
        audit = await service.repository.list_audit_events(
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
        candidate = await service.repository.get_candidate(
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
        validator=validator,
    )

    assert isinstance(result, SystemSettingActivated)
    assert result.current.version == 1
    assert result.current.validation_status is SystemSettingValidationStatus.VALID
    assert result.current.validation_metadata == {"slug": "example"}


async def test_confirmation_rechecks_impact_before_activation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Confirmation fails closed when resource impact changed after validation."""
    service = _service(
        rdb_session_manager,
        activation_mode=SystemSettingActivationMode.CONFIRMED,
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
            metadata=None,
            impact={"affected_count": 1},
            confirmation_required=True,
        )

    validated = await service.validate_candidate(
        section=SystemSettingSection.PLATFORM_GITHUB_APP,
        validator=validator,
    )
    assert isinstance(validated, SystemSettingCandidatePending)

    async def changed_impact(
        _session: AsyncSession,
        _current: object,
        _candidate: object,
    ) -> dict[str, object]:
        return {"affected_count": 2}

    async def confirm(
        _session: AsyncSession,
        _action: str,
        _candidate: object,
        _impact: dict[str, object] | None,
    ) -> None:
        return None

    with pytest.raises(SystemSettingImpactChanged) as exc_info:
        await service.confirm_candidate(
            section=SystemSettingSection.PLATFORM_GITHUB_APP,
            candidate_id=validated.candidate.id,
            expected_version=0,
            confirmation_action="activate",
            actor_user_id=None,
            impact_resolver=changed_impact,
            confirmation_handler=confirm,
        )
    assert exc_info.value.current_impact == {"affected_count": 2}


async def test_application_data_migration_runner_is_idempotent(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A committed marker prevents the application operation from running twice."""
    runner = SystemDataMigrationRunner(
        session_manager=rdb_session_manager,
        repository=SystemDataMigrationRepository(),
    )
    calls = 0

    async def operation(_session: AsyncSession) -> SystemDataMigrationResult:
        nonlocal calls
        calls += 1
        return SystemDataMigrationResult(
            outcome=SystemDataMigrationOutcome.APPLIED,
            metadata={"updated_count": 3},
        )

    first = await runner.run(name="test_system_setting_migration", operation=operation)
    second = await runner.run(name="test_system_setting_migration", operation=operation)

    assert calls == 1
    assert first == second
    assert first.outcome is SystemDataMigrationOutcome.APPLIED
    assert first.metadata == {"updated_count": 3}
