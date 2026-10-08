"""Durable-to-volatile Runtime connection registration orchestration."""

import asyncio
import dataclasses
import logging
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from azents_runtime_control.transfer import (
    RUNNER_TRANSFER_CAPABILITY,
    RUNNER_TRANSFER_PROTOCOL_VERSION,
)

from azents.core.runtime_connection_registration import (
    RuntimeConnectionRegistrationUnavailable,
)
from azents.core.runtime_provider_control import RuntimeProviderCredentialAuthentication
from azents.core.runtime_runner_credential import RuntimeRunnerCredential
from azents.repos.runtime_connection_registration_operations import (
    RuntimeProviderConnectionRegistrationOperationRepository,
    RuntimeRunnerConnectionRegistrationOperationRepository,
)
from azents.runtime.control_protocol.data import (
    RuntimeProviderRegistration,
    RuntimeProviderRegistrationAccepted,
    RuntimeRunnerRegistration,
    RuntimeRunnerRegistrationAccepted,
)
from azents.runtime.control_protocol.service import RuntimeRunnerGenerationObserver
from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeConnectionPromotionStatus,
    RuntimeConnectionRecord,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore

_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 20
_DEFAULT_CONNECTION_TTL_SECONDS = 60
_DEFAULT_CANDIDATE_TTL_SECONDS = 15
_LOGGER = logging.getLogger(__name__)


class RuntimeProviderConnectionRegistrar(Protocol):
    """Register one authenticated Provider stream."""

    async def register_provider(
        self,
        registration: RuntimeProviderRegistration,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        registered_at: datetime,
    ) -> RuntimeProviderRegistrationAccepted:
        """Allocate, publish, and durably accept one Provider generation."""
        ...


class RuntimeRunnerConnectionRegistrar(Protocol):
    """Register one authenticated Runner stream."""

    async def register_runner(
        self,
        registration: RuntimeRunnerRegistration,
        *,
        authentication: RuntimeRunnerCredential,
        registered_at: datetime,
    ) -> RuntimeRunnerRegistrationAccepted:
        """Allocate, publish, and durably accept one Runner generation."""
        ...


