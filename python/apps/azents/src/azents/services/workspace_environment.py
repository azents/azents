"""Workspace common environment and Agent opt-in application service."""

from typing import Annotated

from azcommon.result import Result
from fastapi import Depends

from azents.core.enums import WorkspaceUserRole
from azents.core.runtime_environment import RuntimeEnvironmentAccessError
from azents.core.workspace_environment import (
    AgentWorkspaceEnvironmentSettings,
    WorkspaceEnvironmentEntryEdit,
    WorkspaceEnvironmentSettings,
)
from azents.repos.agent_runtime_environment import AgentRuntimeEnvironmentRepository
from azents.repos.workspace_environment import WorkspaceEnvironmentRepository


def get_workspace_environment_repository(
    agent_environment: Annotated[
        AgentRuntimeEnvironmentRepository, Depends(AgentRuntimeEnvironmentRepository)
    ],
) -> WorkspaceEnvironmentRepository:
    """Compose completed repository operations from current infrastructure."""
    return WorkspaceEnvironmentRepository(agent_environment)


class WorkspaceEnvironmentService:
    """Return metadata only; repositories own all atomic persistence."""

    def __init__(
        self,
        repository: Annotated[
            WorkspaceEnvironmentRepository,
            Depends(get_workspace_environment_repository),
        ],
    ) -> None:
        self.repository = repository

    async def get(
        self, workspace_id: str, *, role: WorkspaceUserRole
    ) -> WorkspaceEnvironmentSettings:
        """Read available shared names."""
        return await self.repository.get(workspace_id, role=role)

    async def replace(
        self,
        workspace_id: str,
        *,
        edits: list[WorkspaceEnvironmentEntryEdit],
        role: WorkspaceUserRole,
    ) -> Result[WorkspaceEnvironmentSettings, RuntimeEnvironmentAccessError]:
        """Edit encrypted shared values under Owner/Manager authority."""
        return await self.repository.replace(workspace_id, edits=edits, role=role)

    async def agent_settings(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        selected_ids: list[str] | None,
    ) -> Result[AgentWorkspaceEnvironmentSettings, RuntimeEnvironmentAccessError]:
        """Read or explicitly replace the Agent's selected variable IDs."""
        return await self.repository.agent_settings(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
            selected_ids=selected_ids,
        )
