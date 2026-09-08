"""Runtime connection registration orchestration tests."""

import dataclasses
import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence
from azents_runtime_control.transfer import (
    RUNNER_TRANSFER_CAPABILITY,
    RUNNER_TRANSFER_PROTOCOL_VERSION,
)
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeConnectionAuthorityKind,
    RuntimeProviderAuthMethod,
    RuntimeProviderKind,
    RuntimeProviderScope,
)
from azents.core.runtime_runner_credential import RuntimeRunnerCredential
from azents.repos.runtime_connection_generation.data import (
    RuntimeConnectionGeneration,
)
from azents.runtime.control_protocol.data import (
    RuntimeProtocolCapabilities,
    RuntimeProviderRegistration,
    RuntimeRunnerRegistration,
)
from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeConnectionPromotionResult,
)
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.services.runtime_provider_control.data import (
    RuntimeProviderCredentialAuthentication,
)

from .data import RuntimeConnectionRegistrationUnavailable
from .service import (
    RuntimeProviderConnectionRegistrationService,
    RuntimeRunnerConnectionRegistrationService,
)


class _SessionManager:
    def __init__(self) -> None:
        self.sessions: list[AsyncSession] = []

    def __call__(self) -> object:
        return self._open()

    @asynccontextmanager
    async def _open(self) -> AsyncGenerator[AsyncSession, None]:
        session = AsyncSession()
        await session.begin()
        self.sessions.append(session)
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
        finally:
            await session.close()


class _GenerationAuthority:
    def __init__(self) -> None:
        self.high_water: dict[tuple[RuntimeConnectionAuthorityKind, str], int] = {}
        self.accepted: dict[tuple[RuntimeConnectionAuthorityKind, str], int] = {}
        self.accept_session: AsyncSession | None = None
        self.reject_acceptance = False

    async def allocate_generation(
        self,
        session: AsyncSession,
        *,
        connection_kind: RuntimeConnectionAuthorityKind,
        subject_id: str,
    ) -> RuntimeConnectionGeneration:
        assert session.in_transaction()
        key = (connection_kind, subject_id)
        generation = self.high_water.get(key, 0) + 1
        self.high_water[key] = generation
        return self._state(key)

    async def generation_is_current_high_water(
        self,
        session: AsyncSession,
        *,
        connection_kind: RuntimeConnectionAuthorityKind,
        subject_id: str,
        generation: int,
    ) -> bool:
        assert session.in_transaction()
        return self.high_water.get((connection_kind, subject_id)) == generation

    async def accept_generation(
        self,
        session: AsyncSession,
        *,
        connection_kind: RuntimeConnectionAuthorityKind,
        subject_id: str,
        generation: int,
    ) -> RuntimeConnectionGeneration | None:
        assert session.in_transaction()
        self.accept_session = session
        key = (connection_kind, subject_id)
        if self.reject_acceptance or self.high_water.get(key) != generation:
            return None
        self.accepted[key] = generation
        return self._state(key)

    def _state(
        self,
        key: tuple[RuntimeConnectionAuthorityKind, str],
    ) -> RuntimeConnectionGeneration:
        now = datetime.now(UTC)
        return RuntimeConnectionGeneration(
            connection_kind=key[0],
            subject_id=key[1],
            high_water_generation=self.high_water[key],
            accepted_generation=self.accepted.get(key, 0),
            created_at=now,
            updated_at=now,
        )


class _TransactionCheckingStore(InMemoryRuntimeCoordinationStore):
    def __init__(self, session_manager: _SessionManager) -> None:
        super().__init__()
        self.session_manager = session_manager
        self.external_calls = 0

    def _assert_transactions_closed(self) -> None:
        assert all(
            not session.in_transaction() for session in self.session_manager.sessions
        )
        self.external_calls += 1

    async def stage_connection_candidate(self, **kwargs: object) -> bool:
        self._assert_transactions_closed()
        return await super().stage_connection_candidate(**kwargs)  # ty: ignore[invalid-argument-type]

    async def promote_connection_candidate(
        self, **kwargs: object
    ) -> RuntimeConnectionPromotionResult:
        self._assert_transactions_closed()
        return await super().promote_connection_candidate(**kwargs)  # ty: ignore[invalid-argument-type]

    async def revoke_connection(self, **kwargs: object) -> bool:
        self._assert_transactions_closed()
        return await super().revoke_connection(**kwargs)  # ty: ignore[invalid-argument-type]


