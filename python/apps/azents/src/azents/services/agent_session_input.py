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
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.input_buffer.data import InputBuffer
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService


@dataclasses.dataclass(frozen=True)
class BufferedAgentSessionInputResult:
    """InputBuffer creation and broker wake-up result."""

    agent_runtime_id: str
    agent_session_id: str
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

    agent_runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
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
            input_buffer = result.input_buffer

        return Success(
            BufferedAgentSessionInputResult(
                agent_runtime_id=runtime.id,
                agent_session_id=agent_session.id,
                input_buffer=input_buffer,
            )
        )
