"""System-Admin infrastructure Profile deletion service tests."""

import datetime
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.core.runtime_profile import (
    RuntimeInfrastructureProfileKind,
    RuntimeProfileLifecycle,
)
from azents.repos.runtime_profile.data import (
    RuntimeInfrastructureProfile,
    RuntimeInfrastructureProfileDeleteOutcome,
    RuntimeInfrastructureProfileDeletion,
    RuntimeInfrastructureProfileDeletionImpact,
    RuntimeInfrastructureProfileReplace,
    WorkspaceRuntimeProfile,
    WorkspaceRuntimeProfileUsage,
)
from azents.repos.runtime_provider.data import RuntimeProvider
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)
from azents.repos.workspace.data import Workspace
from azents.services.terminal_policy.invalidation import (
    NoopTerminalPolicyInvalidationPublisher,
)
from azents.testing.types import require_instance

from .service import (
    RuntimeProfileAdminService,
    RuntimeProfileAdminUnavailable,
    _infrastructure_terminal_only_change,
)


def _provider() -> RuntimeProvider:
    """Build one Kubernetes Provider projection."""
    now = datetime.datetime(2026, 8, 11, tzinfo=datetime.UTC)
    return RuntimeProvider(
        id="provider-row-1",
        provider_id="provider-1",
        scope=RuntimeProviderScope.SYSTEM,
        workspace_id=None,
        kind=RuntimeProviderKind.KUBERNETES,
        display_name="Provider",
        registration_method=RuntimeProviderRegistrationMethod.ADMIN,
        enabled=True,
        lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
        availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
        current_contract_revision_id=None,
        active_config_revision_id=None,
        admin_version=1,
        capabilities={},
        config_schema=None,
        metadata=None,
        created_at=now,
        updated_at=now,
    )


def _infrastructure_profile(*, version: int = 7) -> RuntimeInfrastructureProfile:
    """Build one Provider-owned Pod Profile."""
    now = datetime.datetime(2026, 8, 11, tzinfo=datetime.UTC)
    return RuntimeInfrastructureProfile(
        id="infrastructure-1",
        provider_id="provider-row-1",
        profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
        display_name="Standard Pod",
        description="Standard Pod",
        lifecycle=RuntimeProfileLifecycle.ACTIVE,
        contract_family="kubernetes.pod-profile",
        schema_version=1,
        spec={"schema_version": 1},
        required_capabilities=("kubernetes.pod-profile",),
        version=version,
        terminal_enabled=True,
        digest="a" * 64,
        created_by_user_id=None,
        updated_by_user_id=None,
        created_at=now,
        updated_at=now,
    )


def _workspace_profile() -> WorkspaceRuntimeProfile:
    """Build one Workspace Runtime Profile detail target."""
    now = datetime.datetime(2026, 8, 11, tzinfo=datetime.UTC)
    return WorkspaceRuntimeProfile(
        id="workspace-profile-1",
        workspace_id="workspace-1",
        provider_id="provider-row-1",
        infrastructure_profile_id="infrastructure-1",
        display_name="Workspace Profile",
        description="Workspace Profile",
        lifecycle=RuntimeProfileLifecycle.ACTIVE,
        policy={"schema_version": 1, "network_restriction": None},
        version=3,
        terminal_enabled=True,
        digest="b" * 64,
        created_by_workspace_user_id=None,
        updated_by_workspace_user_id=None,
        created_at=now,
        updated_at=now,
    )


def _service() -> tuple[
    RuntimeProfileAdminService,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    dict[str, bool],
]:
    """Build the service with transaction-state tracking dependencies."""
    transaction = {"committed": False, "rolled_back": False}

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        try:
            yield AsyncMock(spec=AsyncSession)
        except Exception:
            transaction["rolled_back"] = True
            raise
        else:
            transaction["committed"] = True

    profile_repository = AsyncMock()
    provider_repository = AsyncMock()
    workspace_repository = AsyncMock()
    service = RuntimeProfileAdminService(
        session_manager=session_manager,
        profile_repository=profile_repository,
        provider_repository=provider_repository,
        policy_repository=require_instance(
            MagicMock(spec=RuntimeProviderPolicyRepository),
            RuntimeProviderPolicyRepository,
        ),
        workspace_repository=workspace_repository,
        terminal_policy_invalidation_publisher=(
            NoopTerminalPolicyInvalidationPublisher()
        ),
    )
    provider_repository.get_by_provider_id.return_value = _provider()
    return (
        service,
        profile_repository,
        provider_repository,
        workspace_repository,
        transaction,
    )


def test_terminal_only_infrastructure_change_skips_physical_reconciliation() -> None:
    """The Terminal flag alone is classified as non-physical Profile work."""
    current = _infrastructure_profile()
    replacement = RuntimeInfrastructureProfileReplace(
        display_name=current.display_name,
        description=current.description,
        lifecycle=current.lifecycle,
        contract_family=current.contract_family,
        schema_version=current.schema_version,
        spec=current.spec,
        required_capabilities=current.required_capabilities,
        terminal_enabled=False,
        digest=current.digest,
        actor_user_id="admin-1",
    )

    assert _infrastructure_terminal_only_change(current, replacement) is True


