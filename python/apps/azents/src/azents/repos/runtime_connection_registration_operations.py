"""Completed generation allocation, observation and atomic registration acceptance."""

import dataclasses
from datetime import datetime
from typing import Protocol

from azents_runtime_control.provider import RuntimeProviderOperationalDiagnostics

from azents.core.enums import RuntimeConnectionAuthorityKind
from azents.core.runtime_connection_registration import (
    RuntimeConnectionRegistrationUnavailable,
)
from azents.core.runtime_provider_control import RuntimeProviderCredentialAuthentication
from azents.core.runtime_runner_credential import RuntimeRunnerCredential
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.runtime_connection_generation.data import RuntimeConnectionGeneration
from azents.runtime.control_protocol.data import (
    RuntimeProviderRegistration,
    RuntimeRunnerRegistration,
)


class RuntimeConnectionGenerationAuthority(Protocol):
    async def allocate_generation(
        self,
        session: WriteSession,
        *,
        connection_kind: RuntimeConnectionAuthorityKind,
        subject_id: str,
    ) -> RuntimeConnectionGeneration:
        """Allocate the next durable generation."""
        ...

    async def generation_is_current_high_water(
        self,
        session: ReadSession,
        *,
        connection_kind: RuntimeConnectionAuthorityKind,
        subject_id: str,
        generation: int,
    ) -> bool:
        """Return whether one generation remains current."""
        ...

    async def accept_generation(
        self,
        session: WriteSession,
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
        session: ReadSession,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        validated_at: datetime,
    ) -> None:
        """Validate Provider authority inside a caller-owned transaction."""
        ...

    async def create_connection_in_transaction(
        self,
        session: WriteSession,
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
        self, session: ReadSession, credential: RuntimeRunnerCredential
    ) -> bool:
        """Validate Runner authority inside a caller-owned transaction."""
        ...

    async def fence_runner_registration_in_transaction(
        self, session: WriteSession, credential: RuntimeRunnerCredential
    ) -> bool:
        """Validate Runner authority inside a caller-owned transaction."""
        ...


@dataclasses.dataclass(frozen=True)
class RuntimeProviderConnectionRegistrationOperationRepository:
    """Register Provider connections across durable and volatile authority."""

    session_manager: SessionManager[WriteSession]
    read_session_manager: SessionManager[ReadSession]
    generation_repository: RuntimeConnectionGenerationAuthority
    provider_control: RuntimeProviderConnectionAuthority

    async def allocate(self, subject_id: str) -> int:
        async with self.session_manager() as session:
            state = await self.generation_repository.allocate_generation(
                session,
                connection_kind=RuntimeConnectionAuthorityKind.PROVIDER,
                subject_id=subject_id,
            )
        return state.high_water_generation

    async def observe(
        self,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        generation: int,
        validated_at: datetime,
    ) -> None:
        async with self.read_session_manager() as session:
            if not await self.generation_repository.generation_is_current_high_water(
                session,
                connection_kind=RuntimeConnectionAuthorityKind.PROVIDER,
                subject_id=authentication.provider_resource_id,
                generation=generation,
            ):
                raise RuntimeConnectionRegistrationUnavailable("superseded")
            await self.provider_control.validate_connection_authority_in_transaction(
                session, authentication=authentication, validated_at=validated_at
            )

    async def accept(
        self,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        generation: int,
        registration: RuntimeProviderRegistration,
        authorized_at: datetime,
        registered_at: datetime,
    ) -> None:
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
                authorized_at=authorized_at,
                connected_at=registered_at,
            )


@dataclasses.dataclass(frozen=True)
class RuntimeRunnerConnectionRegistrationOperationRepository:
    """Register Runner connections across durable and volatile authority."""

    session_manager: SessionManager[WriteSession]
    read_session_manager: SessionManager[ReadSession]
    generation_repository: RuntimeConnectionGenerationAuthority
    runner_authentication: RuntimeRunnerConnectionAuthority

    async def allocate(self, subject_id: str) -> int:
        async with self.session_manager() as session:
            state = await self.generation_repository.allocate_generation(
                session,
                connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
                subject_id=subject_id,
            )
        return state.high_water_generation

    async def observe(
        self,
        *,
        authentication: RuntimeRunnerCredential,
        generation: int,
        registration: RuntimeRunnerRegistration,
    ) -> None:
        async with self.read_session_manager() as session:
            if not await self.generation_repository.generation_is_current_high_water(
                session,
                connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
                subject_id=registration.runtime_id,
                generation=generation,
            ):
                raise RuntimeConnectionRegistrationUnavailable("superseded")
            if not await self.runner_authentication.authorize_runner_in_transaction(
                session, authentication
            ):
                raise RuntimeConnectionRegistrationUnavailable("authority_changed")

    async def accept(
        self,
        *,
        authentication: RuntimeRunnerCredential,
        generation: int,
        registration: RuntimeRunnerRegistration,
    ) -> None:
        async with self.session_manager() as session:
            fence_registration = (
                self.runner_authentication.fence_runner_registration_in_transaction
            )
            if not await fence_registration(session, authentication):
                raise RuntimeConnectionRegistrationUnavailable("authority_changed")
            accepted = await self.generation_repository.accept_generation(
                session,
                connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
                subject_id=registration.runtime_id,
                generation=generation,
            )
            if accepted is None:
                raise RuntimeConnectionRegistrationUnavailable("superseded")