class _ProviderAuthority:
    def __init__(self) -> None:
        self.validate_sessions: list[AsyncSession] = []
        self.validated_at: list[datetime] = []
        self.create_session: AsyncSession | None = None

    async def validate_connection_authority_in_transaction(
        self,
        session: AsyncSession,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        validated_at: datetime,
    ) -> None:
        assert session.in_transaction()
        self.validate_sessions.append(session)
        self.validated_at.append(validated_at)
        if (
            authentication.evidence_expires_at is not None
            and authentication.evidence_expires_at <= validated_at
        ):
            raise RuntimeError("provider evidence expired")

    async def create_connection_in_transaction(
        self,
        session: AsyncSession,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        connection_id: str,
        generation: int,
        reported_provider_type: str,
        reported_protocol_version: str,
        operational_diagnostics: object,
        authorized_at: datetime,
        connected_at: datetime,
    ) -> object:
        del (
            connection_id,
            generation,
            reported_provider_type,
            reported_protocol_version,
            operational_diagnostics,
            connected_at,
        )
        assert session.in_transaction()
        await self.validate_connection_authority_in_transaction(
            session,
            authentication=authentication,
            validated_at=authorized_at,
        )
        self.create_session = session
        return object()


class _RunnerAuthority:
    async def authorize_runner_in_transaction(
        self,
        session: AsyncSession,
        credential: RuntimeRunnerCredential,
    ) -> bool:
        del credential
        assert session.in_transaction()
        return True


@dataclasses.dataclass
class _GenerationObserver:
    replacements: list[tuple[int, int]] = dataclasses.field(default_factory=list)

    async def on_runner_replaced(
        self,
        *,
        runtime_id: str,
        previous_generation: int,
        generation: int,
    ) -> None:
        assert runtime_id == "runtime-1"
        self.replacements.append((previous_generation, generation))

    async def on_runner_revoked(self, *, runtime_id: str, generation: int) -> None:
        del runtime_id, generation


@dataclasses.dataclass
class _Clock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


class _PromotionHookStore(_TransactionCheckingStore):
    def __init__(
        self,
        session_manager: _SessionManager,
        *,
        after_promotion: Callable[[], None],
    ) -> None:
        super().__init__(session_manager)
        self.after_promotion = after_promotion

    async def promote_connection_candidate(
        self,
        **kwargs: object,
    ) -> RuntimeConnectionPromotionResult:
        result = await super().promote_connection_candidate(**kwargs)
        self.after_promotion()
        return result


@pytest.mark.asyncio
async def test_provider_registration_separates_external_calls_from_transactions() -> (
    None
):
    sessions = _SessionManager()
    generations = _GenerationAuthority()
    store = _TransactionCheckingStore(sessions)
    provider = _ProviderAuthority()
    now = datetime.now(UTC)
    service = RuntimeProviderConnectionRegistrationService(
        session_manager=sessions,  # ty: ignore[invalid-argument-type]
        generation_repository=generations,
        coordination_store=store,
        provider_control=provider,
        clock=lambda: now,
    )

    accepted = await service.register_provider(
        _provider_registration(),
        authentication=_provider_authentication(),
        registered_at=now,
    )

    assert accepted.generation == 1
    assert store.external_calls == 2
    assert generations.accept_session is provider.create_session
    assert len(provider.validate_sessions) == 2
    assert provider.validated_at == [now, now]


@pytest.mark.asyncio
async def test_provider_final_acceptance_rechecks_current_evidence_time() -> None:
    """Evidence that expires after promotion rejects and revokes registration."""
    sessions = _SessionManager()
    generations = _GenerationAuthority()
    provider = _ProviderAuthority()
    started_at = datetime(2026, 9, 8, tzinfo=UTC)
    clock = _Clock(started_at)
    store = _PromotionHookStore(
        sessions,
        after_promotion=lambda: setattr(
            clock,
            "now",
            started_at + timedelta(seconds=2),
        ),
    )
    service = RuntimeProviderConnectionRegistrationService(
        session_manager=sessions,  # ty: ignore[invalid-argument-type]
        generation_repository=generations,
        coordination_store=store,
        provider_control=provider,
        clock=clock,
    )
    authentication = dataclasses.replace(
        _provider_authentication(),
        evidence_expires_at=started_at + timedelta(seconds=1),
    )

    with pytest.raises(RuntimeError, match="provider evidence expired"):
        await service.register_provider(
            _provider_registration(),
            authentication=authentication,
            registered_at=started_at,
        )

    assert provider.validated_at == [
        started_at,
        started_at + timedelta(seconds=2),
    ]
    assert (
        await store.get_connection(
            kind=RuntimeConnectionKind.PROVIDER,
            subject_id="provider-1",
        )
        is None
    )


@pytest.mark.asyncio
async def test_failed_final_acceptance_revokes_only_after_transaction_ends() -> None:
    sessions = _SessionManager()
    generations = _GenerationAuthority()
    generations.reject_acceptance = True
    store = _TransactionCheckingStore(sessions)
    service = RuntimeRunnerConnectionRegistrationService(
        session_manager=sessions,  # ty: ignore[invalid-argument-type]
        generation_repository=generations,
        coordination_store=store,
        runner_authentication=_RunnerAuthority(),
        generation_observer=None,
    )

    with pytest.raises(RuntimeConnectionRegistrationUnavailable, match="superseded"):
        await service.register_runner(
            _runner_registration(),
            authentication=_runner_credential(),
            registered_at=datetime.now(UTC),
        )

    assert store.external_calls == 3
    assert (
        await store.get_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id="runtime-1",
        )
        is None
    )


