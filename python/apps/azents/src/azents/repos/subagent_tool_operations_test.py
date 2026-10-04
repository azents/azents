"""Completed Subagent Toolkit operation tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionStatus
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import CapturedContextSource
from azents.repos.subagent_coordination.repository import (
    SubagentCoordinationRepository,
)
from azents.repos.subagent_tool_operations import SubagentToolOperationRepository


async def test_subagent_tool_operations_close_before_returning_effect_targets() -> None:
    """Subagent reads and queueing return detached results after commit."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    transaction_active = False
    transaction_count = 0

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        nonlocal transaction_active, transaction_count
        assert not transaction_active
        transaction_active = True
        transaction_count += 1
        try:
            yield session
        finally:
            transaction_active = False

    agents = AsyncMock(spec=AgentRepository)
    sessions = AsyncMock(spec=AgentSessionRepository)
    runs = AsyncMock(spec=AgentRunRepository)
    transcripts = AsyncMock(spec=EventTranscriptRepository)
    mailbox = AsyncMock(spec=MailboxRepository)
    sources = AsyncMock(spec=ModelMetadataSourceRepository)
    coordination = AsyncMock(spec=SubagentCoordinationRepository)
    agent = SimpleNamespace(id="agent-1")
    current = SimpleNamespace(
        id="root-agent",
        root_session_agent_id="root-agent",
        agent_session_id="root-session",
        path="/root",
    )
    target = SimpleNamespace(
        id="child-agent",
        root_session_agent_id="root-agent",
        agent_session_id="child-session",
        name="child",
        path="/root/child",
    )
    locked_target = SimpleNamespace(
        status=AgentSessionStatus.ACTIVE,
        stop_requested_at=None,
    )
    agents.get_by_id.return_value = agent
    sessions.get_session_agent_by_session_id.return_value = current
    sessions.resolve_session_agent_path.return_value = target
    sessions.lock_session_agent_by_id.return_value = current
    sessions.lock_by_id.return_value = locked_target
    sources.capture_for_context.return_value = CapturedContextSource(models=())
    coordination.project_root_tree.return_value = None
    operations = SubagentToolOperationRepository(
        session_manager=session_manager,
        agent_repository=agents,
        agent_session_repository=sessions,
        agent_run_repository=runs,
        event_transcript_repository=transcripts,
        mailbox_repository=mailbox,
        source_repository=sources,
        coordination_repository=coordination,
    )

    assert await operations.get_agent("agent-1") is agent
    assert not transaction_active
    assert await operations.get_current_session_agent("root-session") is current
    assert not transaction_active
    assert await operations.load_model_context(requests=[]) == CapturedContextSource(
        models=()
    )
    assert not transaction_active
    assert (
        await operations.list_agents(
            session_id="root-session",
            configured_capacity=3,
        )
        is None
    )
    assert not transaction_active

    result = await operations.send_message(
        session_id="root-session",
        agent_name="child",
        content="note",
    )
    assert result.target is target
    assert not transaction_active
    mailbox.create.assert_awaited_once()
    assert transaction_count == 5
