"""Completed Runtime management database operations."""

import dataclasses
from typing import Annotated

from azcommon.datetime import tznow
from fastapi import Depends

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderLifecycleState,
)
from azents.core.runtime_profile import RuntimeReconcileSourceKind
from azents.core.runtime_provider_admin import (
    RuntimeProviderAdminUnavailable,
    RuntimeProviderOperationalDiagnosticsProjection,
)
from azents.core.runtime_provider_data import RuntimeProvider
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)


@dataclasses.dataclass
class RuntimeProviderAdminOperationsRepository:
    """Own grouped database operations before service effects."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]

    repository: Annotated[RuntimeProviderRepository, Depends(RuntimeProviderRepository)]

    profile_repository: Annotated[
        RuntimeProfileRepository, Depends(RuntimeProfileRepository)
    ]

    control_repository: Annotated[
        RuntimeProviderControlRepository,
        Depends(RuntimeProviderControlRepository),
    ]

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
            )
        if provider is None:
            raise RuntimeProviderAdminUnavailable(
                code="provider_not_found",
                message="Runtime Provider was not found.",
            )
        return provider

    async def get_operational_diagnostics(
        self,
        provider_id: str,
    ) -> RuntimeProviderOperationalDiagnosticsProjection | None:
        """Return diagnostics only from the active authenticated generation."""
        async with self.session_manager() as session:
            provider = await self.repository.get_by_provider_id(
                session,
                provider_logical_id=provider_id,
            )
            if provider is None:
                raise RuntimeProviderAdminUnavailable(
                    code="provider_not_found",
                    message="Runtime Provider was not found.",
                )
            connection = await self.control_repository.get_current_connection(
                session,
                provider_id=provider.id,
                now=tznow(),
            )
        if connection is None or connection.operational_diagnostics is None:
            return None
        return RuntimeProviderOperationalDiagnosticsProjection(
            generation=connection.generation,
            protocol_version=connection.reported_protocol_version,
            diagnostics=connection.operational_diagnostics,
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
        async with self.session_manager() as session:
            provider = await self.repository.get_by_provider_id(
                session,
                provider_logical_id=provider_id,
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
            if updated is not None:
                await self.profile_repository.enqueue_reconcile_task(
                    session,
                    source_type=RuntimeReconcileSourceKind.PROVIDER,
                    source_id=updated.id,
                    source_version=str(updated.admin_version),
                    available_at=tznow(),
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
            )
            if provider is None:
                raise RuntimeProviderAdminUnavailable(
                    code="provider_not_found",
                    message="Runtime Provider was not found.",
                )
            updated = await self.repository.replace_workspace_availability(
                session,
                provider_id=provider.id,
                workspace_ids=workspace_ids,
            )
            if updated is not None:
                await self.profile_repository.enqueue_reconcile_task(
                    session,
                    source_type=RuntimeReconcileSourceKind.PROVIDER,
                    source_id=updated.id,
                    source_version=str(updated.admin_version),
                    available_at=tznow(),
                )
        if updated is None:
            raise RuntimeProviderAdminUnavailable(
                code="provider_not_found",
                message="Runtime Provider was not found.",
            )
        return updated