@pytest.mark.asyncio
async def test_runner_replacement_observer_runs_after_durable_acceptance() -> None:
    sessions = _SessionManager()
    generations = _GenerationAuthority()
    store = _TransactionCheckingStore(sessions)
    observer = _GenerationObserver()
    service = RuntimeRunnerConnectionRegistrationService(
        session_manager=sessions,  # ty: ignore[invalid-argument-type]
        generation_repository=generations,
        coordination_store=store,
        runner_authentication=_RunnerAuthority(),
        generation_observer=observer,
    )
    now = datetime.now(UTC)

    first = await service.register_runner(
        _runner_registration(),
        authentication=_runner_credential(),
        registered_at=now,
    )
    second = await service.register_runner(
        dataclasses.replace(_runner_registration(), connection_id="connection-2"),
        authentication=_runner_credential(),
        registered_at=now,
    )

    assert first.generation == 1
    assert second.generation == 2
    assert observer.replacements == [(1, 2)]


@pytest.mark.asyncio
async def test_runner_observer_failure_does_not_reject_committed_acceptance(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Post-commit replacement cleanup remains best effort."""
    sessions = _SessionManager()
    generations = _GenerationAuthority()
    store = _TransactionCheckingStore(sessions)

    class _FailingObserver(_GenerationObserver):
        async def on_runner_replaced(
            self,
            *,
            runtime_id: str,
            previous_generation: int,
            generation: int,
        ) -> None:
            del runtime_id, previous_generation, generation
            raise RuntimeError("observer failed")

    service = RuntimeRunnerConnectionRegistrationService(
        session_manager=sessions,  # ty: ignore[invalid-argument-type]
        generation_repository=generations,
        coordination_store=store,
        runner_authentication=_RunnerAuthority(),
        generation_observer=_FailingObserver(),
    )
    now = datetime.now(UTC)
    await service.register_runner(
        _runner_registration(),
        authentication=_runner_credential(),
        registered_at=now,
    )

    with caplog.at_level(
        logging.ERROR,
        logger="azents.services.runtime_connection_registration.service",
    ):
        accepted = await service.register_runner(
            dataclasses.replace(
                _runner_registration(),
                connection_id="connection-2",
            ),
            authentication=_runner_credential(),
            registered_at=now,
        )

    assert accepted.generation == 2
    assert (
        generations.accepted[(RuntimeConnectionAuthorityKind.RUNNER, "runtime-1")] == 2
    )
    assert "Runtime Runner replacement observer failed" in caplog.text


def _provider_registration() -> RuntimeProviderRegistration:
    return RuntimeProviderRegistration(
        provider_id="provider-1",
        provider_type="docker",
        scope="system",
        workspace_id=None,
        protocol_version="provider-v1",
        capabilities=RuntimeProtocolCapabilities(("lifecycle",)),
        config_schema_version="v1",
        metadata={},
        capability_contract={},
        operational_diagnostics=None,
        auth_credential_id="credential-1",
        connection_id="connection-1",
        owner_replica_id="control-a",
    )


def _provider_authentication() -> RuntimeProviderCredentialAuthentication:
    return RuntimeProviderCredentialAuthentication(
        binding_id="binding-1",
        credential_id="credential-1",
        provider_id="provider-1",
        provider_resource_id="provider-resource-1",
        provider_kind=RuntimeProviderKind.DOCKER,
        provider_scope=RuntimeProviderScope.SYSTEM,
        provider_workspace_id=None,
        auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
        auth_subject="admin:provider-resource-1",
        evidence_expires_at=None,
    )


def _runner_registration() -> RuntimeRunnerRegistration:
    return RuntimeRunnerRegistration(
        runtime_id="runtime-1",
        runner_id="runner-1",
        protocol_version=RUNNER_TRANSFER_PROTOCOL_VERSION,
        capabilities=RuntimeProtocolCapabilities((RUNNER_TRANSFER_CAPABILITY,)),
        health="ready",
        workspace_path="/workspace/agent",
        metadata={},
        auth_credential_id="runner-credential-1",
        runtime_configuration=RuntimeConfigurationEvidence(
            configuration_sequence=1,
            digest="d" * 64,
            desired_generation=1,
        ),
        connection_id="connection-1",
        owner_replica_id="control-a",
    )


def _runner_credential() -> RuntimeRunnerCredential:
    return RuntimeRunnerCredential(
        credential_id="runner-credential-1",
        runtime_id="runtime-1",
        desired_generation=1,
    )
