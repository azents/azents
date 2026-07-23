"""Admin operations for Runtime Provider product resources."""

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


@dataclasses.dataclass(frozen=True)
class RuntimeProviderAdminUnavailable(Exception):
    """The requested Runtime Provider Admin operation cannot be completed."""

    code: str
    message: str

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclasses.dataclass
class RuntimeProviderAdminService:
    """Manage Provider inventory and mutable administrative policy."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[RuntimeProviderRepository, Depends(RuntimeProviderRepository)]

    async def list_providers(self) -> list[RuntimeProvider]:
        """Return all durable Providers, including disabled resources."""
        async with self.session_manager() as session:
            return await self.repository.list_available(
                session,
                workspace_id=None,
                include_disabled=True,
            )

    async def get_provider(self, provider_id: str) -> RuntimeProvider:
        """Return one Provider by its stable logical ID."""
        async with self.session_manager() as session:
            provider = await self.repository.get_by_provider_id(
                session,
                provider_logical_id=provider_id,
                for_update=False,
            )
        if provider is None:
            raise RuntimeProviderAdminUnavailable(
                code="provider_not_found",
                message="Runtime Provider was not found.",
            )
        return provider

    async def update_policy(
        self,
        provider_id: str,
        *,
        enabled: bool,
        lifecycle_state: RuntimeProviderLifecycleState,
        availability_mode: RuntimeProviderAvailabilityMode,
    ) -> RuntimeProvider:
        """Replace mutable Provider policy without changing Runtime bindings."""
        async with self.session_manager() as session:
            provider = await self.repository.get_by_provider_id(
                session,
                provider_logical_id=provider_id,
                for_update=False,
            )
            if provider is None:
                raise RuntimeProviderAdminUnavailable(
                    code="provider_not_found",
                    message="Runtime Provider was not found.",
                )
            updated = await self.repository.update_administrative_policy(
                session,
                provider_id=provider.id,
                enabled=enabled,
                lifecycle_state=lifecycle_state,
                availability_mode=availability_mode,
            )
        if updated is None:
            raise RuntimeProviderAdminUnavailable(
                code="provider_not_found",
                message="Runtime Provider was not found.",
            )
        return updated

    async def replace_workspace_availability(
        self,
        provider_id: str,
        *,
        workspace_ids: set[str],
    ) -> RuntimeProvider:
        """Replace the Workspace allow-list for one Provider."""
        async with self.session_manager() as session:
            provider = await self.repository.get_by_provider_id(
                session,
                provider_logical_id=provider_id,
                for_update=False,
            )
            if provider is None:
                raise RuntimeProviderAdminUnavailable(
                    code="provider_not_found",
                    message="Runtime Provider was not found.",
                )
            await self.repository.replace_workspace_availability(
                session,
                provider_id=provider.id,
                workspace_ids=workspace_ids,
            )
        return provider
