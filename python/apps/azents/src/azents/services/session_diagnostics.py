"""Operational retained Session reads under the existing system-admin boundary."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.session_diagnostics import (
    SessionDiagnosticEventPage,
    SessionDiagnosticFile,
    SessionDiagnosticMetadata,
)
from azents.repos.session_diagnostics import SessionDiagnosticRepository


@dataclasses.dataclass(frozen=True)
class SessionDiagnosticService:
    """Serve bounded canonical diagnostics, not public Conversation history."""

    repository: Annotated[
        SessionDiagnosticRepository, Depends(SessionDiagnosticRepository)
    ]

    async def metadata(
        self, *, session_id: str, workspace_id: str
    ) -> SessionDiagnosticMetadata | None:
        """Read retained common execution metadata in the requested workspace."""
        return await self.repository.metadata(
            session_id=session_id, workspace_id=workspace_id
        )

    async def events(
        self,
        *,
        session_id: str,
        workspace_id: str,
        after: str | None,
        limit: int,
    ) -> SessionDiagnosticEventPage | None:
        """Read typed safe event projections without private provider artifacts."""
        return await self.repository.events(
            session_id=session_id,
            workspace_id=workspace_id,
            after=after,
            limit=limit,
        )

    async def file(
        self,
        *,
        session_id: str,
        workspace_id: str,
        path: str,
        offset: int,
        limit: int,
    ) -> SessionDiagnosticFile | None:
        """Read one bounded retained file slice without mutation or regeneration."""
        return await self.repository.file(
            session_id=session_id,
            workspace_id=workspace_id,
            path=path,
            offset=offset,
            limit=limit,
        )
