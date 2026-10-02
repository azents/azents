"""PostgreSQL regression for completed System Settings atomic operations."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import azents.repos.system_setting.operations as operations_module
from azents.core.crypto import CredentialCipher
from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingActivationMode,
    SystemSettingAuditEventType,
    SystemSettingCandidateExpired,
    SystemSettingCandidateNotValidated,
    SystemSettingDefinition,
    SystemSettingEffectiveGenerationChanged,
    SystemSettingEnvironment,
    SystemSettingEnvironmentBinding,
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
    StoredSystemSetting,
    StoredSystemSettingAuditEvent,
    SystemSettingActivated,
    SystemSettingAuditEventCreate,
    SystemSettingCandidatePending,
    SystemSettingCandidateValidationResult,
    SystemSettingCandidateValidationSnapshot,
    SystemSettingCurrentWrite,
    SystemSettingHealthResult,
    SystemSettingMutation,
)
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.rdb.models.system_setting import (
    RDBSystemSetting,
    RDBSystemSettingAuditEvent,
    RDBSystemSettingCandidate,
)
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

SECTION = SystemSettingSection.PLATFORM_GITHUB_APP
CREATED = datetime.datetime(2026, 7, 20, tzinfo=datetime.UTC)


class _Config(BaseModel):
    endpoint: str | None = None


class _Secrets(BaseModel):
    token: str | None = None


def _accept(_config: BaseModel, _secrets: BaseModel) -> None:
    """Accept typed local test models."""


def _service(
    manager: SessionManager[AsyncSession],
    *,
    mode: SystemSettingActivationMode,
    query: SystemSettingRepository,
    environment: dict[str, str],
) -> SystemSettingsService:
    key = Fernet.generate_key().decode()
    cipher = CredentialCipher(key)
    github_query = PlatformGitHubAppSystemSettingRepository()
    return SystemSettingsService(
        repository=SystemSettingsRepository(
            session_manager=manager,
            repository=query,
            payloads=SystemSettingPayloadResolver(
                registry=SystemSettingRegistry(
                    definitions=(
                        SystemSettingDefinition(
                            section=SECTION,
                            schema_version=1,
                            config_model=_Config,
                            secret_model=_Secrets,
                            activation_mode=mode,
                            environment_bindings=(
                                SystemSettingEnvironmentBinding(
                                    field_name="endpoint",
                                    environment_variable="AZ_TEST_ENDPOINT",
                                    target=SystemSettingFieldTarget.CONFIG,
                                ),
                            ),
                            candidate_ttl=datetime.timedelta(hours=24),
                            local_validator=_accept,
                        ),
                    ),
                ),
                cipher=cipher,
                environment=SystemSettingEnvironment(values=environment),
                generation_hasher=SystemSettingGenerationHasher(key),
            ),
            github_impact=PlatformGitHubAppImpactRepository(
                session_manager=manager,
                impact_repository=github_query,
                bindings=PlatformGitHubAppBindingRepository(
                    repository=github_query,
                    cipher=cipher,
                ),
            ),
        ),
    )


def _mutation() -> SystemSettingMutation:
    return SystemSettingMutation(
        section=SECTION,
        expected_version=0,
        config_patch={"endpoint": "initial"},
        secret_actions={
            "token": SystemSettingSecretAction(
                action=SystemSettingSecretActionType.REPLACE,
                value="test-secret",
            ),
        },
        actor_user_id=None,
    )


def _validation(*, confirmation: bool) -> SystemSettingCandidateValidationResult:
    return SystemSettingCandidateValidationResult(
        status=SystemSettingValidationStatus.VALID,
        code=None,
        message=None,
        action_hint=None,
        metadata={"sanitized": True},
        impact=None,
        confirmation_required=confirmation,
    )


class _AuditFailure(SystemSettingRepository):
    def __init__(self, event_type: SystemSettingAuditEventType) -> None:
        self.event_type = event_type

    async def append_audit_event(
        self,
        session: AsyncSession,
        *,
        create: SystemSettingAuditEventCreate,
    ) -> StoredSystemSettingAuditEvent:
        result = await super().append_audit_event(session, create=create)
        if create.event_type == self.event_type:
            raise ValueError("Injected failure after audit insert.")
        return result


@pytest.mark.parametrize("operation", ["prepare", "confirm", "cancel", "record"])
async def test_every_expiry_error_follows_committed_ciphertext_deletion(
    rdb_session_manager: SessionManager[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """Each expiry-reporting service branch deletes before raising, without audit."""
    monkeypatch.setattr(operations_module, "tznow", lambda: CREATED)
    service = _service(
        rdb_session_manager,
        mode=SystemSettingActivationMode.CONFIRMED,
        query=SystemSettingRepository(),
        environment={},
    )
    pending = await service.mutate(_mutation())
    assert isinstance(pending, SystemSettingCandidatePending)
    snapshot = await service.prepare_candidate_validation(
        SECTION,
        candidate_id=pending.candidate.id,
    )
    monkeypatch.setattr(
        operations_module,
        "tznow",
        lambda: CREATED + datetime.timedelta(hours=25),
    )
    with pytest.raises(SystemSettingCandidateExpired):
        match operation:
            case "prepare":
                await service.prepare_candidate_validation(
                    SECTION,
                    candidate_id=pending.candidate.id,
                )
            case "confirm":
                await service.confirm_candidate(
                    section=SECTION,
                    candidate_id=pending.candidate.id,
                    expected_version=0,
                    confirmation_action="activate",
                    actor_user_id=None,
                )
            case "cancel":
                await service.cancel_candidate(
                    section=SECTION,
                    candidate_id=pending.candidate.id,
                    actor_user_id=None,
                )
            case "record":
                await service._record_candidate_validation(
                    snapshot=snapshot,
                    result=_validation(confirmation=False),
                )
            case _:
                raise AssertionError(operation)
    async with rdb_session_manager() as session:
        assert (
            await service.repository.repository.get_candidate(
                session,
                section=SECTION,
            )
            is None
        )
        assert (
            await service.repository.repository.get_current(
                session,
                section=SECTION,
            )
            is None
        )
    audit = await service.repository.list_audit_events(
        section=SECTION, offset=0, limit=20
    )
    assert [item.event_type for item in audit.items] == [
        SystemSettingAuditEventType.CANDIDATE_REPLACED,
    ]


@pytest.mark.parametrize("operation", ["mutate", "state"])
async def test_expiry_cleanup_rolls_back_with_later_local_failure(
    rdb_session_manager: SessionManager[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """Cleanup in mutation/state remains in its original rollback group."""
    monkeypatch.setattr(operations_module, "tznow", lambda: CREATED)
    service = _service(
        rdb_session_manager,
        mode=SystemSettingActivationMode.VALIDATED,
        query=SystemSettingRepository(),
        environment={},
    )
    pending = await service.mutate(_mutation())
    assert isinstance(pending, SystemSettingCandidatePending)
    monkeypatch.setattr(
        operations_module,
        "tznow",
        lambda: CREATED + datetime.timedelta(hours=25),
    )
    if operation == "mutate":
        with pytest.raises(ValueError, match="Unknown System Settings config"):
            await service.mutate(
                dataclasses.replace(_mutation(), config_patch={"unknown": "value"})
            )
    else:

        def failed_projection(
            self: SystemSettingPayloadResolver,
            *,
            definition: SystemSettingDefinition,
            current: StoredSystemSetting | None,
        ) -> ResolvedSystemSetting:
            raise ValueError("Injected projection failure.")

        monkeypatch.setattr(
            SystemSettingPayloadResolver, "resolve_current", failed_projection
        )
        with pytest.raises(ValueError, match="projection failure"):
            await service.get_state(SECTION)
    async with rdb_session_manager() as session:
        candidate = await service.repository.repository.get_candidate(
            session, section=SECTION
        )
    assert candidate == pending.candidate
    assert candidate.encrypted_secrets is not None


@pytest.mark.parametrize(
    "mode", [SystemSettingActivationMode.DIRECT, SystemSettingActivationMode.VALIDATED]
)
async def test_mutation_current_candidate_and_audit_roll_back_together(
    rdb_session_manager: SessionManager[AsyncSession],
    mode: SystemSettingActivationMode,
) -> None:
    """A late audit failure cannot commit a current or candidate partial write."""
    event = (
        SystemSettingAuditEventType.ACTIVATED
        if mode == SystemSettingActivationMode.DIRECT
        else SystemSettingAuditEventType.CANDIDATE_REPLACED
    )
    service = _service(
        rdb_session_manager,
        mode=mode,
        query=_AuditFailure(event),
        environment={},
    )
    with pytest.raises(ValueError, match="after audit insert"):
        await service.mutate(_mutation())
    state = await service.get_state(SECTION)
    assert state.current is None
    assert state.candidate is None
    assert (
        await service.repository.list_audit_events(section=SECTION, offset=0, limit=10)
    ).total == 0


@pytest.mark.parametrize("operation", ["validation", "cancel", "health"])
async def test_finalization_rolls_back_partial_rows_and_audit(
    rdb_session_manager: SessionManager[AsyncSession],
    operation: str,
) -> None:
    """Validation+activation, cancel, and health writes share audit rollback."""
    mode = (
        SystemSettingActivationMode.DIRECT
        if operation == "health"
        else SystemSettingActivationMode.VALIDATED
    )
    service = _service(
        rdb_session_manager, mode=mode, query=SystemSettingRepository(), environment={}
    )
    original = await service.mutate(_mutation())
    event = {
        "validation": SystemSettingAuditEventType.ACTIVATED,
        "cancel": SystemSettingAuditEventType.CANDIDATE_CANCELLED,
        "health": SystemSettingAuditEventType.HEALTH_CHECKED,
    }[operation]
    failing = SystemSettingsService(
        repository=dataclasses.replace(
            service.repository, repository=_AuditFailure(event)
        )
    )
    with pytest.raises(ValueError, match="after audit insert"):
        match operation:
            case "validation":
                assert isinstance(original, SystemSettingCandidatePending)
                snapshot = await failing.prepare_candidate_validation(
                    SECTION, candidate_id=original.candidate.id
                )
                await failing._record_candidate_validation(
                    snapshot=snapshot, result=_validation(confirmation=False)
                )
            case "cancel":
                assert isinstance(original, SystemSettingCandidatePending)
                await failing.cancel_candidate(
                    section=SECTION,
                    candidate_id=original.candidate.id,
                    actor_user_id=None,
                )
            case "health":
                await failing.record_health(
                    section=SECTION,
                    expected_generation=original.resolved.effective_generation,
                    result=SystemSettingHealthResult(
                        status=SystemSettingHealthStatus.HEALTHY,
                        code=None,
                        message=None,
                        action_hint=None,
                        metadata=None,
                    ),
                    actor_user_id=None,
                )
            case _:
                raise AssertionError(operation)
    state = await service.get_state(SECTION)
    if isinstance(original, SystemSettingCandidatePending):
        assert state.current is None
        assert state.candidate == original.candidate
        assert (
            state.candidate.validation_status == SystemSettingValidationStatus.PENDING
        )
    else:
        assert state.current == original.current
        assert state.health is None
    assert (
        await service.repository.list_audit_events(section=SECTION, offset=0, limit=10)
    ).total == 1


async def test_validation_and_health_recheck_environment_generation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """External work cannot authorize a write after environment authority drifts."""
    environment: dict[str, str] = {}
    service = _service(
        rdb_session_manager,
        mode=SystemSettingActivationMode.CONFIRMED,
        query=SystemSettingRepository(),
        environment=environment,
    )
    pending = await service.mutate(_mutation())
    assert isinstance(pending, SystemSettingCandidatePending)
    snapshot = await service.prepare_candidate_validation(
        SECTION, candidate_id=pending.candidate.id
    )
    environment["AZ_TEST_ENDPOINT"] = "changed"
    with pytest.raises(SystemSettingEffectiveGenerationChanged):
        await service._record_candidate_validation(
            snapshot=snapshot, result=_validation(confirmation=True)
        )
    with pytest.raises(SystemSettingEffectiveGenerationChanged):
        await service.record_health(
            section=SECTION,
            expected_generation=snapshot.current_resolved.effective_generation,
            result=SystemSettingHealthResult(
                status=SystemSettingHealthStatus.HEALTHY,
                code=None,
                message=None,
                action_hint=None,
                metadata=None,
            ),
            actor_user_id=None,
        )
    candidate = await service.get_candidate(SECTION)
    assert candidate == pending.candidate
    assert (
        await service.repository.list_audit_events(section=SECTION, offset=0, limit=10)
    ).total == 1


@pytest.mark.parametrize("operation", ["prepare", "confirm", "record"])
async def test_finalization_rejects_changed_candidate_base_version(
    rdb_session_manager: SessionManager[AsyncSession],
    operation: str,
) -> None:
    """A changed current row invalidates the original candidate across all phases."""
    service = _service(
        rdb_session_manager,
        mode=SystemSettingActivationMode.CONFIRMED,
        query=SystemSettingRepository(),
        environment={},
    )
    pending = await service.mutate(_mutation())
    assert isinstance(pending, SystemSettingCandidatePending)
    snapshot = await service.prepare_candidate_validation(
        SECTION,
        candidate_id=pending.candidate.id,
    )
    async with rdb_session_manager() as session:
        await service.repository.repository.write_current(
            session,
            write=SystemSettingCurrentWrite(
                section=SECTION,
                schema_version=1,
                version=1,
                config=pending.candidate.config,
                encrypted_secrets=pending.candidate.encrypted_secrets,
                secret_metadata=pending.candidate.secret_metadata,
                validation_status=None,
                validated_generation=None,
                validation_metadata=None,
                validated_at=None,
                updated_by_user_id=None,
            ),
        )
    with pytest.raises(SystemSettingVersionConflict) as error:
        match operation:
            case "prepare":
                await service.prepare_candidate_validation(
                    SECTION,
                    candidate_id=pending.candidate.id,
                )
            case "confirm":
                await service.confirm_candidate(
                    section=SECTION,
                    candidate_id=pending.candidate.id,
                    expected_version=1,
                    confirmation_action="activate",
                    actor_user_id=None,
                )
            case "record":
                await service._record_candidate_validation(
                    snapshot=snapshot,
                    result=_validation(confirmation=False),
                )
            case _:
                raise AssertionError(operation)
    assert error.value.expected_version == 0
    assert error.value.current_version == 1
    assert await service.get_candidate(SECTION) == pending.candidate
    assert (
        await service.repository.list_audit_events(section=SECTION, offset=0, limit=10)
    ).total == 1


async def test_late_cipher_failure_rolls_back_expired_candidate_cleanup(
    rdb_session_manager: SessionManager[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pure encryption remains inside the mutation's original rollback boundary."""
    monkeypatch.setattr(operations_module, "tznow", lambda: CREATED)
    service = _service(
        rdb_session_manager,
        mode=SystemSettingActivationMode.VALIDATED,
        query=SystemSettingRepository(),
        environment={},
    )
    pending = await service.mutate(_mutation())
    assert isinstance(pending, SystemSettingCandidatePending)
    monkeypatch.setattr(
        operations_module,
        "tznow",
        lambda: CREATED + datetime.timedelta(hours=25),
    )

    def fail_encrypt(self: CredentialCipher, plaintext: str) -> str:
        raise ValueError("Injected cipher failure.")

    monkeypatch.setattr(CredentialCipher, "encrypt", fail_encrypt)
    with pytest.raises(ValueError, match="cipher failure"):
        await service.mutate(_mutation())
    async with rdb_session_manager() as session:
        assert (
            await service.repository.repository.get_candidate(
                session,
                section=SECTION,
            )
            == pending.candidate
        )


