"""Runtime Provider control persistence repository."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderBindingState,
    RuntimeProviderConnectionStatus,
    RuntimeProviderCredentialState,
    RuntimeProviderEnrollmentGrantState,
    RuntimeProviderLifecycleState,
)
from azents.rdb.models.runtime_provider import RDBRuntimeProvider
from azents.rdb.models.runtime_provider_binding import (
    RDBRuntimeProviderAuthBinding,
)
from azents.rdb.models.runtime_provider_control import (
    RDBRuntimeProviderConnection,
    RDBRuntimeProviderCredential,
    RDBRuntimeProviderEnrollmentGrant,
)

from .data import (
    RuntimeProviderConnection,
    RuntimeProviderConnectionCreate,
    RuntimeProviderCredential,
    RuntimeProviderCredentialCreate,
    RuntimeProviderEnrollmentGrant,
    RuntimeProviderEnrollmentGrantCreate,
)

_TERMINAL_PROVIDER_STATES = frozenset(
    {
        RuntimeProviderLifecycleState.DECOMMISSIONED,
        RuntimeProviderLifecycleState.FORCE_RETIRED,
    }
)


def _active_connection_binding() -> sa.ColumnElement[bool]:
    """Require the connection's exact binding snapshot to remain active."""
    return sa.exists(
        sa.select(RDBRuntimeProviderAuthBinding.id).where(
            RDBRuntimeProviderAuthBinding.id == RDBRuntimeProviderConnection.binding_id,
            RDBRuntimeProviderAuthBinding.provider_id
            == RDBRuntimeProviderConnection.provider_id,
            RDBRuntimeProviderAuthBinding.auth_method
            == RDBRuntimeProviderConnection.auth_method,
            RDBRuntimeProviderAuthBinding.subject
            == RDBRuntimeProviderConnection.auth_subject,
            RDBRuntimeProviderAuthBinding.state == RuntimeProviderBindingState.ACTIVE,
        )
    )


def _active_connection_provider() -> sa.ColumnElement[bool]:
    """Require the bound Provider to remain non-terminal."""
    return sa.exists(
        sa.select(RDBRuntimeProvider.id).where(
            RDBRuntimeProvider.id == RDBRuntimeProviderConnection.provider_id,
            RDBRuntimeProvider.lifecycle_state.not_in(_TERMINAL_PROVIDER_STATES),
        )
    )


