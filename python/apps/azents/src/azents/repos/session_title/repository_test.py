"""Session title operation repository tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionTitleSource
from azents.repos.session_title import SessionTitleRepository


async def test_load_generation_snapshot_uses_one_completed_database_operation() -> None:
    """The eligible title owner, model selection, and integration share one context."""
    events: list[str] = []
    session: AsyncSession = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        events.append("enter")
        try:
            yield session
        finally:
            events.append("exit")

    agent_session_repository = AsyncMock()
    agent_session_repository.get_by_id.return_value = SimpleNamespace(
        agent_id="agent-1",
        title_source=AgentSessionTitleSource.AUTO_INITIAL,
        title_generation_event_id="event-1",
    )
    selection = SimpleNamespace(llm_provider_integration_id="integration-1")
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = SimpleNamespace(
        id="agent-1",
        lightweight_model_selection=selection,
    )
    integration = SimpleNamespace(enabled=True)
    integration_repository = AsyncMock()
    integration_repository.get_by_id_with_secrets.return_value = integration
    repository = SessionTitleRepository(
        agent_repository=agent_repository,
        agent_session_repository=agent_session_repository,
        integration_repository=integration_repository,
        session_manager=session_manager,
    )

    snapshot = await repository.load_generation_snapshot(
        session_id="session-1",
        generation_event_id="event-1",
    )

    assert snapshot is not None
    assert snapshot.agent_id == "agent-1"
    assert snapshot.selection is selection
    assert snapshot.integration is integration
    assert events == ["enter", "exit"]
    agent_session_repository.get_by_id.assert_awaited_once_with(session, "session-1")
    agent_repository.get_by_id.assert_awaited_once_with(session, "agent-1")
    integration_repository.get_by_id_with_secrets.assert_awaited_once_with(
        session,
        "integration-1",
    )


async def test_replace_initial_auto_title_commits_as_one_repository_operation() -> None:
    """The conditional title update receives one repository-owned session."""
    events: list[str] = []
    session: AsyncSession = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        events.append("enter")
        try:
            yield session
        finally:
            events.append("exit")

    agent_session_repository = AsyncMock()
    updated = SimpleNamespace(id="session-1")
    agent_session_repository.replace_initial_auto_title.return_value = updated
    repository = SessionTitleRepository(
        agent_repository=AsyncMock(),
        agent_session_repository=agent_session_repository,
        integration_repository=AsyncMock(),
        session_manager=session_manager,
    )

    result = await repository.replace_initial_auto_title(
        session_id="session-1",
        title="Incident response",
        event_id="event-1",
    )

    assert result is updated
    assert events == ["enter", "exit"]
    agent_session_repository.replace_initial_auto_title.assert_awaited_once_with(
        session,
        session_id="session-1",
        title="Incident response",
        event_id="event-1",
    )
