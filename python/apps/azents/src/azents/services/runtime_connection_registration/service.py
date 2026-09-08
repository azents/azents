"""Durable-to-volatile Runtime connection registration orchestration."""

import asyncio
import dataclasses
import logging
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from azents_runtime_control.provider import RuntimeProviderOperationalDiagnostics
from azents_runtime_control.transfer import (
    RUNNER_TRANSFER_CAPABILITY,
    RUNNER_TRANSFER_PROTOCOL_VERSION,
)
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import RuntimeConnectionAuthorityKind
from azents.core.runtime_runner_credential import RuntimeRunnerCredential
from azents.rdb.session import SessionManager
from azents.repos.runtime_connection_generation.data import (
    RuntimeConnectionGeneration,
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
from azents.services.runtime_provider_control.data import (
    RuntimeProviderCredentialAuthentication,
)

from .data import RuntimeConnectionRegistrationUnavailable

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


class RuntimeConnectionGenerationAuthority(Protocol):
    async def allocate_generation(
        self,
        session: AsyncSession,
        *,
        connection_kind: RuntimeConnectionAuthorityKind,
        subject_id: str,
    ) -> RuntimeConnectionGeneration:
        """Allocate the next durable generation."""
        ...

    async def generation_is_current_high_water(
        self,
        session: AsyncSession,
        *,
        connection_kind: RuntimeConnectionAuthorityKind,
        subject_id: str,
        generation: int,
    ) -> bool:
        """Return whether one generation remains current."""
        ...

    async def accept_generation(
        self,
        session: AsyncSession,
        *,
        connection_kind: RuntimeConnectionAuthorityKind,
        subject_id: str,
        generation: int,
    ) -> RuntimeConnectionGeneration | None:
        """Accept one current high-water generation."""
        ...


class RuntimeProviderConnectionAuthority(Protocol):
    async def validate_connection_authority_in_transaction(
        self,
        session: AsyncSession,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        validated_at: datetime,
    ) -> None:
        """Validate Provider authority inside a caller-owned transaction."""
        ...

    async def create_connection_in_transaction(
        self,
        session: AsyncSession,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        connection_id: str,
        generation: int,
        reported_provider_type: str,
        reported_protocol_version: str,
        operational_diagnostics: RuntimeProviderOperationalDiagnostics | None,
        authorized_at: datetime,
        connected_at: datetime,
    ) -> object:
        """Persist Provider acceptance inside a caller-owned transaction."""
        ...


class RuntimeRunnerConnectionAuthority(Protocol):
    async def authorize_runner_in_transaction(
        self,
        session: AsyncSession,
        credential: RuntimeRunnerCredential,
    ) -> bool:
        """Validate Runner authority inside a caller-owned transaction."""
        ...


@dataclasses.dataclass(frozen=True)
class RuntimeProviderConnectionRegistrationService:
    """Register Provider connections across durable and volatile authority."""

    session_manager: SessionManager[AsyncSession]
    generation_repository: RuntimeConnectionGenerationAuthority
    coordination_store: RuntimeCoordinationStore
    provider_control: RuntimeProviderConnectionAuthority
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
        async with self.session_manager() as session:
            if not await self.generation_repository.generation_is_current_high_water(
                session,
                connection_kind=RuntimeConnectionAuthorityKind.PROVIDER,
                subject_id=authentication.provider_resource_id,
                generation=generation,
            ):
                raise RuntimeConnectionRegistrationUnavailable("superseded")
            await self.provider_control.validate_connection_authority_in_transaction(
                session,
                authentication=authentication,
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
            async with self.session_manager() as session:
                accepted = await self.generation_repository.accept_generation(
                    session,
                    connection_kind=RuntimeConnectionAuthorityKind.PROVIDER,
                    subject_id=authentication.provider_resource_id,
                    generation=generation,
                )
                if accepted is None:
                    raise RuntimeConnectionRegistrationUnavailable("superseded")
                await self.provider_control.create_connection_in_transaction(
                    session,
                    authentication=authentication,
                    connection_id=registration.connection_id,
                    generation=generation,
                    reported_provider_type=registration.provider_type,
                    reported_protocol_version=registration.protocol_version,
                    operational_diagnostics=registration.operational_diagnostics,
                    authorized_at=self.clock(),
                    connected_at=registered_at,
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
                kind=record.kind,
                subject_id=record.subject_id,
                generation=generation,
            )
            raise

        return RuntimeProviderRegistrationAccepted(
            provider_id=registration.provider_id,
            connection_id=registration.connection_id,
            generation=generation,
            heartbeat_interval_seconds=self.heartbeat_interval_seconds,
        )

    async def _allocate(self, subject_id: str) -> int:
        async with self.session_manager() as session:
            state = await self.generation_repository.allocate_generation(
                session,
                connection_kind=RuntimeConnectionAuthorityKind.PROVIDER,
                subject_id=subject_id,
            )
        return state.high_water_generation


@dataclasses.dataclass(frozen=True)
class RuntimeRunnerConnectionRegistrationService:
    """Register Runner connections across durable and volatile authority."""

    session_manager: SessionManager[AsyncSession]
    generation_repository: RuntimeConnectionGenerationAuthority
    coordination_store: RuntimeCoordinationStore
    runner_authentication: RuntimeRunnerConnectionAuthority
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
        async with self.session_manager() as session:
            if not await self.generation_repository.generation_is_current_high_water(
                session,
                connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
                subject_id=registration.runtime_id,
                generation=generation,
            ):
                raise RuntimeConnectionRegistrationUnavailable("superseded")
            if not await self.runner_authentication.authorize_runner_in_transaction(
                session,
                authentication,
            ):
                raise RuntimeConnectionRegistrationUnavailable("authority_changed")

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
            async with self.session_manager() as session:
                if not await self.runner_authentication.authorize_runner_in_transaction(
                    session,
                    authentication,
                ):
                    raise RuntimeConnectionRegistrationUnavailable("authority_changed")
                accepted = await self.generation_repository.accept_generation(
                    session,
                    connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
                    subject_id=registration.runtime_id,
                    generation=generation,
                )
                if accepted is None:
                    raise RuntimeConnectionRegistrationUnavailable("superseded")
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
                kind=record.kind,
                subject_id=record.subject_id,
                generation=generation,
            )
            raise

        previous = promotion.previous_connection
        if (
            previous is not None
            and previous.generation != generation
            and self.generation_observer is not None
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
        async with self.session_manager() as session:
            state = await self.generation_repository.allocate_generation(
                session,
                connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
                subject_id=subject_id,
            )
        return state.high_water_generation
