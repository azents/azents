"""Runtime Provider administrative-policy reconciliation tests."""

import datetime
from datetime import UTC

from azcommon.datetime import tznow
from azents_runtime_control.provider import (
    RuntimeProviderOperationalDiagnostics,
    RuntimeProviderOperationalWarning,
    RuntimeProviderOperationalWarningSeverity,
)

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderConnectionStatus,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.core.runtime_profile import RuntimeReconcileSourceKind
from azents.core.runtime_provider_admin import (
    RuntimeProviderOperationalDiagnosticsProjection,
)
from azents.core.runtime_provider_data import RuntimeProvider
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.data import RuntimeProviderCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_admin_operations import (
    RuntimeProviderAdminOperationsRepository,
)
from azents.repos.runtime_provider_control.data import RuntimeProviderConnection
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)

from .service import RuntimeProviderAdminService


class _DiagnosticsProviderRepository(RuntimeProviderRepository):
    """Return the native Provider used by administrative diagnostics."""

    def __init__(self, provider: RuntimeProvider) -> None:
        self.provider = provider

    async def get_by_provider_id(
        self,
        session: ReadSession,
        *,
        provider_logical_id: str,
    ) -> RuntimeProvider | None:
        """Resolve only the exact Provider configured for this test."""
        del session
        assert provider_logical_id == self.provider.provider_id
        return self.provider


class _DiagnosticsControlRepository(RuntimeProviderControlRepository):
    """Expose a typed current-connection transition for diagnostics."""

    def __init__(self, connection: RuntimeProviderConnection | None) -> None:
        self.connection = connection

    async def get_current_connection(
        self,
        session: ReadSession,
        *,
        provider_id: str,
        now: datetime.datetime,
    ) -> RuntimeProviderConnection | None:
        """Return the exact authenticated generation or its unavailability."""
        del session, now
        assert provider_id == "provider-row-1"
        return self.connection


async def test_provider_policy_and_workspace_availability_enqueue_versions(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Every Provider policy mutation advances and reconciles Admin version."""
    provider_repository = RuntimeProviderRepository()
    profile_repository = RuntimeProfileRepository()
    async with rdb_session_manager() as session:
        provider = await provider_repository.create(
            session,
            RuntimeProviderCreate(
                provider_id="system-provider-admin-reconcile",
                scope=RuntimeProviderScope.SYSTEM,
                workspace_id=None,
                kind=RuntimeProviderKind.KUBERNETES,
                display_name="Admin Reconcile Provider",
                registration_method=RuntimeProviderRegistrationMethod.ADMIN,
                enabled=True,
                lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
                availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
                capabilities={},
                config_schema=None,
                metadata=None,
            ),
        )
    service = RuntimeProviderAdminService(
        operations=RuntimeProviderAdminOperationsRepository(
            session_manager=rdb_session_manager,
            repository=provider_repository,
            profile_repository=profile_repository,
            control_repository=RuntimeProviderControlRepository(),
        )
    )

    policy_updated = await service.update_policy(
        provider.provider_id,
        enabled=True,
        lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
        availability_mode=RuntimeProviderAvailabilityMode.SELECTED_WORKSPACES,
    )
    assert policy_updated.admin_version == 1

    async with rdb_session_manager() as session:
        first_tasks = await profile_repository.claim_reconcile_tasks(
            session,
            available_before=tznow() + datetime.timedelta(seconds=1),
            reclaim_running_before=tznow() - datetime.timedelta(minutes=5),
            limit=10,
        )
        assert len(first_tasks) == 1
        first = first_tasks[0]
        assert first.source_type is RuntimeReconcileSourceKind.PROVIDER
        assert first.source_id == provider.id
        assert first.source_version == "1"
        assert await profile_repository.complete_reconcile_task(
            session,
            task_id=first.id,
            expected_attempt=first.attempt,
            cursor=None,
        )

    availability_updated = await service.replace_workspace_availability(
        provider.provider_id,
        workspace_ids=set(),
    )
    assert availability_updated.admin_version == 2

    async with rdb_session_manager() as session:
        second_tasks = await profile_repository.claim_reconcile_tasks(
            session,
            available_before=tznow() + datetime.timedelta(seconds=1),
            reclaim_running_before=tznow() - datetime.timedelta(minutes=5),
            limit=10,
        )
        assert len(second_tasks) == 1
        second = second_tasks[0]
        assert second.source_type is RuntimeReconcileSourceKind.PROVIDER
        assert second.source_id == provider.id
        assert second.source_version == "2"


async def test_provider_operational_diagnostics_returns_only_current_projection(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Admin diagnostics expose no connection credential or binding authority."""
    checked_at = datetime.datetime(2026, 8, 12, tzinfo=UTC)
    provider_repository = _DiagnosticsProviderRepository(
        RuntimeProvider(
            id="provider-row-1",
            provider_id="system-kubernetes",
            scope=RuntimeProviderScope.SYSTEM,
            workspace_id=None,
            kind=RuntimeProviderKind.KUBERNETES,
            display_name="Diagnostics Provider",
            registration_method=RuntimeProviderRegistrationMethod.ADMIN,
            enabled=True,
            lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
            availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
            current_contract_revision_id=None,
            active_config_revision_id=None,
            admin_version=0,
            capabilities={},
            config_schema=None,
            metadata=None,
            created_at=checked_at,
            updated_at=checked_at,
        )
    )
    diagnostics = RuntimeProviderOperationalDiagnostics(
        checked_at=checked_at,
        warnings=(
            RuntimeProviderOperationalWarning(
                code="rbac_incomplete",
                severity=RuntimeProviderOperationalWarningSeverity.WARNING,
                metadata={
                    "required_verb": "get",
                    "resource_kind": "secrets",
                },
            ),
        ),
    )
    control_repository = _DiagnosticsControlRepository(
        RuntimeProviderConnection(
            id="connection-row-1",
            provider_id="provider-row-1",
            binding_id="binding-1",
            credential_id="credential-1",
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            auth_subject="system-kubernetes",
            evidence_expires_at=None,
            connection_id="connection-1",
            generation=7,
            status=RuntimeProviderConnectionStatus.CONNECTED,
            reported_provider_type="kubernetes",
            reported_protocol_version="agent-runtime-provider-kubernetes-v3",
            operational_diagnostics=diagnostics,
            connected_at=checked_at,
            last_heartbeat_at=checked_at,
            disconnected_at=None,
            created_at=checked_at,
        )
    )
    service = RuntimeProviderAdminService(
        operations=RuntimeProviderAdminOperationsRepository(
            session_manager=rdb_session_manager,
            repository=provider_repository,
            profile_repository=RuntimeProfileRepository(),
            control_repository=control_repository,
        )
    )

    projection = await service.get_operational_diagnostics("system-kubernetes")
    control_repository.connection = None
    unavailable = await service.get_operational_diagnostics("system-kubernetes")

    assert projection == RuntimeProviderOperationalDiagnosticsProjection(
        generation=7,
        protocol_version="agent-runtime-provider-kubernetes-v3",
        diagnostics=diagnostics,
    )
    assert unavailable is None
