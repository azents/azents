"""Completed Engine tool operations and repository-owned identity/owner binding."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.engine_runtime_tool_read import EngineRuntimeToolReadRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.mcp_oauth_connection.operations import (
    MCPOAuthRuntimeOperationRepository,
)
from azents.repos.memory import MemoryRepository
from azents.repos.memory.operations import MemoryOperationRepository
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task.tool_operations import (
    ScheduledTaskToolOperationRepository,
)
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.session_execution.ownership import OwnerBoundSessionManager
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.toolkit_state.engine import (
    GitHubSelectedInstallationStore,
    McpToolSnapshotStore,
    TodoStateStore,
    ToolkitAgentsAppendixDedupeStateStore,
)


def _owner_manager(
    manager: SessionManager[AsyncSession], owner: SessionExecutionOwner
) -> OwnerBoundSessionManager:
    return OwnerBoundSessionManager(
        session_manager=manager,
        session_id=owner.session_id,
        owner_generation=owner.owner_generation,
    )


@dataclasses.dataclass(frozen=True)
class EngineMcpSnapshotFactory:
    """Create completed snapshot operations for explicit nullable identities."""

    session_manager: SessionManager[AsyncSession] | None

    def with_owner(self, owner: SessionExecutionOwner) -> "EngineMcpSnapshotFactory":
        manager = self.session_manager
        if manager is None:
            return self
        return dataclasses.replace(self, session_manager=_owner_manager(manager, owner))

    def create(
        self,
        *,
        agent_id: str | None,
        session_id: str | None,
        toolkit_namespace: str,
        state_name: str,
    ) -> McpToolSnapshotStore | None:
        """Bind a complete operation only when storage and identities exist."""
        if agent_id == "" or session_id == "":
            raise ValueError("MCP snapshot identities must be nonempty or absent.")
        if self.session_manager is None or agent_id is None or session_id is None:
            return None
        return McpToolSnapshotStore(
            session_manager=self.session_manager,
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=toolkit_namespace,
            state_name=state_name,
        )

    def selected_installation(
        self, *, agent_id: str | None, session_id: str | None
    ) -> GitHubSelectedInstallationStore | None:
        """Create completed GitHub selection operations for an available identity."""
        if agent_id == "" or session_id == "":
            raise ValueError("GitHub selection identities must be nonempty or absent.")
        if self.session_manager is None or agent_id is None or session_id is None:
            return None
        return GitHubSelectedInstallationStore(
            session_manager=self.session_manager,
            agent_id=agent_id,
            session_id=session_id,
        )


@dataclasses.dataclass(frozen=True)
class EngineToolRepositories:
    """Expose completed operations and factories, never an Engine session scope."""

    memory: MemoryOperationRepository
    runtime: EngineRuntimeToolReadRepository
    mcp_oauth: MCPOAuthRuntimeOperationRepository
    snapshots: EngineMcpSnapshotFactory
    appendix: ToolkitAgentsAppendixDedupeStateStore

    def with_owner(self, owner: SessionExecutionOwner) -> "EngineToolRepositories":
        """Rebind every execution-owned database operation within this layer."""
        return dataclasses.replace(
            self,
            memory=dataclasses.replace(
                self.memory,
                session_manager=_owner_manager(self.memory.session_manager, owner),
            ),
            runtime=dataclasses.replace(
                self.runtime,
                session_manager=_owner_manager(self.runtime.session_manager, owner),
            ),
            mcp_oauth=dataclasses.replace(
                self.mcp_oauth,
                session_manager=_owner_manager(self.mcp_oauth.session_manager, owner),
            ),
            snapshots=self.snapshots.with_owner(owner),
            appendix=self.appendix.for_execution(owner),
        )


def get_engine_tool_repositories(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    memory_repository: Annotated[MemoryRepository, Depends(MemoryRepository)],
    agent_runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ],
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ],
    runtime_profile_repository: Annotated[
        RuntimeProfileRepository, Depends(RuntimeProfileRepository)
    ],
    project_repository: Annotated[
        SessionWorkspaceProjectRepository, Depends(SessionWorkspaceProjectRepository)
    ],
) -> EngineToolRepositories:
    """Wire concrete tool database collaborators at the repository boundary."""
    return EngineToolRepositories(
        memory=MemoryOperationRepository(
            session_manager=session_manager,
            memory_repository=memory_repository,
            agent_session_repository=agent_session_repository,
        ),
        runtime=EngineRuntimeToolReadRepository(
            session_manager=session_manager,
            agent_runtime_repository=agent_runtime_repository,
            runtime_profile_repository=runtime_profile_repository,
            project_repository=project_repository,
        ),
        mcp_oauth=MCPOAuthRuntimeOperationRepository(
            session_manager=session_manager,
            connection_repository=MCPOAuthConnectionRepository(cipher=cipher),
        ),
        snapshots=EngineMcpSnapshotFactory(session_manager=session_manager),
        appendix=ToolkitAgentsAppendixDedupeStateStore(session_manager=session_manager),
    )


def get_engine_todo_store(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
) -> TodoStateStore:
    """Compose a completed Todo store inside the repository layer."""
    return TodoStateStore(session_manager=session_manager)


def get_engine_scheduled_tool_operations(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    task_repository: Annotated[
        ScheduledTaskRepository, Depends(ScheduledTaskRepository)
    ],
    cycle_repository: Annotated[
        ScheduledTaskCycleRepository, Depends(ScheduledTaskCycleRepository)
    ],
    mailbox_repository: Annotated[MailboxRepository, Depends(MailboxRepository)],
    run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)],
) -> ScheduledTaskToolOperationRepository:
    """Compose completed Scheduled tool operations without exposing a session."""
    return ScheduledTaskToolOperationRepository(
        session_manager=session_manager,
        task_repository=task_repository,
        cycle_repository=cycle_repository,
        mailbox_repository=mailbox_repository,
        run_repository=run_repository,
    )
