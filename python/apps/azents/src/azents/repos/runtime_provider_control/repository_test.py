"""Runtime Provider Control persistence tests."""

import datetime

import sqlalchemy as sa
from azcommon.datetime import tznow
from azents_runtime_control.provider import (
    RuntimeProviderOperationalDiagnostics,
    RuntimeProviderOperationalWarning,
    RuntimeProviderOperationalWarningSeverity,
)
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBindingOwner,
    RuntimeProviderBootstrapAdapterKind,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.rdb.models.runtime_provider_control import RDBRuntimeProviderConnection
from azents.repos.runtime_provider.data import (
    RuntimeProviderBootstrapSourceCreate,
    RuntimeProviderCreate,
)
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_binding.data import (
    RuntimeProviderAuthBindingCreate,
    RuntimeProviderAuthBindingRevoke,
)
from azents.repos.runtime_provider_binding.repository import (
    RuntimeProviderAuthBindingRepository,
)

from .data import (
    RuntimeProviderConnectionCreate,
    RuntimeProviderCredentialCreate,
    RuntimeProviderEnrollmentGrantCreate,
)
from .repository import RuntimeProviderControlRepository


async def _provider_source_and_binding(
    session: AsyncSession,
) -> tuple[str, str, str]:
    """Create a durable Provider, bootstrap source, and issued-token binding."""
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
    binding = await RuntimeProviderAuthBindingRepository().create(
        session,
        create=RuntimeProviderAuthBindingCreate(
            provider_id=provider.id,
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            subject=f"admin:{provider.id}",
            owner=RuntimeProviderBindingOwner.ADMIN,
            bootstrap_declaration_id=None,
            config=None,
        ),
    )
    return provider.id, source.id, binding.id


