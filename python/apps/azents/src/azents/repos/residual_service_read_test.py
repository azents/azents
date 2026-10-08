"""Completed residual service read operation tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent_session_data import AgentSession
from azents.core.enums import AgentSessionStatus
from azents.core.session_execution_data import SessionExecutionRecord
from azents.rdb.session_capabilities import ReadSession, ReadWriteSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_workspace_access import (
    AgentWorkspaceAccessRepository,
    AgentWorkspaceAgentNotFound,
)
from azents.repos.discord_connection_operations import (
    DiscordConnectionOperationRepository,
)
from azents.repos.discord_settings_read import DiscordSettingsReadRepository
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.idle_continuation import IdleContinuationRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.repos.workspace_user import WorkspaceUserRepository


async def test_residual_reads_close_their_sessions_before_returning() -> None:
    """Workspace and Discord snapshots return after their transactions close."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    transaction_active = False

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        nonlocal transaction_active
        transaction_active = True
        try:
            yield session
        finally:
            transaction_active = False

    agent_repository = AsyncMock(spec=AgentRepository)
    external_channel_repository = AsyncMock(spec=ExternalChannelRepository)

    async def get_agent(
        current_session: WriteSession,
        agent_id: str,
    ) -> None:
        assert transaction_active
        assert current_session is session
        assert agent_id == "agent-1"
        return None

    async def get_interaction(
        current_session: WriteSession,
        *,
        interaction_id: str,
    ) -> None:
        assert transaction_active
        assert current_session is session
        assert interaction_id == "interaction-1"
        return None

    agent_repository.get_by_id.side_effect = get_agent
    external_channel_repository.get_interaction.side_effect = get_interaction

    workspace_result = await AgentWorkspaceAccessRepository(
        session_manager=session_manager,
        agent_repository=agent_repository,
        workspace_user_repository=AsyncMock(spec=WorkspaceUserRepository),
    ).get_agent_for_user(
        "agent-1",
        user_id="user-1",
    )
    assert isinstance(workspace_result, Failure)
    assert isinstance(workspace_result.error, AgentWorkspaceAgentNotFound)
    assert not transaction_active

    assert (
        await DiscordSettingsReadRepository(
            session_manager=session_manager,
            external_channel_repository=external_channel_repository,
        ).get_interaction("interaction-1")
        is None
    )
    assert not transaction_active


async def test_residual_mutation_and_idle_read_finish_before_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discord mutation and idle eligibility own their transaction lifetimes."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    transaction_active = False

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        nonlocal transaction_active
        transaction_active = True
        try:
            yield session
        finally:
            transaction_active = False

    external_channel_repository = AsyncMock(spec=ExternalChannelRepository)
    external_channel_repository.prepare_discord_callback.return_value = True
    prepared = await DiscordConnectionOperationRepository(
        session_manager=session_manager,
        external_channel_repository=external_channel_repository,
    ).prepare_callback(
        connection_id="connection-1",
        expected_encrypted_credentials="encrypted",
        expected_configuration_generation=1,
        provider_app_id="app-1",
        interaction_public_key="key",
        callback_selector_hash="hash",
    )
    assert prepared
    _raw_session.commit.assert_awaited_once()
    assert not transaction_active

    async def get_current_owner(
        self: AgentSessionRepository,
        current_session: ReadSession,
        agent_session_id: str,
    ) -> AgentSession:
        del self
        assert transaction_active
        assert current_session is session
        assert agent_session_id == "session-1"
        return AgentSession.model_construct(
            id=agent_session_id,
            owner_generation=1,
            status=AgentSessionStatus.ACTIVE,
            pending_idle_continuation_run_id=None,
            pending_command_id=None,
            agent_id="agent-1",
        )

    monkeypatch.setattr(AgentSessionRepository, "get_by_id", get_current_owner)

    async def get_common_owner(
        self: SessionExecutionRecordRepository,
        current_session: ReadSession,
        session_id: str,
    ) -> SessionExecutionRecord:
        del self
        assert transaction_active
        assert current_session is session
        assert session_id == "session-1"
        return SessionExecutionRecord.model_construct(
            id=session_id,
            owner_generation=1,
            status=AgentSessionStatus.ACTIVE,
            agent_id="agent-1",
        )

    monkeypatch.setattr(SessionExecutionRecordRepository, "get_by_id", get_common_owner)
    eligibility = await IdleContinuationRepository(
        session_manager=session_manager,
        agent_session_repository=AgentSessionRepository(),
        agent_run_repository=AsyncMock(spec=AgentRunRepository),
        mailbox_repository=AsyncMock(spec=MailboxRepository),
        scheduled_task_cycle_repository=AsyncMock(spec=ScheduledTaskCycleRepository),
    ).get_eligibility(
        "session-1",
        "run-1",
        owner_generation=1,
    )
    assert not eligibility.eligible
    assert not transaction_active
