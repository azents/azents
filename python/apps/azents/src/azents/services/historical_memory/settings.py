"""Human-facing Historical Memory settings service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.enums import WorkspaceUserRole
from azents.repos.agent.data import NotFound
from azents.repos.historical_memory.settings import (
    HistoricalMemorySettingsRepository,
)
from azents.repos.historical_memory.settings_data import (
    HistoricalMemorySettingsCursorError,
    HistoricalMemorySettingsScope,
)
from azents.services.agent.data import (
    NotBelongToWorkspace,
    PrivateAgentAccessDenied,
)
from azents.services.memory import MemoryService

from .settings_data import (
    HistoricalMemorySettingsCursorInvalid,
    HistoricalMemorySettingsListOutput,
    HistoricalMemorySettingsNotFound,
    HistoricalMemorySettingsOutput,
)


@dataclasses.dataclass
class HistoricalMemorySettingsService:
    """Read currently visible Historical Memory for human settings."""

    repository: Annotated[
        HistoricalMemorySettingsRepository,
        Depends(HistoricalMemorySettingsRepository),
    ]
    memory_service: Annotated[MemoryService, Depends(MemoryService)]

    async def list(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
        scope: HistoricalMemorySettingsScope,
        query: str | None,
        cursor: str | None,
        limit: int,
    ) -> Result[
        HistoricalMemorySettingsListOutput,
        NotFound
        | NotBelongToWorkspace
        | PrivateAgentAccessDenied
        | HistoricalMemorySettingsCursorInvalid,
    ]:
        """List one exact Historical Memory source scope."""
        access = await self.memory_service.get_visible_agent(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        match access:
            case Success():
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(access)
        try:
            page = await self.repository.list(
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
                scope=scope,
                query=query,
                cursor=cursor,
                limit=limit,
            )
        except HistoricalMemorySettingsCursorError as error:
            return Failure(HistoricalMemorySettingsCursorInvalid(message=str(error)))
        return Success(HistoricalMemorySettingsListOutput.convert_from(page))

    async def get(
        self,
        agent_id: str,
        source_session_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        HistoricalMemorySettingsOutput,
        NotFound
        | NotBelongToWorkspace
        | PrivateAgentAccessDenied
        | HistoricalMemorySettingsNotFound,
    ]:
        """Return one currently visible Historical Memory source."""
        access = await self.memory_service.get_visible_agent(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        match access:
            case Success():
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(access)
        record = await self.repository.get(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            source_session_id=source_session_id,
        )
        if record is None:
            return Failure(
                HistoricalMemorySettingsNotFound(source_session_id=source_session_id)
            )
        return Success(HistoricalMemorySettingsOutput.convert_from(record))
