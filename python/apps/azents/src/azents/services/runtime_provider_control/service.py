"""Runtime Provider enrollment and credential authentication service."""

import dataclasses
import datetime

from azcommon.datetime import tznow
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAuditEventType,
    RuntimeProviderEnrollmentGrantState,
    RuntimeProviderLifecycleState,
)
from azents.core.runtime_provider_credential import RuntimeProviderCredentialVerifier
from azents.rdb.session import SessionManager
from azents.repos.runtime_provider.data import RuntimeProviderAuditEventCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_control.data import (
    RuntimeProviderConnection,
    RuntimeProviderConnectionCreate,
    RuntimeProviderCredentialCreate,
    RuntimeProviderEnrollmentGrantCreate,
)
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)

from .data import (
    RuntimeProviderCredentialAuthentication,
    RuntimeProviderCredentialIssued,
    RuntimeProviderCredentialUnavailable,
    RuntimeProviderEnrollmentGrantIssued,
    RuntimeProviderEnrollmentUnavailable,
)

_TERMINAL = frozenset(
    {
        RuntimeProviderLifecycleState.DECOMMISSIONED,
        RuntimeProviderLifecycleState.FORCE_RETIRED,
    }
)


@dataclasses.dataclass(frozen=True)
class RuntimeProviderEnrollmentService:
    """Issue, exchange, and verify Provider-bound enrollment credentials."""

    session_manager: SessionManager[AsyncSession]
    repository: RuntimeProviderControlRepository
    provider_repository: RuntimeProviderRepository
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
        if expires_at <= tznow():
            raise RuntimeProviderEnrollmentUnavailable("grant_expiry_invalid")
        if (issued_by_user_id is None) == (issued_by_source_id is None):
            raise RuntimeProviderEnrollmentUnavailable("grant_issuer_invalid")
        secret = self.verifier.issue_secret()
        async with self.session_manager() as session:
            provider = await self.provider_repository.get_by_id(
                session,
                provider_id=provider_id,
                for_update=True,
            )
            if provider is None or provider.lifecycle_state in _TERMINAL:
                raise RuntimeProviderEnrollmentUnavailable("provider_unavailable")
            grant = await self.repository.create_enrollment_grant(
                session,
                create=RuntimeProviderEnrollmentGrantCreate(
                    provider_id=provider_id,
                    verifier=self.verifier.verifier_for(secret),
                    expires_at=expires_at,
                    issued_by_user_id=issued_by_user_id,
                    issued_by_source_id=issued_by_source_id,
                ),
            )
            await self.provider_repository.append_audit_event(
                session,
                create=RuntimeProviderAuditEventCreate(
                    provider_id=provider.id,
                    event_type=RuntimeProviderAuditEventType.ENROLLMENT_GRANT_ISSUED,
                    actor_user_id=issued_by_user_id,
                    metadata={
                        "grant_id": grant.id,
                        "issuer": (
                            "user"
                            if issued_by_user_id is not None
                            else "bootstrap_source"
                        ),
                    },
                    created_at=tznow(),
                ),
            )
        return RuntimeProviderEnrollmentGrantIssued(
            grant_id=grant.id,
            provider_id=provider_id,
            secret=secret,
            expires_at=expires_at,
        )

    async def exchange_grant(
        self,
        *,
        grant_id: str,
        secret: str,
        credential_expires_at: datetime.datetime | None,
    ) -> RuntimeProviderCredentialIssued:
        """Consume one valid grant and return its Provider credential once."""
        now = tznow()
        credential_secret = self.verifier.issue_secret()
        async with self.session_manager() as session:
            grant = await self.repository.get_enrollment_grant_for_update(
                session,
                grant_id=grant_id,
            )
            if (
                grant is None
                or grant.state != RuntimeProviderEnrollmentGrantState.ISSUED
                or grant.expires_at <= now
                or not self.verifier.matches(secret, grant.verifier)
            ):
                raise RuntimeProviderEnrollmentUnavailable("grant_unavailable")
            provider = await self.provider_repository.get_by_id(
                session,
                provider_id=grant.provider_id,
                for_update=True,
            )
            if provider is None or provider.lifecycle_state in _TERMINAL:
                raise RuntimeProviderEnrollmentUnavailable("provider_unavailable")
            credential = await self.repository.create_credential_and_consume_grant(
                session,
                grant_id=grant.id,
                credential=RuntimeProviderCredentialCreate(
                    provider_id=grant.provider_id,
                    verifier=self.verifier.verifier_for(credential_secret),
                    expires_at=credential_expires_at,
                    issued_grant_id=grant.id,
                ),
                consumed_at=now,
            )
            if credential is None:
                raise RuntimeProviderEnrollmentUnavailable("grant_unavailable")
            await self.provider_repository.append_audit_event(
                session,
                create=RuntimeProviderAuditEventCreate(
                    provider_id=credential.provider_id,
                    event_type=RuntimeProviderAuditEventType.CREDENTIAL_ISSUED,
                    actor_user_id=None,
                    metadata={
                        "credential_id": credential.id,
                        "grant_id": grant.id,
                    },
                    created_at=now,
                ),
            )
        return RuntimeProviderCredentialIssued(
            credential_id=credential.id,
            provider_id=credential.provider_id,
            secret=credential_secret,
            expires_at=credential.expires_at,
        )

    async def authenticate_credential(
        self,
        *,
        secret: str,
    ) -> RuntimeProviderCredentialAuthentication:
        """Resolve active credential plaintext to its credential and Provider IDs."""
        now = tznow()
        async with self.session_manager() as session:
            credential = await self.repository.get_active_credential_by_verifier(
                session,
                verifier=self.verifier.verifier_for(secret),
                now=now,
            )
            if credential is None or not self.verifier.matches(
                secret,
                credential.verifier,
            ):
                raise RuntimeProviderCredentialUnavailable("credential_unavailable")
            provider = await self.provider_repository.get_by_id(
                session,
                provider_id=credential.provider_id,
                for_update=False,
            )
            if provider is None or provider.lifecycle_state in _TERMINAL:
                raise RuntimeProviderCredentialUnavailable("provider_unavailable")
            if not await self.repository.mark_credential_used(
                session,
                credential_id=credential.id,
                used_at=now,
            ):
                raise RuntimeProviderCredentialUnavailable("credential_unavailable")
        return RuntimeProviderCredentialAuthentication(
            credential_id=credential.id,
            provider_id=credential.provider_id,
            provider_kind=provider.kind,
            provider_scope=provider.scope,
            provider_workspace_id=provider.workspace_id,
        )

    async def revoke_credential(
        self,
        *,
        credential_id: str,
        revoked_by_user_id: str | None,
    ) -> bool:
        """Revoke one credential so it cannot establish or maintain a stream."""
        now = tznow()
        async with self.session_manager() as session:
            credential = await self.repository.revoke_credential(
                session,
                credential_id=credential_id,
                revoked_at=now,
                revoked_by_user_id=revoked_by_user_id,
            )
            if credential is None:
                return False
            await self.provider_repository.append_audit_event(
                session,
                create=RuntimeProviderAuditEventCreate(
                    provider_id=credential.provider_id,
                    event_type=RuntimeProviderAuditEventType.CREDENTIAL_REVOKED,
                    actor_user_id=revoked_by_user_id,
                    metadata={"credential_id": credential.id},
                    created_at=now,
                ),
            )
            return True

    async def create_connection(
        self,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        connection_id: str,
        generation: int,
        reported_provider_type: str,
        reported_protocol_version: str,
        connected_at: datetime.datetime,
    ) -> RuntimeProviderConnection:
        """Persist an authenticated Provider stream after control registration."""
        async with self.session_manager() as session:
            provider = await self.provider_repository.get_by_id(
                session,
                provider_id=authentication.provider_id,
                for_update=True,
            )
            if provider is None or provider.lifecycle_state in _TERMINAL:
                raise RuntimeProviderCredentialUnavailable("provider_unavailable")
            if not await self.repository.mark_credential_used(
                session,
                credential_id=authentication.credential_id,
                used_at=connected_at,
            ):
                raise RuntimeProviderCredentialUnavailable("credential_unavailable")
            connection = await self.repository.create_connection(
                session,
                create=RuntimeProviderConnectionCreate(
                    provider_id=authentication.provider_id,
                    credential_id=authentication.credential_id,
                    connection_id=connection_id,
                    generation=generation,
                    reported_provider_type=reported_provider_type,
                    reported_protocol_version=reported_protocol_version,
                    connected_at=connected_at,
                ),
            )
            await self.provider_repository.append_audit_event(
                session,
                create=RuntimeProviderAuditEventCreate(
                    provider_id=authentication.provider_id,
                    event_type=RuntimeProviderAuditEventType.CONNECTION_OPENED,
                    actor_user_id=None,
                    metadata={
                        "connection_id": connection.id,
                        "credential_id": authentication.credential_id,
                        "generation": generation,
                    },
                    created_at=connected_at,
                ),
            )
            return connection

    async def heartbeat_connection(
        self,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        generation: int,
        heartbeat_at: datetime.datetime,
    ) -> bool:
        """Refresh an authenticated connection after checking credential validity."""
        async with self.session_manager() as session:
            return await self.repository.heartbeat_connection(
                session,
                provider_id=authentication.provider_id,
                credential_id=authentication.credential_id,
                generation=generation,
                heartbeat_at=heartbeat_at,
            )

    async def disconnect_connection(
        self,
        *,
        authentication: RuntimeProviderCredentialAuthentication,
        generation: int,
        disconnected_at: datetime.datetime,
    ) -> bool:
        """Persist closure of an authenticated Provider stream generation."""
        async with self.session_manager() as session:
            disconnected = await self.repository.disconnect_connection(
                session,
                provider_id=authentication.provider_id,
                credential_id=authentication.credential_id,
                generation=generation,
                disconnected_at=disconnected_at,
            )
            if disconnected:
                await self.provider_repository.append_audit_event(
                    session,
                    create=RuntimeProviderAuditEventCreate(
                        provider_id=authentication.provider_id,
                        event_type=RuntimeProviderAuditEventType.CONNECTION_CLOSED,
                        actor_user_id=None,
                        metadata={
                            "credential_id": authentication.credential_id,
                            "generation": generation,
                        },
                        created_at=disconnected_at,
                    ),
                )
            return disconnected
