"""Runtime Profile availability repository tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderLifecycleState,
    RuntimeProviderScope,
)
from azents.core.runtime_profile import RuntimeProfileLifecycle
from azents.repos.runtime_profile.availability import (
    RuntimeProfileAvailabilityRepository,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)


async def test_provider_unavailable_profile_returns_existing_reason_code() -> None:
    """Agent selection preserves the Workspace projection rejection order."""
    session = AsyncMock(spec=AsyncSession)
    profile_repository = AsyncMock(spec=RuntimeProfileRepository)
    provider_repository = AsyncMock(spec=RuntimeProviderRepository)
    control_repository = AsyncMock(spec=RuntimeProviderControlRepository)
    profile_repository.get_workspace_runtime_profile.return_value = SimpleNamespace(
        provider_id="provider-1",
        infrastructure_profile_id="infrastructure-1",
        lifecycle=RuntimeProfileLifecycle.ACTIVE,
        policy={"schema_version": 1},
    )
    profile_repository.get_infrastructure_profile.return_value = SimpleNamespace(
        provider_id="provider-1",
        lifecycle=RuntimeProfileLifecycle.ACTIVE,
        spec={"schema_version": 1},
    )
    provider_repository.get_by_id.return_value = SimpleNamespace(
        id="provider-1",
        scope=RuntimeProviderScope.SYSTEM,
        enabled=False,
        lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
        current_contract_revision_id="revision-1",
        availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
    )
    repository = RuntimeProfileAvailabilityRepository(
        profile_repository=profile_repository,
        provider_repository=provider_repository,
        policy_repository=AsyncMock(spec=RuntimeProviderPolicyRepository),
        control_repository=control_repository,
    )

    code = await repository.get_agent_profile_unavailability_code(
        session,
        workspace_id="workspace-1",
        profile_id="profile-1",
    )

    assert code == "provider_unavailable"
    control_repository.has_connected_connection.assert_not_awaited()