class TestRuntimeProviderControlRepository:
    """Verify durable one-time enrollment and connection fencing."""

    async def test_grant_consumes_once_and_persists_credential(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A grant creates exactly one credential even after replay."""
        repository = RuntimeProviderControlRepository()
        provider_id, source_id, binding_id = await _provider_source_and_binding(
            rdb_session
        )
        now = tznow()
        grant = await repository.create_enrollment_grant(
            rdb_session,
            create=RuntimeProviderEnrollmentGrantCreate(
                provider_id=provider_id,
                binding_id=binding_id,
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
                binding_id=binding_id,
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
                binding_id=binding_id,
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

    async def test_connection_diagnostics_replace_only_on_active_generation(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A reconnect never inherits or permits updates to an older snapshot."""
        repository = RuntimeProviderControlRepository()
        provider_id, source_id, binding_id = await _provider_source_and_binding(
            rdb_session
        )
        auth_subject = f"admin:{provider_id}"
        now = tznow()
        grant = await repository.create_enrollment_grant(
            rdb_session,
            create=RuntimeProviderEnrollmentGrantCreate(
                provider_id=provider_id,
                binding_id=binding_id,
                verifier="diagnostics-grant-verifier",
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
                binding_id=binding_id,
                verifier="diagnostics-credential-verifier",
                expires_at=None,
                issued_grant_id=grant.id,
            ),
            consumed_at=now,
        )
        assert credential is not None
        initial = _diagnostics(
            checked_at=now,
            code="cni_support_unconfirmed",
        )
        first = await repository.create_connection(
            rdb_session,
            create=RuntimeProviderConnectionCreate(
                provider_id=provider_id,
                binding_id=binding_id,
                credential_id=credential.id,
                auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
                auth_subject=auth_subject,
                evidence_expires_at=None,
                connection_id="provider-diagnostics-connection-1",
                generation=1,
                reported_provider_type="kubernetes",
                reported_protocol_version="agent-runtime-provider-kubernetes-v3",
                operational_diagnostics=initial,
                connected_at=now,
            ),
        )
        replacement = _diagnostics(
            checked_at=now + datetime.timedelta(minutes=1),
            code="unexpected_network_policy",
        )

        assert await repository.heartbeat_connection(
            rdb_session,
            provider_id=provider_id,
            binding_id=binding_id,
            credential_id=credential.id,
            generation=first.generation,
            heartbeat_at=now + datetime.timedelta(minutes=1),
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            auth_subject=auth_subject,
            operational_diagnostics=replacement,
        )
        first_row = (
            await rdb_session.execute(
                sa.select(RDBRuntimeProviderConnection).where(
                    RDBRuntimeProviderConnection.id == first.id
                )
            )
        ).scalar_one()
        await rdb_session.refresh(first_row)
        assert first_row.diagnostics_checked_at == replacement.checked_at
        assert first_row.operational_diagnostics is not None
        warnings = first_row.operational_diagnostics["warnings"]
        assert isinstance(warnings, list)
        warning = warnings[0]
        assert isinstance(warning, dict)
        code = next(
            value
            for key, value in warning.items()
            if isinstance(key, str) and key == "code"
        )
        assert isinstance(code, str)
        assert code == "unexpected_network_policy"

        second = await repository.create_connection(
            rdb_session,
            create=RuntimeProviderConnectionCreate(
                provider_id=provider_id,
                binding_id=binding_id,
                credential_id=credential.id,
                auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
                auth_subject=auth_subject,
                evidence_expires_at=None,
                connection_id="provider-diagnostics-connection-2",
                generation=2,
                reported_provider_type="kubernetes",
                reported_protocol_version="agent-runtime-provider-kubernetes-v3",
                operational_diagnostics=None,
                connected_at=now + datetime.timedelta(minutes=2),
            ),
        )

        assert second.operational_diagnostics is None
        assert not await repository.heartbeat_connection(
            rdb_session,
            provider_id=provider_id,
            binding_id=binding_id,
            credential_id=credential.id,
            generation=first.generation,
            heartbeat_at=now + datetime.timedelta(minutes=3),
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            auth_subject=auth_subject,
            operational_diagnostics=initial,
        )
        second_row = (
            await rdb_session.execute(
                sa.select(RDBRuntimeProviderConnection).where(
                    RDBRuntimeProviderConnection.id == second.id
                )
            )
        ).scalar_one()
        assert second_row.operational_diagnostics is None
        assert second_row.diagnostics_checked_at is None
        current = await repository.get_current_connection(
            rdb_session,
            provider_id=provider_id,
            now=now + datetime.timedelta(minutes=3),
        )
        assert current is not None
        assert current.generation == second.generation
        assert current.operational_diagnostics is None
        assert await repository.disconnect_connection(
            rdb_session,
            provider_id=provider_id,
            binding_id=binding_id,
            credential_id=credential.id,
            generation=second.generation,
            disconnected_at=now + datetime.timedelta(minutes=4),
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            auth_subject=auth_subject,
        )
        assert (
            await repository.get_current_connection(
                rdb_session,
                provider_id=provider_id,
                now=now + datetime.timedelta(minutes=4),
            )
            is None
        )

    async def test_revoked_credential_cannot_heartbeat_connection(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Credential revocation immediately prevents connection heartbeat."""
        repository = RuntimeProviderControlRepository()
        provider_id, source_id, binding_id = await _provider_source_and_binding(
            rdb_session
        )
        auth_subject = f"admin:{provider_id}"
        now = tznow()
        grant = await repository.create_enrollment_grant(
            rdb_session,
            create=RuntimeProviderEnrollmentGrantCreate(
                provider_id=provider_id,
                binding_id=binding_id,
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
                binding_id=binding_id,
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
                binding_id=binding_id,
                credential_id=credential.id,
                auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
                auth_subject=auth_subject,
                evidence_expires_at=None,
                connection_id="provider-control-test-connection",
                generation=1,
                reported_provider_type="docker",
                reported_protocol_version="test-v1",
                operational_diagnostics=None,
                connected_at=now,
            ),
        )

        assert await repository.heartbeat_connection(
            rdb_session,
            provider_id=provider_id,
            binding_id=binding_id,
            credential_id=credential.id,
            generation=connection.generation,
            heartbeat_at=now + datetime.timedelta(seconds=1),
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            auth_subject=auth_subject,
            operational_diagnostics=None,
        )
        assert await repository.connection_active(
            rdb_session,
            provider_id=provider_id,
            binding_id=binding_id,
            credential_id=credential.id,
            generation=connection.generation,
            now=now + datetime.timedelta(seconds=1),
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            auth_subject=auth_subject,
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
            binding_id=binding_id,
            credential_id=credential.id,
            generation=connection.generation,
            heartbeat_at=now + datetime.timedelta(seconds=3),
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            auth_subject=auth_subject,
            operational_diagnostics=None,
        )
        assert not await repository.connection_active(
            rdb_session,
            provider_id=provider_id,
            binding_id=binding_id,
            credential_id=credential.id,
            generation=connection.generation,
            now=now + datetime.timedelta(seconds=3),
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            auth_subject=auth_subject,
        )
        assert not await repository.disconnect_connection(
            rdb_session,
            provider_id=provider_id,
            binding_id=binding_id,
            credential_id=credential.id,
            generation=connection.generation,
            disconnected_at=now + datetime.timedelta(seconds=4),
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            auth_subject=auth_subject,
        )

    async def test_revoked_binding_disconnects_kubernetes_connection(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Binding revocation immediately removes workload connection authority."""
        repository = RuntimeProviderControlRepository()
        provider_id, _, _ = await _provider_source_and_binding(rdb_session)
        binding_repository = RuntimeProviderAuthBindingRepository()
        subject = "system:serviceaccount:azents-runtime:provider"
        binding = await binding_repository.create(
            rdb_session,
            create=RuntimeProviderAuthBindingCreate(
                provider_id=provider_id,
                auth_method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
                subject=subject,
                owner=RuntimeProviderBindingOwner.BOOTSTRAP,
                bootstrap_declaration_id=None,
                config={
                    "namespace": "azents-runtime",
                    "service_account_name": "provider",
                    "audience": "azents-runtime-control",
                },
            ),
        )
        now = tznow()
        connection = await repository.create_connection(
            rdb_session,
            create=RuntimeProviderConnectionCreate(
                provider_id=provider_id,
                binding_id=binding.id,
                credential_id=None,
                auth_method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
                auth_subject=subject,
                evidence_expires_at=now + datetime.timedelta(seconds=2),
                connection_id="provider-control-kubernetes-connection",
                generation=1,
                reported_provider_type="kubernetes",
                reported_protocol_version="test-v1",
                operational_diagnostics=None,
                connected_at=now,
            ),
        )

        assert await repository.heartbeat_connection(
            rdb_session,
            provider_id=provider_id,
            binding_id=binding.id,
            credential_id=None,
            generation=connection.generation,
            heartbeat_at=now + datetime.timedelta(seconds=1),
            auth_method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
            auth_subject=subject,
            operational_diagnostics=None,
        )
        assert await repository.connection_active(
            rdb_session,
            provider_id=provider_id,
            binding_id=binding.id,
            credential_id=None,
            generation=connection.generation,
            now=now + datetime.timedelta(seconds=1),
            auth_method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
            auth_subject=subject,
        )
        assert await repository.has_connected_connection(
            rdb_session,
            provider_id=provider_id,
            now=now + datetime.timedelta(seconds=1),
            for_update=True,
        )
        assert not await repository.has_connected_connection(
            rdb_session,
            provider_id=provider_id,
            now=now + datetime.timedelta(seconds=3),
        )
        revoked = await binding_repository.revoke(
            rdb_session,
            revoke=RuntimeProviderAuthBindingRevoke(
                binding_id=binding.id,
                expected_admin_version=binding.admin_version,
                revoked_at=now + datetime.timedelta(seconds=4),
                revoked_by_user_id=None,
                reason="test",
            ),
        )

        assert revoked is not None
        assert not await repository.heartbeat_connection(
            rdb_session,
            provider_id=provider_id,
            binding_id=binding.id,
            credential_id=None,
            generation=connection.generation,
            heartbeat_at=now + datetime.timedelta(seconds=5),
            auth_method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
            auth_subject=subject,
            operational_diagnostics=None,
        )
        assert not await repository.connection_active(
            rdb_session,
            provider_id=provider_id,
            binding_id=binding.id,
            credential_id=None,
            generation=connection.generation,
            now=now + datetime.timedelta(seconds=5),
            auth_method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
            auth_subject=subject,
        )
        assert not await repository.has_connected_connection(
            rdb_session,
            provider_id=provider_id,
            now=now + datetime.timedelta(seconds=5),
        )


def _diagnostics(
    *,
    checked_at: datetime.datetime,
    code: str,
) -> RuntimeProviderOperationalDiagnostics:
    return RuntimeProviderOperationalDiagnostics(
        checked_at=checked_at,
        warnings=(
            RuntimeProviderOperationalWarning(
                code=code,
                severity=RuntimeProviderOperationalWarningSeverity.WARNING,
                metadata=(
                    {"policy_count": "1"}
                    if code == "unexpected_network_policy"
                    else {"reason": "api_discovery_unavailable"}
                ),
            ),
        ),
    )
