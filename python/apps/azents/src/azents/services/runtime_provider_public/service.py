"""Workspace-scoped Runtime Provider discovery."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.runtime_provider_data import RuntimeProvider
from azents.repos.runtime_provider.discovery import RuntimeProviderDiscoveryRepository


@dataclasses.dataclass
class RuntimeProviderPublicService:
    """List eligible Providers without exposing mutable binding state."""

    repository: Annotated[
        RuntimeProviderDiscoveryRepository, Depends(RuntimeProviderDiscoveryRepository)
    ]

    async def list_for_workspace(self, workspace_id: str) -> list[RuntimeProvider]:
        """Return enabled, non-retired Providers eligible for one Workspace."""
        return await self.repository.list_for_workspace(workspace_id)
