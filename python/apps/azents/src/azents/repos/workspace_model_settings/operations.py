"""Completed Workspace model-default database operations."""

import dataclasses
from typing import Annotated

from azcommon.result import Result
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.workspace_model_settings import WorkspaceModelSettingsRepository
from azents.repos.workspace_model_settings.data import (
    DefaultModelCannotBeCleared,
    WorkspaceModelSettings,
    WorkspaceModelSettingsUpdate,
)


@dataclasses.dataclass
class WorkspaceModelSettingsOperationRepository:
    """Own current snapshots, empty-row creation and atomic default updates."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    settings_repository: Annotated[
        WorkspaceModelSettingsRepository, Depends(WorkspaceModelSettingsRepository)
    ]

    async def get(self, workspace_id: str) -> WorkspaceModelSettings | None:
        """Return a completed current snapshot without creating a row."""
        async with self.session_manager() as session:
            return await self.settings_repository.get(session, workspace_id)

    async def get_or_create(self, workspace_id: str) -> WorkspaceModelSettings:
        """Return current defaults, creating the existing empty row when absent."""
        async with self.session_manager() as session:
            return await self.settings_repository.get_or_create(session, workspace_id)

    async def update(
        self,
        workspace_id: str,
        update: WorkspaceModelSettingsUpdate,
    ) -> Result[WorkspaceModelSettings, DefaultModelCannotBeCleared]:
        """Commit settings and the existing chain-write marker together."""
        async with self.session_manager() as session:
            return await self.settings_repository.update(session, workspace_id, update)
