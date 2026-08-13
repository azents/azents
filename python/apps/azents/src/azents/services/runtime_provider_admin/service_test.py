"""Runtime Provider administrative-policy reconciliation tests."""

import datetime
from datetime import UTC
from typing import cast
from unittest.mock import AsyncMock, Mock

from azcommon.datetime import tznow
from azents_runtime_control.provider import (
    RuntimeProviderOperationalDiagnostics,
    RuntimeProviderOperationalWarning,
    RuntimeProviderOperationalWarningSeverity,
)
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.core.runtime_profile import RuntimeReconcileSourceKind
from azents.rdb.session import SessionManager
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.data import RuntimeProviderCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_control.data import RuntimeProviderConnection
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)

from .service import (
    RuntimeProviderAdminService,
    RuntimeProviderOperationalDiagnosticsProjection,
)


async def test_provider_policy_and_workspace_availability_enqueue_versions(
    rdb_session_manager: SessionManager[AsyncSession],
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
        session_manager=rdb_session_manager,
        repository=provider_repository,
        profile_repository=profile_repository,
        control_repository=RuntimeProviderControlRepository(),
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
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Admin diagnostics expose no connection credential or binding authority."""
    provider_repository = Mock(spec=RuntimeProviderRepository)
    cast(
        AsyncMock,
        provider_repository.get_by_provider_id,
    ).return_value = Mock(id="provider-row-1")
    control_repository = Mock(spec=RuntimeProviderControlRepository)
    diagnostics = RuntimeProviderOperationalDiagnostics(
        checked_at=datetime.datetime(2026, 8, 12, tzinfo=UTC),
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
    cast(
        AsyncMock,
        control_repository.get_current_connection,
    ).return_value = Mock(
        spec=RuntimeProviderConnection,
        generation=7,
        reported_protocol_version="agent-runtime-provider-kubernetes-v3",
        operational_diagnostics=diagnostics,
    )
    service = RuntimeProviderAdminService(
        session_manager=rdb_session_manager,
        repository=cast(RuntimeProviderRepository, provider_repository),
        profile_repository=RuntimeProfileRepository(),
        control_repository=cast(
            RuntimeProviderControlRepository,
            control_repository,
        ),
    )

    projection = await service.get_operational_diagnostics("system-kubernetes")
    cast(
        AsyncMock,
        control_repository.get_current_connection,
    ).return_value = None
    unavailable = await service.get_operational_diagnostics("system-kubernetes")

    assert projection == RuntimeProviderOperationalDiagnosticsProjection(
        generation=7,
        protocol_version="agent-runtime-provider-kubernetes-v3",
        diagnostics=diagnostics,
    )
    assert unavailable is None
