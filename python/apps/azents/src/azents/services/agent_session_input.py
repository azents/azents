"""AgentSession input enqueue facade."""

import dataclasses
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionStatus, InputBufferKind
from azents.engine.run.input import InputMessage
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, AgentSessionCreate
from azents.repos.input_buffer.data import InputBuffer
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService


@dataclasses.dataclass(frozen=True)
class BufferedAgentSessionInputResult:
    """InputBuffer creation and broker wake-up result."""

    agent_runtime_id: str
    agent_session_id: str
    input_buffer: InputBuffer


@dataclasses.dataclass(frozen=True)
class CreatedAgentSessionInputResult:
    """New AgentSession creation and first input enqueue result."""

    agent_runtime_id: str
    agent_session: AgentSession
    input_buffer: InputBuffer


@dataclasses.dataclass(frozen=True)
class AgentSessionInputSessionNotFound:
    """Requested AgentSession was not found."""


@dataclasses.dataclass(frozen=True)
class AgentSessionInputWrongAgent:
    """Requested AgentSession does not belong to the requested agent."""


@dataclasses.dataclass(frozen=True)
class AgentSessionInputInactiveSession:
    """Requested AgentSession is not writable."""


AgentSessionInputError = (
    AgentSessionInputSessionNotFound
    | AgentSessionInputWrongAgent
    | AgentSessionInputInactiveSession
)


@dataclasses.dataclass
class AgentSessionInputService:
    """Input enqueue facade based on AgentSession."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    session_workspace_project_repository: Annotated[
        SessionWorkspaceProjectRepository, Depends(SessionWorkspaceProjectRepository)
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    input_buffer_service: Annotated[InputBufferService, Depends(InputBufferService)]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def create_buffered_agent_input(
        self,
        *,
        agent_id: str,
        agent_session_id: str,
        message: InputMessage,
        user_id: str,
        client_request_id: str | None = None,
    ) -> Result[BufferedAgentSessionInputResult, AgentSessionInputError]:
        """Store user input as durable InputBuffer row."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, agent_session_id
            )
            if agent_session is None:
                return Failure(AgentSessionInputSessionNotFound())
            if agent_session.agent_id != agent_id:
                return Failure(AgentSessionInputWrongAgent())
            if agent_session.status != AgentSessionStatus.ACTIVE:
                return Failure(AgentSessionInputInactiveSession())

            runtime = await self.agent_runtime_repository.ensure_for_agent(
                session, agent_id
            )
            input_buffer = await self._enqueue_user_message(
                session,
                agent_session=agent_session,
                message=message,
                user_id=user_id,
                client_request_id=client_request_id,
            )

        return Success(
            BufferedAgentSessionInputResult(
                agent_runtime_id=runtime.id,
                agent_session_id=agent_session.id,
                input_buffer=input_buffer,
            )
        )

    async def create_team_session_with_buffered_input(
        self,
        *,
        agent_id: str,
        message: InputMessage,
        user_id: str,
        client_request_id: str | None = None,
    ) -> Result[CreatedAgentSessionInputResult, AgentSessionInputError]:
        """Create a non-primary team AgentSession and store first user input."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(AgentSessionInputSessionNotFound())
            if not await self._has_workspace_access(
                session,
                workspace_id=agent.workspace_id,
                user_id=user_id,
            ):
                return Failure(AgentSessionInputSessionNotFound())
            runtime = await self.agent_runtime_repository.ensure_for_agent(
                session, agent_id
            )
            primary = await self.agent_session_repository.ensure_team_primary_for_agent(
                session,
                workspace_id=agent.workspace_id,
                agent_id=agent_id,
            )
            agent_session = await self.agent_session_repository.create(
                session,
                AgentSessionCreate(
                    workspace_id=agent.workspace_id,
                    agent_id=agent_id,
                    title=None,
                    primary_kind=None,
                ),
            )
            await self._copy_primary_projects(
                session,
                from_session_id=primary.id,
                to_session_id=agent_session.id,
            )
            input_buffer = await self._enqueue_user_message(
                session,
                agent_session=agent_session,
                message=message,
                user_id=user_id,
                client_request_id=client_request_id,
            )

        return Success(
            CreatedAgentSessionInputResult(
                agent_runtime_id=runtime.id,
                agent_session=agent_session,
                input_buffer=input_buffer,
            )
        )

    async def _enqueue_user_message(
        self,
        session: AsyncSession,
        *,
        agent_session: AgentSession,
        message: InputMessage,
        user_id: str,
        client_request_id: str | None,
    ) -> InputBuffer:
        """Enqueue one user message for an already selected AgentSession."""
        result = await self.input_buffer_service.enqueue(
            session,
            InputBufferEnqueue(
                session_id=agent_session.id,
                kind=InputBufferKind.USER_MESSAGE,
                actor_user_id=user_id,
                content=message.text,
                idempotency_key=client_request_id,
                metadata=message.metadata,
                attachments=message.attachments,
                file_parts=message.file_parts,
            ),
        )
        return result.input_buffer

    async def _copy_primary_projects(
        self,
        session: AsyncSession,
        *,
        from_session_id: str,
        to_session_id: str,
    ) -> None:
        """Snapshot-copy team primary project registrations into a new session."""
        project_repository = self.session_workspace_project_repository
        primary_projects = await project_repository.list_projects(
            session,
            session_id=from_session_id,
        )
        for project in primary_projects:
            await project_repository.create_project(
                session,
                SessionWorkspaceProjectCreate(
                    session_id=to_session_id,
                    path=project.path,
                ),
            )

    async def _has_workspace_access(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        user_id: str,
    ) -> bool:
        """Return whether the user is a member of the workspace."""
        workspace_user = await self.workspace_user_repository.get_by_workspace_and_user(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        return workspace_user is not None
