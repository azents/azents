"""Test-only Runtime coordination publication helpers."""

from datetime import datetime, timedelta
from typing import Protocol

from azents_runtime_control.provider import RuntimeProviderOperationalDiagnostics
from azents_runtime_control.transfer import (
    RUNNER_TRANSFER_CAPABILITY,
    RUNNER_TRANSFER_PROTOCOL_VERSION,
)

from azents.core.runtime_runner_credential import RuntimeRunnerCredential
from azents.runtime.control_protocol.data import (
    RuntimeProviderRegistration,
    RuntimeProviderRegistrationAccepted,
    RuntimeRunnerRegistration,
    RuntimeRunnerRegistrationAccepted,
)
from azents.runtime.control_protocol.service import RuntimeControlProtocolService
from azents.runtime.coordination.data import (
    JsonValue,
    RuntimeConnectionKind,
    RuntimeConnectionPromotionStatus,
    RuntimeConnectionRecord,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.services.runtime_provider_control.data import (
    RuntimeProviderCredentialAuthentication,
)

_TEST_CONNECTION_TTL_SECONDS = 60
_TEST_CANDIDATE_TTL_SECONDS = 15
_TEST_HEARTBEAT_INTERVAL_SECONDS = 20


class _RuntimeProviderConnectionTracker(Protocol):
    async def create_connection(
        self,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        connection_id: str,
        generation: int,
        reported_provider_type: str,
        reported_protocol_version: str,
        operational_diagnostics: RuntimeProviderOperationalDiagnostics | None,
        connected_at: datetime,
    ) -> object:
        """Record one test Provider connection."""
        ...


async def publish_test_connection(
    store: RuntimeCoordinationStore,
    *,
    kind: RuntimeConnectionKind,
    subject_id: str,
    connection_id: str,
    owner_replica_id: str,
    generation: int,
    connected_at: datetime,
    heartbeat_at: datetime,
    ttl_seconds: int,
    metadata: dict[str, JsonValue],
) -> RuntimeConnectionRecord:
    """Publish one explicitly generated connection for focused tests."""
    record = RuntimeConnectionRecord(
        kind=kind,
        subject_id=subject_id,
        connection_id=connection_id,
        owner_replica_id=owner_replica_id,
        generation=generation,
        connected_at=connected_at,
        heartbeat_at=heartbeat_at,
        expires_at=heartbeat_at + timedelta(seconds=ttl_seconds),
        metadata=metadata,
    )
    token = f"test-publication:{kind.value}:{subject_id}:{generation}:{connection_id}"
    staged = await store.stage_connection_candidate(
        record=record,
        publication_token=token,
        ttl_seconds=min(_TEST_CANDIDATE_TTL_SECONDS, ttl_seconds),
    )
    if not staged:
        raise AssertionError("Test connection candidate was not staged")
    promotion = await store.promote_connection_candidate(
        kind=kind,
        subject_id=subject_id,
        generation=generation,
        publication_token=token,
        ttl_seconds=ttl_seconds,
    )
    if (
        promotion.status is not RuntimeConnectionPromotionStatus.APPLIED
        or promotion.connection is None
    ):
        raise AssertionError(f"Test connection promotion failed: {promotion.status}")
    return promotion.connection


async def publish_next_test_connection(
    store: RuntimeCoordinationStore,
    *,
    kind: RuntimeConnectionKind,
    subject_id: str,
    connection_id: str,
    owner_replica_id: str,
    connected_at: datetime,
    heartbeat_at: datetime,
    ttl_seconds: int,
    metadata: dict[str, JsonValue],
) -> RuntimeConnectionRecord:
    """Publish the next test-local connection generation."""
    current = await store.get_connection(kind=kind, subject_id=subject_id)
    generation = current.generation + 1 if current is not None else 1
    return await publish_test_connection(
        store,
        kind=kind,
        subject_id=subject_id,
        connection_id=connection_id,
        owner_replica_id=owner_replica_id,
        generation=generation,
        connected_at=connected_at,
        heartbeat_at=heartbeat_at,
        ttl_seconds=ttl_seconds,
        metadata=metadata,
    )


class FakeRuntimeControlProtocolService(RuntimeControlProtocolService):
    """Control protocol test double with explicit volatile publication only."""

    def __init__(self, store: RuntimeCoordinationStore, **kwargs: object) -> None:
        super().__init__(store, **kwargs)  # ty: ignore[invalid-argument-type]
        self.store = store
        self._test_store = store
        self._test_generations: dict[tuple[RuntimeConnectionKind, str], int] = {}

    async def register_provider(
        self,
        registration: RuntimeProviderRegistration,
        *,
        registered_at: datetime,
    ) -> RuntimeProviderRegistrationAccepted:
        """Publish one Provider connection with a test-local generation."""
        key = (RuntimeConnectionKind.PROVIDER, registration.provider_id)
        generation = self._test_generations.get(key, 0) + 1
        self._test_generations[key] = generation
        record = await publish_test_connection(
            self._test_store,
            kind=RuntimeConnectionKind.PROVIDER,
            subject_id=registration.provider_id,
            connection_id=registration.connection_id,
            owner_replica_id=registration.owner_replica_id,
            generation=generation,
            connected_at=registered_at,
            heartbeat_at=registered_at,
            ttl_seconds=_TEST_CONNECTION_TTL_SECONDS,
            metadata={
                "provider_type": registration.provider_type,
                "scope": registration.scope,
                "workspace_id": registration.workspace_id,
                "protocol_version": registration.protocol_version,
                "capabilities": list(registration.capabilities.values),
                "config_schema_version": registration.config_schema_version,
                "auth_credential_id": registration.auth_credential_id,
                "metadata": registration.metadata,
            },
        )
        return RuntimeProviderRegistrationAccepted(
            provider_id=registration.provider_id,
            connection_id=registration.connection_id,
            generation=record.generation,
            heartbeat_interval_seconds=_TEST_HEARTBEAT_INTERVAL_SECONDS,
        )

    async def register_runner(
        self,
        registration: RuntimeRunnerRegistration,
        *,
        registered_at: datetime,
    ) -> RuntimeRunnerRegistrationAccepted:
        """Publish one Runner connection with a test-local generation."""
        if registration.protocol_version != RUNNER_TRANSFER_PROTOCOL_VERSION:
            raise ValueError("Runner protocol version is not supported")
        if RUNNER_TRANSFER_CAPABILITY not in registration.capabilities.values:
            raise ValueError("Runner transfer capability is required")
        key = (RuntimeConnectionKind.RUNNER, registration.runtime_id)
        generation = self._test_generations.get(key, 0) + 1
        self._test_generations[key] = generation
        previous = await self._test_store.get_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=registration.runtime_id,
        )
        record = await publish_test_connection(
            self._test_store,
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=registration.runtime_id,
            connection_id=registration.connection_id,
            owner_replica_id=registration.owner_replica_id,
            generation=generation,
            connected_at=registered_at,
            heartbeat_at=registered_at,
            ttl_seconds=_TEST_CONNECTION_TTL_SECONDS,
            metadata={
                "runner_id": registration.runner_id,
                "protocol_version": registration.protocol_version,
                "capabilities": list(registration.capabilities.values),
                "health": registration.health,
                "workspace_path": registration.workspace_path,
                "auth_credential_id": registration.auth_credential_id,
                "metadata": registration.metadata,
            },
        )
        observer = self._runner_generation_observer
        if previous is not None and observer is not None:
            await observer.on_runner_replaced(
                runtime_id=registration.runtime_id,
                previous_generation=previous.generation,
                generation=record.generation,
            )
        return RuntimeRunnerRegistrationAccepted(
            runtime_id=registration.runtime_id,
            runner_id=registration.runner_id,
            connection_id=registration.connection_id,
            generation=record.generation,
            heartbeat_interval_seconds=_TEST_HEARTBEAT_INTERVAL_SECONDS,
        )


