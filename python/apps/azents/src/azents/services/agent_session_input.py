"""AgentSession input enqueue facade."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionEndReason,
    AgentSessionStartReason,
    InputBufferKind,
)
from azents.engine.run.input import InputMessage
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import EventSessionRepository
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
    event_session_repository: Annotated[
        EventSessionRepository, Depends(EventSessionRepository)
    ]
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
    ) -> BufferedAgentSessionInputResult:
        """Store user input as durable InputBuffer row."""
        async with self.session_manager() as session:
            runtime = await self.agent_runtime_repository.ensure_for_agent(
                session, agent_id
            )
            active_session = (
                await self.agent_session_repository.ensure_active_with_runtime_lock(
                    session, runtime.id
                )
            )
            await self.event_session_repository.ensure_from_legacy_session(
                session,
                active_session,
            )
            agent_session = await self.agent_session_repository.get_by_id(
                session, agent_session_id
            )
            if agent_session is None:
                raise ValueError("AgentSession not found")
            if agent_session.agent_runtime_id != runtime.id:
                raise ValueError("AgentSession does not belong to the agent runtime")
            target_session_id = active_session.id
            result = await self.input_buffer_service.enqueue(
                session,
                InputBufferEnqueue(
                    session_id=target_session_id,
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

        return BufferedAgentSessionInputResult(
            agent_runtime_id=runtime.id,
            agent_session_id=target_session_id,
            input_buffer=input_buffer,
        )

    async def rotate_agent_session(
        self,
        *,
        agent_id: str,
        start_reason: AgentSessionStartReason,
        end_reason: AgentSessionEndReason,
    ) -> str:
        """Rotate active AgentSession of Agent non-destructively.

        :param agent_id: Agent ID
        :param start_reason: New AgentSession start reason
        :param end_reason: Existing AgentSession end reason
        :return: New active AgentSession ID
        """
        async with self.session_manager() as session:
            runtime = await self.agent_runtime_repository.ensure_for_agent(
                session, agent_id
            )
            rotation = await self.agent_session_repository.rotate_active_with_previous(
                session,
                runtime.id,
                start_reason=start_reason,
                end_reason=end_reason,
                now=datetime.datetime.now(datetime.timezone.utc),
            )
            if rotation.previous is not None:
                await self.input_buffer_service.move_by_session_id(
                    session,
                    from_session_id=rotation.previous.id,
                    to_session_id=rotation.current.id,
                )
                previous = await self.agent_session_repository.get_by_id(
                    session,
                    rotation.previous.id,
                )
                if previous is not None:
                    await self.event_session_repository.ensure_from_legacy_session(
                        session,
                        previous,
                    )
            await self.event_session_repository.ensure_from_legacy_session(
                session,
                rotation.current,
            )
            return rotation.current.id
