"""Runtime management sequencing through completed repository operations."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderLifecycleState,
)
from azents.core.runtime_provider_admin import (
    RuntimeProviderOperationalDiagnosticsProjection,
)
from azents.core.runtime_provider_data import RuntimeProvider
from azents.repos.runtime_provider_admin_operations import (
    RuntimeProviderAdminOperationsRepository,
)


@dataclasses.dataclass
class RuntimeProviderAdminService:
    """Sequence completed management operations and postcommit effects."""

    operations: Annotated[
        RuntimeProviderAdminOperationsRepository,
        Depends(RuntimeProviderAdminOperationsRepository),
    ]

    async def list_providers(self) -> list[RuntimeProvider]:
        """Return all durable Providers, including disabled resources."""
        return await self.operations.list_providers()

    async def get_provider(self, provider_id: str) -> RuntimeProvider:
        """Return one Provider by its stable logical ID."""
        return await self.operations.get_provider(provider_id=provider_id)

    async def get_operational_diagnostics(
        self,
        provider_id: str,
    ) -> RuntimeProviderOperationalDiagnosticsProjection | None:
        """Return diagnostics only from the active authenticated generation."""
        return await self.operations.get_operational_diagnostics(
            provider_id=provider_id
        )

    async def update_policy(
        self,
        provider_id: str,
        *,
        enabled: bool,
        lifecycle_state: RuntimeProviderLifecycleState,
        availability_mode: RuntimeProviderAvailabilityMode,
    ) -> RuntimeProvider:
        """Replace mutable Provider policy without changing Runtime bindings."""
        return await self.operations.update_policy(
            provider_id=provider_id,
            enabled=enabled,
            lifecycle_state=lifecycle_state,
            availability_mode=availability_mode,
        )

    async def replace_workspace_availability(
        self,
        provider_id: str,
        *,
        workspace_ids: set[str],
    ) -> RuntimeProvider:
        """Replace the Workspace allow-list for one Provider."""
        return await self.operations.replace_workspace_availability(
            provider_id=provider_id, workspace_ids=workspace_ids
        )
