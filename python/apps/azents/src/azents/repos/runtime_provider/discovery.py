"""Completed descriptive Runtime Provider discovery reads."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderLifecycleState,
)
from azents.core.runtime_provider_data import RuntimeProvider
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.runtime_provider.repository import RuntimeProviderRepository


@dataclasses.dataclass
class RuntimeProviderDiscoveryRepository:
    """Own the complete nonlocking Provider eligibility read."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    repository: Annotated[RuntimeProviderRepository, Depends(RuntimeProviderRepository)]

    async def list_for_workspace(self, workspace_id: str) -> list[RuntimeProvider]:
        """Return enabled, active Providers allowed in the selected Workspace."""
        async with self.session_manager() as session:
            providers = await self.repository.list_available(
                session, workspace_id=workspace_id, include_disabled=False
            )
            eligible: list[RuntimeProvider] = []
            for provider in providers:
                if provider.lifecycle_state is not RuntimeProviderLifecycleState.ACTIVE:
                    continue
                if provider.availability_mode == (
                    RuntimeProviderAvailabilityMode.SELECTED_WORKSPACES
                ) and not await self.repository.is_available_to_workspace(
                    session, provider_id=provider.id, workspace_id=workspace_id
                ):
                    continue
                eligible.append(provider)
            return eligible
