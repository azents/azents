"""Agent Runtime environment management service."""

import dataclasses
from typing import Annotated

from azcommon.result import Result, Success
from fastapi import Depends
from pydantic import BaseModel

from azents.core.enums import WorkspaceUserRole
from azents.core.runtime_environment import (
    RuntimeEnvironmentAccessError,
    RuntimeEnvironmentEntryEdit,
)
from azents.repos.agent_runtime_environment import (
    AgentRuntimeEnvironmentRepository,
    RuntimeEnvironmentAccess,
)


class RuntimeEnvironmentEntry(BaseModel):
    """Redacted stored entry metadata."""

    name: str
    has_value: bool


class RuntimeEnvironmentSettings(BaseModel):
    """Per-Agent management state; secret values never leave through this model."""

    entries: list[RuntimeEnvironmentEntry]
    can_manage: bool

    @classmethod
    def from_access(
        cls, access: RuntimeEnvironmentAccess
    ) -> "RuntimeEnvironmentSettings":
        """Build metadata without carrying plaintext values."""
        return cls(
            entries=[
                RuntimeEnvironmentEntry(name=name, has_value=True)
                for name in access.names
            ],
            can_manage=access.can_manage,
        )


@dataclasses.dataclass
class AgentRuntimeEnvironmentService:
    """Expose completed redacted storage operations."""

    repository: Annotated[
        AgentRuntimeEnvironmentRepository, Depends(AgentRuntimeEnvironmentRepository)
    ]

    async def get(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[RuntimeEnvironmentSettings, RuntimeEnvironmentAccessError]:
        """Get permitted names and management authority."""
        result = await self.repository.get(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        if isinstance(result, Success):
            return Success(RuntimeEnvironmentSettings.from_access(result.value))
        return result

    async def replace(
        self,
        agent_id: str,
        *,
        edits: list[RuntimeEnvironmentEntryEdit],
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[RuntimeEnvironmentSettings, RuntimeEnvironmentAccessError]:
        """Replace the desired list under current Agent management authority."""
        result = await self.repository.replace(
            agent_id,
            edits=edits,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        if isinstance(result, Success):
            return Success(RuntimeEnvironmentSettings.from_access(result.value))
        return result