class FakeRuntimeConnectionRegistrar:
    """Provider and Runner registrar test double backed by one volatile store."""

    def __init__(
        self,
        store: RuntimeCoordinationStore,
        *,
        provider_connection_tracker: _RuntimeProviderConnectionTracker | None = None,
    ) -> None:
        self.control = FakeRuntimeControlProtocolService(store)
        self.provider_connection_tracker = provider_connection_tracker

    async def register_provider(
        self,
        registration: RuntimeProviderRegistration,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        registered_at: datetime,
    ) -> RuntimeProviderRegistrationAccepted:
        """Register a Provider while ignoring durable test authentication."""
        accepted = await self.control.register_provider(
            registration,
            registered_at=registered_at,
        )
        if self.provider_connection_tracker is not None:
            await self.provider_connection_tracker.create_connection(
                authentication=authentication,
                connection_id=accepted.connection_id,
                generation=accepted.generation,
                reported_provider_type=registration.provider_type,
                reported_protocol_version=registration.protocol_version,
                operational_diagnostics=registration.operational_diagnostics,
                connected_at=registered_at,
            )
        return accepted

    async def register_runner(
        self,
        registration: RuntimeRunnerRegistration,
        *,
        authentication: RuntimeRunnerCredential,
        registered_at: datetime,
    ) -> RuntimeRunnerRegistrationAccepted:
        """Register a Runner while ignoring durable test authentication."""
        del authentication
        return await self.control.register_runner(
            registration,
            registered_at=registered_at,
        )