async def test_secret_omit_null_clear_and_present_empty_remain_distinct(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Ownership extraction preserves null/omit behavior and explicit secret actions."""
    service = _service(
        rdb_session_manager,
        mode=SystemSettingActivationMode.DIRECT,
        query=SystemSettingRepository(),
        environment={},
    )
    initial = await service.mutate(_mutation())
    assert isinstance(initial, SystemSettingActivated)
    null_config = await service.mutate(
        SystemSettingMutation(
            section=SECTION,
            expected_version=1,
            config_patch={"endpoint": None},
            secret_actions={},
            actor_user_id=None,
        )
    )
    assert isinstance(null_config, SystemSettingActivated)
    assert isinstance(null_config.resolved.config, _Config)
    assert null_config.resolved.config.endpoint is None
    assert isinstance(null_config.resolved.secrets, _Secrets)
    assert null_config.resolved.secrets.token == "test-secret"
    assert null_config.current.secret_metadata == initial.current.secret_metadata
    empty_secret = await service.mutate(
        SystemSettingMutation(
            section=SECTION,
            expected_version=2,
            config_patch={},
            secret_actions={
                "token": SystemSettingSecretAction(
                    action=SystemSettingSecretActionType.REPLACE,
                    value="",
                )
            },
            actor_user_id=None,
        )
    )
    assert isinstance(empty_secret, SystemSettingActivated)
    assert isinstance(empty_secret.resolved.secrets, _Secrets)
    assert empty_secret.resolved.secrets.token == ""
    assert empty_secret.current.encrypted_secrets is not None
    cleared = await service.mutate(
        SystemSettingMutation(
            section=SECTION,
            expected_version=3,
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
    assert isinstance(cleared, SystemSettingActivated)
    assert isinstance(cleared.resolved.secrets, _Secrets)
    assert cleared.resolved.secrets.token is None
    assert cleared.current.encrypted_secrets is None
    assert cleared.current.secret_metadata["token"]["configured"] is False
    assert cleared.current.config == empty_secret.current.config
    audit = await service.repository.list_audit_events(
        section=SECTION, offset=0, limit=10
    )
    assert audit.total == 4
    assert "test-secret" not in repr(audit.items)


async def test_generic_confirmation_authority_is_independent_of_github_policy(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Generic confirmation fences do not require GitHub payload models."""
    environment: dict[str, str] = {}
    service = _service(
        rdb_session_manager,
        mode=SystemSettingActivationMode.CONFIRMED,
        query=SystemSettingRepository(),
        environment=environment,
    )
    pending = await service.mutate(_mutation())
    assert isinstance(pending, SystemSettingCandidatePending)
    with pytest.raises(SystemSettingCandidateNotValidated):
        await service.confirm_candidate(
            section=SECTION,
            candidate_id=pending.candidate.id,
            expected_version=0,
            confirmation_action="activate",
            actor_user_id=None,
        )
    snapshot = await service.prepare_candidate_validation(
        SECTION, candidate_id=pending.candidate.id
    )
    validated = await service._record_candidate_validation(
        snapshot=snapshot, result=_validation(confirmation=True)
    )
    assert isinstance(validated, SystemSettingCandidatePending)
    with pytest.raises(SystemSettingVersionConflict):
        await service.confirm_candidate(
            section=SECTION,
            candidate_id=pending.candidate.id,
            expected_version=1,
            confirmation_action="activate",
            actor_user_id=None,
        )
    async with rdb_session_manager() as session:
        await service.repository.repository.acquire_section_lock(
            session, section=SECTION
        )
        checked = await service.repository._prepare_confirmation_in_session(
            session,
            definition=service.repository.payloads.registry.get(SECTION),
            candidate=validated.candidate,
            expected_version=0,
        )
    assert isinstance(checked.candidate_resolved.config, _Config)
    environment["AZ_TEST_ENDPOINT"] = "changed"
    with pytest.raises(SystemSettingEffectiveGenerationChanged):
        await service.confirm_candidate(
            section=SECTION,
            candidate_id=pending.candidate.id,
            expected_version=0,
            confirmation_action="activate",
            actor_user_id=None,
        )
    assert (await service.get_state(SECTION)).current is None


@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_external_validation_failure_and_cancellation_leave_no_open_db(
    rdb_session_manager: SessionManager[AsyncSession],
    failure: str,
) -> None:
    """A detached external validator runs once after preparation has completed."""
    opened: list[AsyncSession] = []
    active: list[AsyncSession] = []

    @asynccontextmanager
    async def tracked_manager() -> AsyncIterator[AsyncSession]:
        async with rdb_session_manager() as session:
            opened.append(session)
            active.append(session)
            try:
                yield session
            finally:
                active.remove(session)

    service = _service(
        tracked_manager,
        mode=SystemSettingActivationMode.VALIDATED,
        query=SystemSettingRepository(),
        environment={},
    )
    pending = await service.mutate(_mutation())
    assert isinstance(pending, SystemSettingCandidatePending)
    calls = 0

    async def validator(
        snapshot: SystemSettingCandidateValidationSnapshot,
    ) -> SystemSettingCandidateValidationResult:
        nonlocal calls
        calls += 1
        assert snapshot.candidate.id == pending.candidate.id
        assert not active
        assert all(not session.in_transaction() for session in opened)
        if failure == "cancel":
            raise asyncio.CancelledError()
        raise ValueError("External failure.")

    expected = asyncio.CancelledError if failure == "cancel" else ValueError
    with pytest.raises(expected):
        await service.validate_candidate(
            section=SECTION, candidate_id=pending.candidate.id, validator=validator
        )
    assert calls == 1
    assert not active
    assert await service.get_candidate(SECTION) == pending.candidate
    assert (
        await service.repository.list_audit_events(section=SECTION, offset=0, limit=10)
    ).total == 1


async def test_section_lock_serializes_competing_mutations_with_version_fence(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Independent PostgreSQL sessions cannot activate the same expected version."""
    first_locked = asyncio.Event()
    second_started = asyncio.Event()
    release_first = asyncio.Event()

    class GatedRepository(SystemSettingRepository):
        def __init__(self) -> None:
            self.calls = 0

        async def acquire_section_lock(
            self, session: AsyncSession, *, section: SystemSettingSection
        ) -> None:
            self.calls += 1
            attempt = self.calls
            if attempt == 2:
                second_started.set()
            await super().acquire_section_lock(session, section=section)
            if attempt == 1:
                first_locked.set()
                await release_first.wait()

    @asynccontextmanager
    async def independent_manager() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            async with session.begin():
                yield session

    service = _service(
        independent_manager,
        mode=SystemSettingActivationMode.DIRECT,
        query=GatedRepository(),
        environment={},
    )
    tasks: list[
        asyncio.Task[SystemSettingActivated | SystemSettingCandidatePending]
    ] = []
    try:
        tasks.append(asyncio.create_task(service.mutate(_mutation())))
        await asyncio.wait_for(first_locked.wait(), timeout=10)
        tasks.append(asyncio.create_task(service.mutate(_mutation())))
        await asyncio.wait_for(second_started.wait(), timeout=10)
        release_first.set()
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=10
        )
        assert isinstance(results[0], SystemSettingActivated)
        assert isinstance(results[1], SystemSettingVersionConflict)
        assert (await service.resolve(SECTION)).admin_version == 1
        assert (
            await service.repository.list_audit_events(
                section=SECTION, offset=0, limit=10
            )
        ).total == 1
    finally:
        release_first.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        async with independent_manager() as session:
            await session.execute(
                sa.delete(RDBSystemSettingAuditEvent).where(
                    RDBSystemSettingAuditEvent.section == SECTION
                )
            )
            await session.execute(
                sa.delete(RDBSystemSettingCandidate).where(
                    RDBSystemSettingCandidate.section == SECTION
                )
            )
            await session.execute(
                sa.delete(RDBSystemSetting).where(RDBSystemSetting.section == SECTION)
            )
