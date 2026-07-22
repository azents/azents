"""Runtime Provider Control persistence tests."""

import datetime

from azcommon.datetime import tznow
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBootstrapAdapterKind,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.repos.runtime_provider.data import (
    RuntimeProviderBootstrapSourceCreate,
    RuntimeProviderCreate,
)
from azents.repos.runtime_provider.repository import RuntimeProviderRepository

from .data import (
    RuntimeProviderConnectionCreate,
    RuntimeProviderCredentialCreate,
    RuntimeProviderEnrollmentGrantCreate,
)
from .repository import RuntimeProviderControlRepository


async def _provider_and_source(
    session: AsyncSession,
) -> tuple[str, str]:
    """Create a durable Provider and authorized bootstrap grant issuer."""
    provider_repository = RuntimeProviderRepository()
    provider = await provider_repository.create(
        session,
        RuntimeProviderCreate(
            provider_id="provider-control-test",
            scope=RuntimeProviderScope.SYSTEM,
            workspace_id=None,
            kind=RuntimeProviderKind.DOCKER,
            display_name="Provider Control Test",
            registration_method=RuntimeProviderRegistrationMethod.BOOTSTRAP,
            enabled=True,
            lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
            availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
            capabilities={},
            config_schema=None,
            metadata=None,
        ),
    )
    source = await provider_repository.get_or_create_bootstrap_source(
        session,
        create=RuntimeProviderBootstrapSourceCreate(
            source_key="provider-control-test-source",
            adapter_kind=RuntimeProviderBootstrapAdapterKind.HELM_FILE,
        ),
    )
    return provider.id, source.id


class TestRuntimeProviderControlRepository:
    """Verify durable one-time enrollment and connection fencing."""

    async def test_grant_consumes_once_and_persists_credential(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A grant creates exactly one credential even after replay."""
        repository = RuntimeProviderControlRepository()
        provider_id, source_id = await _provider_and_source(rdb_session)
        now = tznow()
        grant = await repository.create_enrollment_grant(
            rdb_session,
            create=RuntimeProviderEnrollmentGrantCreate(
                provider_id=provider_id,
                verifier="grant-verifier",
                expires_at=now + datetime.timedelta(minutes=5),
                issued_by_user_id=None,
                issued_by_source_id=source_id,
            ),
        )

        credential = await repository.create_credential_and_consume_grant(
            rdb_session,
            grant_id=grant.id,
            credential=RuntimeProviderCredentialCreate(
                provider_id=provider_id,
                verifier="credential-verifier",
                expires_at=None,
                issued_grant_id=grant.id,
            ),
            consumed_at=now,
        )
        replay = await repository.create_credential_and_consume_grant(
            rdb_session,
            grant_id=grant.id,
            credential=RuntimeProviderCredentialCreate(
                provider_id=provider_id,
                verifier="replay-verifier",
                expires_at=None,
                issued_grant_id=grant.id,
            ),
            consumed_at=now,
        )
        consumed = await repository.get_enrollment_grant_for_update(
            rdb_session,
            grant_id=grant.id,
        )

        assert credential is not None
        assert replay is None
        assert consumed is not None
        assert consumed.consumed_credential_id == credential.id
        assert consumed.consumed_at == now

    async def test_revoked_credential_cannot_heartbeat_connection(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Credential revocation immediately prevents connection heartbeat."""
        repository = RuntimeProviderControlRepository()
        provider_id, source_id = await _provider_and_source(rdb_session)
        now = tznow()
        grant = await repository.create_enrollment_grant(
            rdb_session,
            create=RuntimeProviderEnrollmentGrantCreate(
                provider_id=provider_id,
                verifier="grant-verifier",
                expires_at=now + datetime.timedelta(minutes=5),
                issued_by_user_id=None,
                issued_by_source_id=source_id,
            ),
        )
        credential = await repository.create_credential_and_consume_grant(
            rdb_session,
            grant_id=grant.id,
            credential=RuntimeProviderCredentialCreate(
                provider_id=provider_id,
                verifier="credential-verifier",
                expires_at=None,
                issued_grant_id=grant.id,
            ),
            consumed_at=now,
        )
        assert credential is not None
        connection = await repository.create_connection(
            rdb_session,
            create=RuntimeProviderConnectionCreate(
                provider_id=provider_id,
                credential_id=credential.id,
                connection_id="provider-control-test-connection",
                generation=1,
                reported_provider_type="docker",
                reported_protocol_version="test-v1",
                connected_at=now,
            ),
        )

        assert await repository.heartbeat_connection(
            rdb_session,
            provider_id=provider_id,
            credential_id=credential.id,
            generation=connection.generation,
            heartbeat_at=now + datetime.timedelta(seconds=1),
        )
        assert await repository.revoke_credential(
            rdb_session,
            credential_id=credential.id,
            revoked_at=now + datetime.timedelta(seconds=2),
            revoked_by_user_id=None,
        )
        assert not await repository.heartbeat_connection(
            rdb_session,
            provider_id=provider_id,
            credential_id=credential.id,
            generation=connection.generation,
            heartbeat_at=now + datetime.timedelta(seconds=3),
        )
        assert await repository.disconnect_connection(
            rdb_session,
            provider_id=provider_id,
            credential_id=credential.id,
            generation=connection.generation,
            disconnected_at=now + datetime.timedelta(seconds=4),
        )
