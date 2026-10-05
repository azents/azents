"""Provider enrollment and credential orchestration over completed operations."""

import dataclasses
import datetime

from azents_runtime_control.provider import RuntimeProviderOperationalDiagnostics

from azents.core.enums import RuntimeProviderAuthMethod
from azents.core.runtime_provider_control import (
    RuntimeProviderCredentialAuthentication,
    RuntimeProviderCredentialIssued,
    RuntimeProviderEnrollmentGrantIssued,
)
from azents.core.runtime_provider_credential import RuntimeProviderCredentialVerifier
from azents.repos.runtime_provider_control.data import RuntimeProviderConnection
from azents.repos.runtime_provider_control.operations import (
    RuntimeProviderControlOperationRepository,
)
from azents.services.runtime_provider_control.provider_auth import ProviderAuthRegistry


@dataclasses.dataclass(frozen=True)
class RuntimeProviderEnrollmentService:
    """Issue, exchange, and verify Provider-bound enrollment credentials."""

    operations: RuntimeProviderControlOperationRepository
    auth_registry: ProviderAuthRegistry
    verifier: RuntimeProviderCredentialVerifier

    async def issue_grant(
        self,
        *,
        provider_id: str,
        expires_at: datetime.datetime,
        issued_by_user_id: str | None,
        issued_by_source_id: str | None,
    ) -> RuntimeProviderEnrollmentGrantIssued:
        """Issue one plaintext enrollment secret for a known active Provider."""
        return await self.operations.issue_grant(
            provider_id=provider_id,
            expires_at=expires_at,
            issued_by_user_id=issued_by_user_id,
            issued_by_source_id=issued_by_source_id,
        )

    async def exchange_grant(
        self,
        *,
        grant_id: str,
        secret: str,
        credential_expires_at: datetime.datetime | None,
        source_address: str | None,
    ) -> RuntimeProviderCredentialIssued:
        """Consume one valid grant and return its Provider credential once."""
        return await self.operations.exchange_grant(
            grant_id=grant_id,
            secret=secret,
            credential_expires_at=credential_expires_at,
            source_address=source_address,
        )

    async def authenticate_credential(
        self, *, secret: str
    ) -> RuntimeProviderCredentialAuthentication:
        """Resolve issued evidence through the explicit verifier registry."""
        return await self.authenticate_provider(
            method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN, secret=secret
        )

    async def authenticate_provider(
        self, *, method: RuntimeProviderAuthMethod, secret: str
    ) -> RuntimeProviderCredentialAuthentication:
        """Authenticate exactly one selected Provider auth method."""
        return await self.auth_registry.verify(method=method, secret=secret)

    async def authenticate_kubernetes_service_account(
        self, *, secret: str
    ) -> RuntimeProviderCredentialAuthentication:
        """Authenticate a trusted Kubernetes Provider workload identity."""
        return await self.authenticate_provider(
            method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT, secret=secret
        )

    async def revoke_credential(
        self, *, credential_id: str, revoked_by_user_id: str | None
    ) -> bool:
        """Revoke one credential so it cannot establish or maintain a stream."""
        return await self.operations.revoke_credential(
            credential_id=credential_id, revoked_by_user_id=revoked_by_user_id
        )

    async def create_connection(
        self,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        connection_id: str,
        generation: int,
        reported_provider_type: str,
        reported_protocol_version: str,
        operational_diagnostics: RuntimeProviderOperationalDiagnostics | None,
        connected_at: datetime.datetime,
    ) -> RuntimeProviderConnection:
        """Persist an authenticated Provider stream after control registration."""
        return await self.operations.create_connection(
            authentication=authentication,
            connection_id=connection_id,
            generation=generation,
            reported_provider_type=reported_provider_type,
            reported_protocol_version=reported_protocol_version,
            operational_diagnostics=operational_diagnostics,
            connected_at=connected_at,
        )

    async def heartbeat_connection(
        self,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        generation: int,
        heartbeat_at: datetime.datetime,
        operational_diagnostics: RuntimeProviderOperationalDiagnostics | None,
    ) -> bool:
        """Refresh an authenticated connection after checking credential validity."""
        return await self.operations.heartbeat_connection(
            authentication=authentication,
            generation=generation,
            heartbeat_at=heartbeat_at,
            operational_diagnostics=operational_diagnostics,
        )

    async def connection_active(
        self,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        generation: int,
        now: datetime.datetime,
    ) -> bool:
        """Check command-delivery authority for an authenticated stream."""
        return await self.operations.connection_active(
            authentication=authentication, generation=generation, now=now
        )

    async def disconnect_connection(
        self,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        generation: int,
        disconnected_at: datetime.datetime,
    ) -> bool:
        """Persist closure of an authenticated Provider stream generation."""
        return await self.operations.disconnect_connection(
            authentication=authentication,
            generation=generation,
            disconnected_at=disconnected_at,
        )
