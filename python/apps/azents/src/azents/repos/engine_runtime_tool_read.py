"""Completed database reads for Engine Runtime Toolkit context."""

import dataclasses

from azents.core.session_workspace_project import SessionWorkspaceProject
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_profile.data import RuntimeConfigurationState
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.session_workspace_project import (
    SessionWorkspaceProjectRepository,
)


@dataclasses.dataclass(frozen=True)
class RuntimeToolBehaviorState:
    """Detached Runtime and configuration state for prompt projection."""

    runtime: AgentRuntime
    configuration: RuntimeConfigurationState | None


@dataclasses.dataclass
class EngineRuntimeToolReadRepository:
    """Own completed Runtime Toolkit database reads."""

    session_manager: SessionManager[ReadSession]
    agent_runtime_repository: AgentRuntimeRepository
    runtime_profile_repository: RuntimeProfileRepository
    project_repository: SessionWorkspaceProjectRepository

    async def load_behavior(
        self,
        *,
        agent_id: str,
    ) -> RuntimeToolBehaviorState | None:
        """Load Runtime and current configuration in one completed transaction."""
        async with self.session_manager() as session:
            runtime = await self.agent_runtime_repository.get_by_agent_id(
                session,
                agent_id,
            )
            if runtime is None:
                return None
            configuration = (
                await self.runtime_profile_repository.get_configuration_state(
                    session,
                    runtime_id=runtime.id,
                )
            )
            return RuntimeToolBehaviorState(
                runtime=runtime,
                configuration=configuration,
            )

    async def list_projects(
        self,
        *,
        session_id: str,
    ) -> list[SessionWorkspaceProject]:
        """List registered Session Projects in a completed transaction."""
        if not session_id:
            return []
        async with self.session_manager() as session:
            return await self.project_repository.list_projects(
                session,
                session_id=session_id,
            )
