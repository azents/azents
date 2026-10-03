"""Repository-only composition for Worker Toolkit database operations."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.subagent_coordination.repository import SubagentCoordinationRepository
from azents.repos.subagent_tool_operations import SubagentToolOperationRepository
from azents.repos.toolkit_state.engine import ToolkitClaudeRulesAppendixDedupeStateStore


def get_worker_claude_rules_store(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
) -> ToolkitClaudeRulesAppendixDedupeStateStore:
    """Create the completed state store without exporting its session factory."""
    return ToolkitClaudeRulesAppendixDedupeStateStore(
        session_manager=session_manager,
    )


def get_worker_subagent_operations(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)],
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ],
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)],
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ],
    mailbox_repository: Annotated[MailboxRepository, Depends(MailboxRepository)],
    source_snapshot_repository: Annotated[
        ModelMetadataSourceRepository, Depends(ModelMetadataSourceRepository)
    ],
    coordination_repository: Annotated[
        SubagentCoordinationRepository, Depends(SubagentCoordinationRepository)
    ],
) -> SubagentToolOperationRepository:
    """Compose the actual atomic Subagent operations in the repository layer."""
    return SubagentToolOperationRepository(
        session_manager=session_manager,
        agent_repository=agent_repository,
        agent_session_repository=agent_session_repository,
        agent_run_repository=agent_run_repository,
        event_transcript_repository=event_transcript_repository,
        mailbox_repository=mailbox_repository,
        source_snapshot_repository=source_snapshot_repository,
        coordination_repository=coordination_repository,
    )