@dataclasses.dataclass(frozen=True)
class RuntimeProviderConnectionRegistrationService:
    """Register Provider connections across durable and volatile authority."""

    operations: RuntimeProviderConnectionRegistrationOperationRepository
    coordination_store: RuntimeCoordinationStore
    clock: Callable[[], datetime]
    heartbeat_interval_seconds: int = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    connection_ttl_seconds: int = _DEFAULT_CONNECTION_TTL_SECONDS
    candidate_ttl_seconds: int = _DEFAULT_CANDIDATE_TTL_SECONDS

    async def register_provider(
        self,
        registration: RuntimeProviderRegistration,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        registered_at: datetime,
    ) -> RuntimeProviderRegistrationAccepted:
        """Allocate, publish, and durably accept one Provider generation."""
        generation = await self._allocate(authentication.provider_resource_id)
        record = RuntimeConnectionRecord(
            kind=RuntimeConnectionKind.PROVIDER,
            subject_id=registration.provider_id,
            connection_id=registration.connection_id,
            owner_replica_id=registration.owner_replica_id,
            generation=generation,
            connected_at=registered_at,
            heartbeat_at=registered_at,
            expires_at=registered_at + timedelta(seconds=self.connection_ttl_seconds),
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
        token = secrets.token_urlsafe(32)
        staged = await self.coordination_store.stage_connection_candidate(
            record=record,
            publication_token=token,
            ttl_seconds=self.candidate_ttl_seconds,
        )
        if not staged:
            raise RuntimeConnectionRegistrationUnavailable("candidate_stage_rejected")
        await self.operations.observe(
            authentication=authentication,
            generation=generation,
            validated_at=self.clock(),
        )
        promotion = await self.coordination_store.promote_connection_candidate(
            kind=record.kind,
            subject_id=record.subject_id,
            generation=generation,
            publication_token=token,
            ttl_seconds=self.connection_ttl_seconds,
        )
        if (
            promotion.status is not RuntimeConnectionPromotionStatus.APPLIED
            or promotion.connection is None
        ):
            raise RuntimeConnectionRegistrationUnavailable(promotion.status.value)
        try:
            await self.operations.accept(
                authentication=authentication,
                generation=generation,
                registration=registration,
                authorized_at=self.clock(),
                registered_at=registered_at,
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self.coordination_store.revoke_connection(
                    kind=record.kind,
                    subject_id=record.subject_id,
                    generation=generation,
                )
            )
            raise
        except Exception:
            await self.coordination_store.revoke_connection(
                kind=record.kind, subject_id=record.subject_id, generation=generation
            )
            raise
        return RuntimeProviderRegistrationAccepted(
            provider_id=registration.provider_id,
            connection_id=registration.connection_id,
            generation=generation,
            heartbeat_interval_seconds=self.heartbeat_interval_seconds,
        )

    async def _allocate(self, subject_id: str) -> int:
        return await self.operations.allocate(subject_id)


@dataclasses.dataclass(frozen=True)
class RuntimeRunnerConnectionRegistrationService:
    """Register Runner connections across durable and volatile authority."""

    operations: RuntimeRunnerConnectionRegistrationOperationRepository
    coordination_store: RuntimeCoordinationStore
    generation_observer: RuntimeRunnerGenerationObserver | None
    heartbeat_interval_seconds: int = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    connection_ttl_seconds: int = _DEFAULT_CONNECTION_TTL_SECONDS
    candidate_ttl_seconds: int = _DEFAULT_CANDIDATE_TTL_SECONDS

    async def register_runner(
        self,
        registration: RuntimeRunnerRegistration,
        *,
        authentication: RuntimeRunnerCredential,
        registered_at: datetime,
    ) -> RuntimeRunnerRegistrationAccepted:
        """Allocate, publish, and durably accept one Runner generation."""
        if registration.protocol_version != RUNNER_TRANSFER_PROTOCOL_VERSION:
            raise ValueError("Runner protocol version is not supported")
        if RUNNER_TRANSFER_CAPABILITY not in registration.capabilities.values:
            raise ValueError("Runner transfer capability is required")
        generation = await self._allocate(registration.runtime_id)
        record = RuntimeConnectionRecord(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=registration.runtime_id,
            connection_id=registration.connection_id,
            owner_replica_id=registration.owner_replica_id,
            generation=generation,
            connected_at=registered_at,
            heartbeat_at=registered_at,
            expires_at=registered_at + timedelta(seconds=self.connection_ttl_seconds),
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
        token = secrets.token_urlsafe(32)
        staged = await self.coordination_store.stage_connection_candidate(
            record=record,
            publication_token=token,
            ttl_seconds=self.candidate_ttl_seconds,
        )
        if not staged:
            raise RuntimeConnectionRegistrationUnavailable("candidate_stage_rejected")
        await self.operations.observe(
            authentication=authentication,
            generation=generation,
            registration=registration,
        )
        promotion = await self.coordination_store.promote_connection_candidate(
            kind=record.kind,
            subject_id=record.subject_id,
            generation=generation,
            publication_token=token,
            ttl_seconds=self.connection_ttl_seconds,
        )
        if (
            promotion.status is not RuntimeConnectionPromotionStatus.APPLIED
            or promotion.connection is None
        ):
            raise RuntimeConnectionRegistrationUnavailable(promotion.status.value)
        try:
            await self.operations.accept(
                authentication=authentication,
                generation=generation,
                registration=registration,
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self.coordination_store.revoke_connection(
                    kind=record.kind,
                    subject_id=record.subject_id,
                    generation=generation,
                )
            )
            raise
        except Exception:
            await self.coordination_store.revoke_connection(
                kind=record.kind, subject_id=record.subject_id, generation=generation
            )
            raise
        previous = promotion.previous_connection
        if (
            previous is not None
            and previous.generation != generation
            and (self.generation_observer is not None)
        ):
            try:
                await self.generation_observer.on_runner_replaced(
                    runtime_id=registration.runtime_id,
                    previous_generation=previous.generation,
                    generation=generation,
                )
            except Exception:
                _LOGGER.exception(
                    "Runtime Runner replacement observer failed",
                    extra={
                        "runtime_id": registration.runtime_id,
                        "previous_generation": previous.generation,
                        "generation": generation,
                    },
                )
        return RuntimeRunnerRegistrationAccepted(
            runtime_id=registration.runtime_id,
            runner_id=registration.runner_id,
            connection_id=registration.connection_id,
            generation=generation,
            heartbeat_interval_seconds=self.heartbeat_interval_seconds,
        )

    async def _allocate(self, subject_id: str) -> int:
        return await self.operations.allocate(subject_id)