async def test_get_profile_deletion_impact_returns_fresh_projection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Impact reads preserve target identity and bounded current counts."""
    service, profiles, _providers, _workspaces, transaction = _service()
    profile = _infrastructure_profile()
    impact = RuntimeInfrastructureProfileDeletionImpact(
        blocking_reference_count=2,
        references=(),
        applied_only_running_runtime_count=1,
        offset=0,
        limit=50,
    )
    profiles.get_infrastructure_profile.return_value = profile
    profiles.get_infrastructure_profile_deletion_impact.return_value = impact

    with caplog.at_level(logging.INFO):
        result = await service.get_profile_deletion_impact(
            "provider-1",
            profile.id,
            profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
            offset=0,
            limit=50,
        )

    assert result.profile == profile
    assert result.impact == impact
    assert transaction == {"committed": True, "rolled_back": False}
    profiles.get_infrastructure_profile_deletion_impact.assert_awaited_once()
    record = next(
        record
        for record in caplog.records
        if record.message == "Projected infrastructure Profile deletion impact"
    )
    assert vars(record)["blocking_reference_count"] == 2
    assert vars(record)["applied_only_running_runtime_count"] == 1


async def test_delete_profile_returns_committed_result_and_logs_actor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Successful deletion commits and emits only bounded audit context."""
    service, profiles, _providers, _workspaces, transaction = _service()
    profile = _infrastructure_profile()
    deletion = RuntimeInfrastructureProfileDeletion(
        profile_id=profile.id,
        superseded_recreation_operation_count=1,
        skipped_recreation_item_count=3,
    )
    profiles.get_infrastructure_profile.return_value = profile
    profiles.delete_infrastructure_profile.return_value = (
        RuntimeInfrastructureProfileDeleteOutcome(
            deletion=deletion,
            current_profile=None,
            blocking_reference_count=0,
        )
    )

    with caplog.at_level(logging.INFO):
        result = await service.delete_profile(
            "provider-1",
            profile.id,
            profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
            expected_version=profile.version,
            actor_user_id="admin-1",
        )

    assert result == deletion
    assert transaction == {"committed": True, "rolled_back": False}
    record = next(
        record
        for record in caplog.records
        if record.message == "Deleted infrastructure Profile"
    )
    context = vars(record)
    assert context["provider_id"] == "provider-1"
    assert context["infrastructure_profile_id"] == profile.id
    assert context["actor_user_id"] == "admin-1"
    assert context["superseded_recreation_operation_count"] == 1
    assert context["skipped_recreation_item_count"] == 3


@pytest.mark.parametrize(
    ("outcome", "expected_code", "expected_count"),
    (
        (
            RuntimeInfrastructureProfileDeleteOutcome(
                deletion=None,
                current_profile=_infrastructure_profile(version=8),
                blocking_reference_count=0,
            ),
            "profile_version_conflict",
            None,
        ),
        (
            RuntimeInfrastructureProfileDeleteOutcome(
                deletion=None,
                current_profile=_infrastructure_profile(version=7),
                blocking_reference_count=2,
            ),
            "profile_referenced",
            2,
        ),
    ),
)
async def test_delete_profile_maps_current_conflicts(
    outcome: RuntimeInfrastructureProfileDeleteOutcome,
    expected_code: str,
    expected_count: int | None,
) -> None:
    """Stale versions and current references remain distinct failures."""
    service, profiles, _providers, _workspaces, transaction = _service()
    profiles.get_infrastructure_profile.return_value = _infrastructure_profile()
    profiles.delete_infrastructure_profile.return_value = outcome

    with pytest.raises(RuntimeProfileAdminUnavailable) as captured:
        await service.delete_profile(
            "provider-1",
            "infrastructure-1",
            profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
            expected_version=7,
            actor_user_id="admin-1",
        )

    assert captured.value.code == expected_code
    assert captured.value.blocking_reference_count == expected_count
    assert transaction == {"committed": False, "rolled_back": True}


async def test_delete_profile_rolls_back_integrity_conflict() -> None:
    """A concurrent FK conflict rolls back the complete delete transaction."""
    service, profiles, _providers, _workspaces, transaction = _service()
    profiles.get_infrastructure_profile.return_value = _infrastructure_profile()
    profiles.delete_infrastructure_profile.side_effect = IntegrityError(
        "delete infrastructure Profile",
        {},
        Exception("concurrent reference"),
    )

    with pytest.raises(RuntimeProfileAdminUnavailable) as captured:
        await service.delete_profile(
            "provider-1",
            "infrastructure-1",
            profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
            expected_version=7,
            actor_user_id="admin-1",
        )

    assert captured.value.code == "profile_delete_conflict"
    assert transaction == {"committed": False, "rolled_back": True}


async def test_admin_detail_uses_system_admin_projection_without_membership() -> None:
    """Admin detail resolves cross-Workspace data without member authorization."""
    service, profiles, providers, workspaces, transaction = _service()
    now = datetime.datetime(2026, 8, 11, tzinfo=datetime.UTC)
    workspace = Workspace(
        name="Workspace",
        handle="workspace",
        default_runtime_profile_id=None,
        default_runtime_profile_version=1,
        created_at=now,
        updated_at=now,
    )
    workspace_profile = _workspace_profile()
    infrastructure = _infrastructure_profile()
    usage = WorkspaceRuntimeProfileUsage(
        selected_agent_count=4,
        running_runtime_count=2,
    )
    workspaces.get_with_id_by_handle.return_value = ("workspace-1", workspace)
    profiles.get_workspace_runtime_profile.return_value = workspace_profile
    profiles.get_infrastructure_profile.return_value = infrastructure
    profiles.get_workspace_runtime_profile_usage.return_value = usage
    providers.get_by_id.return_value = _provider()

    detail = await service.get_workspace_profile_admin_detail(
        "workspace",
        workspace_profile.id,
    )

    assert detail.workspace_id == "workspace-1"
    assert detail.workspace == workspace
    assert detail.profile == workspace_profile
    assert detail.infrastructure_profile == infrastructure
    assert detail.usage == usage
    assert transaction == {"committed": True, "rolled_back": False}
    workspaces.resolve_id.assert_not_awaited()
    workspaces.get_by_handle.assert_not_awaited()