class RuntimeProviderControlRepository:
    """Persist enrollment, credential, and connection state for known Providers."""

    async def create_enrollment_grant(
        self,
        session: AsyncSession,
        *,
        create: RuntimeProviderEnrollmentGrantCreate,
    ) -> RuntimeProviderEnrollmentGrant:
        """Issue one verifier-backed enrollment grant."""
        grant = RDBRuntimeProviderEnrollmentGrant(
            provider_id=create.provider_id,
            binding_id=create.binding_id,
            verifier=create.verifier,
            state=RuntimeProviderEnrollmentGrantState.ISSUED,
            expires_at=create.expires_at,
            issued_by_user_id=create.issued_by_user_id,
            issued_by_source_id=create.issued_by_source_id,
        )
        session.add(grant)
        await session.flush()
        return self._build_grant(grant)

    async def get_enrollment_grant_for_update(
        self,
        session: AsyncSession,
        *,
        grant_id: str,
    ) -> RuntimeProviderEnrollmentGrant | None:
        """Lock one grant so a service can verify and consume it atomically."""
        result = await session.execute(
            sa.select(RDBRuntimeProviderEnrollmentGrant)
            .where(RDBRuntimeProviderEnrollmentGrant.id == grant_id)
            .with_for_update()
        )
        grant = result.scalar_one_or_none()
        return self._build_grant(grant) if grant is not None else None

    async def create_credential_and_consume_grant(
        self,
        session: AsyncSession,
        *,
        grant_id: str,
        credential: RuntimeProviderCredentialCreate,
        consumed_at: datetime.datetime,
    ) -> RuntimeProviderCredential | None:
        """Consume a locked issued grant and create its Provider credential."""
        result = await session.execute(
            sa.update(RDBRuntimeProviderEnrollmentGrant)
            .where(
                RDBRuntimeProviderEnrollmentGrant.id == grant_id,
                RDBRuntimeProviderEnrollmentGrant.state
                == RuntimeProviderEnrollmentGrantState.ISSUED,
                RDBRuntimeProviderEnrollmentGrant.consumed_at.is_(None),
            )
            .values(
                state=RuntimeProviderEnrollmentGrantState.CONSUMED,
                consumed_at=consumed_at,
            )
            .returning(RDBRuntimeProviderEnrollmentGrant)
        )
        grant = result.scalar_one_or_none()
        if grant is None:
            return None
        rdb = RDBRuntimeProviderCredential(
            provider_id=credential.provider_id,
            binding_id=credential.binding_id,
            verifier=credential.verifier,
            state=RuntimeProviderCredentialState.ACTIVE,
            expires_at=credential.expires_at,
            issued_grant_id=credential.issued_grant_id,
        )
        session.add(rdb)
        await session.flush()
        grant.consumed_credential_id = rdb.id
        await session.flush()
        return self._build_credential(rdb)

    async def get_active_credential_by_verifier(
        self,
        session: AsyncSession,
        *,
        verifier: str,
        now: datetime.datetime,
    ) -> RuntimeProviderCredential | None:
        """Return one active unexpired credential matching a verifier."""
        result = await session.execute(
            sa.select(RDBRuntimeProviderCredential).where(
                RDBRuntimeProviderCredential.verifier == verifier,
                RDBRuntimeProviderCredential.state
                == RuntimeProviderCredentialState.ACTIVE,
                sa.or_(
                    RDBRuntimeProviderCredential.expires_at.is_(None),
                    RDBRuntimeProviderCredential.expires_at > now,
                ),
            )
        )
        credential = result.scalar_one_or_none()
        return self._build_credential(credential) if credential is not None else None

    async def mark_credential_used(
        self,
        session: AsyncSession,
        *,
        credential_id: str,
        used_at: datetime.datetime,
    ) -> bool:
        """Mark one active credential as used, unless it was revoked concurrently."""
        result = await session.execute(
            sa.update(RDBRuntimeProviderCredential)
            .where(
                RDBRuntimeProviderCredential.id == credential_id,
                RDBRuntimeProviderCredential.state
                == RuntimeProviderCredentialState.ACTIVE,
                sa.or_(
                    RDBRuntimeProviderCredential.expires_at.is_(None),
                    RDBRuntimeProviderCredential.expires_at > used_at,
                ),
            )
            .values(last_used_at=used_at)
            .returning(RDBRuntimeProviderCredential.id)
        )
        return result.scalar_one_or_none() is not None

    async def revoke_older_bootstrap_credentials(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        current_credential_id: str,
        revoked_at: datetime.datetime,
    ) -> tuple[RuntimeProviderCredential, ...]:
        """Revoke older credentials from the current credential's bootstrap source."""
        current_result = await session.execute(
            sa.select(
                RDBRuntimeProviderCredential.created_at,
                RDBRuntimeProviderEnrollmentGrant.issued_by_source_id,
            )
            .join(
                RDBRuntimeProviderEnrollmentGrant,
                RDBRuntimeProviderEnrollmentGrant.id
                == RDBRuntimeProviderCredential.issued_grant_id,
            )
            .where(
                RDBRuntimeProviderCredential.provider_id == provider_id,
                RDBRuntimeProviderCredential.id == current_credential_id,
            )
        )
        current = current_result.one_or_none()
        if current is None or current.issued_by_source_id is None:
            return ()
        bootstrap_grant_ids = sa.select(RDBRuntimeProviderEnrollmentGrant.id).where(
            RDBRuntimeProviderEnrollmentGrant.issued_by_source_id
            == current.issued_by_source_id
        )
        revoked_result = await session.execute(
            sa.update(RDBRuntimeProviderCredential)
            .where(
                RDBRuntimeProviderCredential.provider_id == provider_id,
                RDBRuntimeProviderCredential.id != current_credential_id,
                RDBRuntimeProviderCredential.state
                == RuntimeProviderCredentialState.ACTIVE,
                sa.or_(
                    RDBRuntimeProviderCredential.created_at < current.created_at,
                    sa.and_(
                        RDBRuntimeProviderCredential.created_at == current.created_at,
                        RDBRuntimeProviderCredential.id < current_credential_id,
                    ),
                ),
                RDBRuntimeProviderCredential.issued_grant_id.in_(bootstrap_grant_ids),
            )
            .values(
                state=RuntimeProviderCredentialState.REVOKED,
                revoked_at=revoked_at,
                revoked_by_user_id=None,
            )
            .returning(RDBRuntimeProviderCredential)
        )
        revoked = tuple(revoked_result.scalars())
        if revoked:
            await session.execute(
                sa.update(RDBRuntimeProviderConnection)
                .where(
                    RDBRuntimeProviderConnection.credential_id.in_(
                        tuple(credential.id for credential in revoked)
                    ),
                    RDBRuntimeProviderConnection.status
                    == RuntimeProviderConnectionStatus.CONNECTED,
                )
                .values(
                    status=RuntimeProviderConnectionStatus.DISCONNECTED,
                    disconnected_at=revoked_at,
                )
            )
        return tuple(self._build_credential(credential) for credential in revoked)

    async def revoke_credential(
        self,
        session: AsyncSession,
        *,
        credential_id: str,
        revoked_at: datetime.datetime,
        revoked_by_user_id: str | None,
    ) -> RuntimeProviderCredential | None:
        """Revoke one active credential without invalidating audit history."""
        result = await session.execute(
            sa.update(RDBRuntimeProviderCredential)
            .where(
                RDBRuntimeProviderCredential.id == credential_id,
                RDBRuntimeProviderCredential.state
                == RuntimeProviderCredentialState.ACTIVE,
            )
            .values(
                state=RuntimeProviderCredentialState.REVOKED,
                revoked_at=revoked_at,
                revoked_by_user_id=revoked_by_user_id,
            )
            .returning(RDBRuntimeProviderCredential)
        )
        credential = result.scalar_one_or_none()
        if credential is not None:
            await session.execute(
                sa.update(RDBRuntimeProviderConnection)
                .where(
                    RDBRuntimeProviderConnection.credential_id == credential_id,
                    RDBRuntimeProviderConnection.status
                    == RuntimeProviderConnectionStatus.CONNECTED,
                )
                .values(
                    status=RuntimeProviderConnectionStatus.DISCONNECTED,
                    disconnected_at=revoked_at,
                )
            )
        return self._build_credential(credential) if credential is not None else None

    async def create_connection(
        self,
        session: AsyncSession,
        *,
        create: RuntimeProviderConnectionCreate,
    ) -> RuntimeProviderConnection:
        """Record one authenticated Provider Control stream connection."""
        await session.execute(
            sa.update(RDBRuntimeProviderConnection)
            .where(
                RDBRuntimeProviderConnection.provider_id == create.provider_id,
                RDBRuntimeProviderConnection.status
                == RuntimeProviderConnectionStatus.CONNECTED,
            )
            .values(
                status=RuntimeProviderConnectionStatus.DISCONNECTED,
                disconnected_at=create.connected_at,
            )
        )
        rdb = RDBRuntimeProviderConnection(
            provider_id=create.provider_id,
            binding_id=create.binding_id,
            credential_id=create.credential_id,
            auth_method=create.auth_method,
            auth_subject=create.auth_subject,
            evidence_expires_at=create.evidence_expires_at,
            connection_id=create.connection_id,
            generation=create.generation,
            status=RuntimeProviderConnectionStatus.CONNECTED,
            reported_provider_type=create.reported_provider_type,
            reported_protocol_version=create.reported_protocol_version,
            connected_at=create.connected_at,
            last_heartbeat_at=create.connected_at,
        )
        session.add(rdb)
        await session.flush()
        return self._build_connection(rdb)

    async def heartbeat_connection(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        binding_id: str,
        credential_id: str | None,
        generation: int,
        heartbeat_at: datetime.datetime,
        auth_method: RuntimeProviderAuthMethod,
        auth_subject: str,
    ) -> bool:
        """Refresh one current authenticated connection heartbeat."""
        result = await session.execute(
            sa.update(RDBRuntimeProviderConnection)
            .where(
                RDBRuntimeProviderConnection.provider_id == provider_id,
                RDBRuntimeProviderConnection.binding_id == binding_id,
                RDBRuntimeProviderConnection.credential_id == credential_id,
                RDBRuntimeProviderConnection.auth_method == auth_method,
                RDBRuntimeProviderConnection.auth_subject == auth_subject,
                RDBRuntimeProviderConnection.generation == generation,
                RDBRuntimeProviderConnection.status
                == RuntimeProviderConnectionStatus.CONNECTED,
                _active_connection_binding(),
                _active_connection_provider(),
                sa.or_(
                    RDBRuntimeProviderConnection.evidence_expires_at.is_(None),
                    RDBRuntimeProviderConnection.evidence_expires_at > heartbeat_at,
                ),
                sa.or_(
                    RDBRuntimeProviderConnection.credential_id.is_(None),
                    sa.exists(
                        sa.select(RDBRuntimeProviderCredential.id).where(
                            RDBRuntimeProviderCredential.id
                            == RDBRuntimeProviderConnection.credential_id,
                            RDBRuntimeProviderCredential.state
                            == RuntimeProviderCredentialState.ACTIVE,
                            sa.or_(
                                RDBRuntimeProviderCredential.expires_at.is_(None),
                                RDBRuntimeProviderCredential.expires_at > heartbeat_at,
                            ),
                        )
                    ),
                ),
            )
            .values(last_heartbeat_at=heartbeat_at)
            .returning(RDBRuntimeProviderConnection.id)
        )
        return result.scalar_one_or_none() is not None

    async def disconnect_connection(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        binding_id: str,
        credential_id: str | None,
        generation: int,
        disconnected_at: datetime.datetime,
        auth_method: RuntimeProviderAuthMethod,
        auth_subject: str,
    ) -> bool:
        """Disconnect only the authenticated current connection generation."""
        result = await session.execute(
            sa.update(RDBRuntimeProviderConnection)
            .where(
                RDBRuntimeProviderConnection.provider_id == provider_id,
                RDBRuntimeProviderConnection.binding_id == binding_id,
                RDBRuntimeProviderConnection.credential_id == credential_id,
                RDBRuntimeProviderConnection.auth_method == auth_method,
                RDBRuntimeProviderConnection.auth_subject == auth_subject,
                RDBRuntimeProviderConnection.generation == generation,
                RDBRuntimeProviderConnection.status
                == RuntimeProviderConnectionStatus.CONNECTED,
                _active_connection_binding(),
                _active_connection_provider(),
            )
            .values(
                status=RuntimeProviderConnectionStatus.DISCONNECTED,
                disconnected_at=disconnected_at,
            )
            .returning(RDBRuntimeProviderConnection.id)
        )
        return result.scalar_one_or_none() is not None

    async def connection_active(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        binding_id: str,
        credential_id: str | None,
        generation: int,
        now: datetime.datetime,
        auth_method: RuntimeProviderAuthMethod,
        auth_subject: str,
    ) -> bool:
        """Return whether a connection and its credential remain active."""
        result = await session.execute(
            sa.select(RDBRuntimeProviderConnection.id).where(
                RDBRuntimeProviderConnection.provider_id == provider_id,
                RDBRuntimeProviderConnection.binding_id == binding_id,
                RDBRuntimeProviderConnection.credential_id == credential_id,
                RDBRuntimeProviderConnection.auth_method == auth_method,
                RDBRuntimeProviderConnection.auth_subject == auth_subject,
                RDBRuntimeProviderConnection.generation == generation,
                RDBRuntimeProviderConnection.status
                == RuntimeProviderConnectionStatus.CONNECTED,
                _active_connection_binding(),
                _active_connection_provider(),
                sa.or_(
                    RDBRuntimeProviderConnection.evidence_expires_at.is_(None),
                    RDBRuntimeProviderConnection.evidence_expires_at > now,
                ),
                sa.or_(
                    RDBRuntimeProviderConnection.credential_id.is_(None),
                    sa.exists(
                        sa.select(RDBRuntimeProviderCredential.id).where(
                            RDBRuntimeProviderCredential.id == credential_id,
                            RDBRuntimeProviderCredential.state
                            == RuntimeProviderCredentialState.ACTIVE,
                            sa.or_(
                                RDBRuntimeProviderCredential.expires_at.is_(None),
                                RDBRuntimeProviderCredential.expires_at > now,
                            ),
                        )
                    ),
                ),
            )
        )
        return result.scalar_one_or_none() is not None

    async def has_connected_connection(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        now: datetime.datetime,
    ) -> bool:
        """Return whether one Provider retains current connection authority."""
        result = await session.execute(
            sa.select(RDBRuntimeProviderConnection.id).where(
                RDBRuntimeProviderConnection.provider_id == provider_id,
                RDBRuntimeProviderConnection.status
                == RuntimeProviderConnectionStatus.CONNECTED,
                _active_connection_binding(),
                _active_connection_provider(),
                sa.or_(
                    RDBRuntimeProviderConnection.evidence_expires_at.is_(None),
                    RDBRuntimeProviderConnection.evidence_expires_at > now,
                ),
                sa.or_(
                    RDBRuntimeProviderConnection.credential_id.is_(None),
                    sa.exists(
                        sa.select(RDBRuntimeProviderCredential.id).where(
                            RDBRuntimeProviderCredential.id
                            == RDBRuntimeProviderConnection.credential_id,
                            RDBRuntimeProviderCredential.state
                            == RuntimeProviderCredentialState.ACTIVE,
                            sa.or_(
                                RDBRuntimeProviderCredential.expires_at.is_(None),
                                RDBRuntimeProviderCredential.expires_at > now,
                            ),
                        )
                    ),
                ),
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    def _build_grant(
        rdb: RDBRuntimeProviderEnrollmentGrant,
    ) -> RuntimeProviderEnrollmentGrant:
        return RuntimeProviderEnrollmentGrant(
            id=rdb.id,
            provider_id=rdb.provider_id,
            verifier=rdb.verifier,
            state=rdb.state,
            expires_at=rdb.expires_at,
            issued_by_user_id=rdb.issued_by_user_id,
            issued_by_source_id=rdb.issued_by_source_id,
            consumed_at=rdb.consumed_at,
            consumed_credential_id=rdb.consumed_credential_id,
            revoked_at=rdb.revoked_at,
            revoked_by_user_id=rdb.revoked_by_user_id,
            created_at=rdb.created_at,
            binding_id=rdb.binding_id,
        )

    @staticmethod
    def _build_credential(
        rdb: RDBRuntimeProviderCredential,
    ) -> RuntimeProviderCredential:
        return RuntimeProviderCredential(
            id=rdb.id,
            provider_id=rdb.provider_id,
            verifier=rdb.verifier,
            state=rdb.state,
            expires_at=rdb.expires_at,
            issued_grant_id=rdb.issued_grant_id,
            last_used_at=rdb.last_used_at,
            revoked_at=rdb.revoked_at,
            revoked_by_user_id=rdb.revoked_by_user_id,
            created_at=rdb.created_at,
            binding_id=rdb.binding_id,
        )

    @staticmethod
    def _build_connection(
        rdb: RDBRuntimeProviderConnection,
    ) -> RuntimeProviderConnection:
        return RuntimeProviderConnection(
            id=rdb.id,
            provider_id=rdb.provider_id,
            binding_id=rdb.binding_id,
            credential_id=rdb.credential_id,
            auth_method=rdb.auth_method,
            auth_subject=rdb.auth_subject,
            evidence_expires_at=rdb.evidence_expires_at,
            connection_id=rdb.connection_id,
            generation=rdb.generation,
            status=rdb.status,
            reported_provider_type=rdb.reported_provider_type,
            reported_protocol_version=rdb.reported_protocol_version,
            connected_at=rdb.connected_at,
            last_heartbeat_at=rdb.last_heartbeat_at,
            disconnected_at=rdb.disconnected_at,
            created_at=rdb.created_at,
        )
