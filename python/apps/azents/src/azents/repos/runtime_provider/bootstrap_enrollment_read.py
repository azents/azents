"""Completed bootstrap source ownership reads for Provider credential enrollment."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.enums import RuntimeProviderBootstrapDeclarationState
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.runtime_provider.repository import RuntimeProviderRepository


@dataclasses.dataclass(frozen=True)
class BootstrapEnrollmentTarget:
    """Detached source-owned Provider identity used by credential orchestration."""

    provider_id: str
    source_id: str


@dataclasses.dataclass(frozen=True)
class RuntimeProviderBootstrapEnrollmentReadRepository:
    """Complete the exact Provider/declaration authority read before enrollment."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    provider_repository: Annotated[
        RuntimeProviderRepository, Depends(RuntimeProviderRepository)
    ]

    async def resolve(
        self, *, provider_logical_id: str, source_id: str
    ) -> BootstrapEnrollmentTarget:
        """Return the Provider only when its current declaration belongs to source."""
        async with self.session_manager() as session:
            provider = await self.provider_repository.get_by_provider_id(
                session, provider_logical_id=provider_logical_id
            )
            if provider is None:
                raise RuntimeError("Bootstrap Provider was not created.")
            declaration = (
                await self.provider_repository.get_bootstrap_declaration_by_provider_id(
                    session, provider_id=provider.id
                )
            )
            if (
                declaration is None
                or declaration.source_id != source_id
                or declaration.state != RuntimeProviderBootstrapDeclarationState.PRESENT
            ):
                raise RuntimeError(
                    "Bootstrap source does not own the credential target Provider."
                )
            return BootstrapEnrollmentTarget(
                provider_id=provider.id, source_id=declaration.source_id
            )
