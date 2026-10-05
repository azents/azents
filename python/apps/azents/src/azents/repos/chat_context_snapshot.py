"""Completed database snapshot reads for the Session Context inspector."""

import dataclasses
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.agent_session_data import AgentSession
from azents.core.chat_data import NotWorkspaceMember, SessionNotFound
from azents.core.enums import AgentSessionStatus
from azents.engine.events.types import Event, SystemPromptAnalysisPayload
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session_system_prompt_snapshot import (
    AgentSessionSystemPromptSnapshotRepository,
)
from azents.repos.workspace_user import WorkspaceUserRepository


@dataclasses.dataclass(frozen=True)
class SessionContextSnapshot:
    """Detached, authorized evidence for one Session Context projection."""

    session: AgentSession
    events: tuple[Event, ...]
    system_prompt: SystemPromptAnalysisPayload | None


@dataclasses.dataclass
class SessionContextSnapshotRepository:
    """Finish the complete authorized Context read before presentation work."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    system_prompt_snapshot_repository: Annotated[
        AgentSessionSystemPromptSnapshotRepository,
        Depends(AgentSessionSystemPromptSnapshotRepository),
    ]

    async def read(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        limit: int,
    ) -> Result[SessionContextSnapshot, SessionNotFound | NotWorkspaceMember]:
        """Read the selected active Session, membership, events and prompt."""
        bounded_limit = max(1, min(limit, 500))
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if (
                agent_session is None
                or agent_session.agent_id != agent_id
                or agent_session.status != AgentSessionStatus.ACTIVE
            ):
                return Failure(SessionNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(NotWorkspaceMember())
            events = await self.transcript_repository.list_recent_by_session_id(
                session, agent_session.id, limit=bounded_limit
            )
            system_prompt = await self.system_prompt_snapshot_repository.get(
                session, session_id=agent_session.id
            )
            return Success(
                SessionContextSnapshot(
                    session=agent_session,
                    events=tuple(events),
                    system_prompt=system_prompt,
                )
            )
