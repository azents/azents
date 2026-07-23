"""Workspace-scoped Runtime Provider discovery."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderLifecycleState,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.runtime_provider.data import RuntimeProvider
from azents.repos.runtime_provider.repository import RuntimeProviderRepository


@dataclasses.dataclass
class RuntimeProviderPublicService:
    """List eligible Providers without exposing mutable binding state."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[RuntimeProviderRepository, Depends(RuntimeProviderRepository)]

    async def list_for_workspace(self, workspace_id: str) -> list[RuntimeProvider]:
        """Return enabled, non-retired Providers eligible for one Workspace."""
        async with self.session_manager() as session:
            providers = await self.repository.list_available(
                session,
                workspace_id=workspace_id,
                include_disabled=False,
            )
            eligible: list[RuntimeProvider] = []
            for provider in providers:
                if provider.lifecycle_state is not RuntimeProviderLifecycleState.ACTIVE:
                    continue
                if provider.availability_mode == (
                    RuntimeProviderAvailabilityMode.SELECTED_WORKSPACES
                ) and not await self.repository.is_available_to_workspace(
                    session,
                    provider_id=provider.id,
                    workspace_id=workspace_id,
                ):
                    continue
                eligible.append(provider)
            return eligible
