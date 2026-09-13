"""Session title operation repository tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionTitleSource
from azents.core.model_operation import ModelOperationKind
from azents.repos.model_candidate_health.data import (
    ModelCandidateHealthObservation,
    ModelCandidateHealthStatus,
)
from azents.repos.session_title import SessionTitleRepository
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_options,
)


async def test_load_generation_snapshot_freezes_title_operation_in_one_context() -> (
    None
):
    """The title owner, chain selection, and persistence share one transaction."""
    events: list[str] = []
    session: AsyncSession = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        events.append("enter")
        try:
            yield session
        finally:
            events.append("exit")

    agent_session = SimpleNamespace(
        agent_id="agent-1",
        title_source=AgentSessionTitleSource.AUTO_INITIAL,
        title_generation_event_id="event-1",
        title_model_operation_state=None,
    )
    agent_session_repository = AsyncMock()
    agent_session_repository.lock_by_id.return_value = agent_session
    agent_session_repository.set_title_model_operation_state.return_value = (
        agent_session
    )
    selection = make_test_model_selection(integration_id="integration-1")
    options = make_test_selectable_model_options(selection)
    agent_repository = AsyncMock()
    agent_repository.lock_by_id.return_value = SimpleNamespace(
        id="agent-1",
        workspace_id="workspace-1",
        lightweight_model_label="default",
        selectable_model_options=options,
    )
    health_repository = AsyncMock()
    now = datetime.datetime.now(datetime.UTC)
    health_repository.snapshot_for_background_in_session.return_value = (
        ModelCandidateHealthObservation(
            server_time=now,
            status=ModelCandidateHealthStatus.AVAILABLE,
            health=None,
        )
    )
    repository = SessionTitleRepository(
        agent_repository=agent_repository,
        agent_session_repository=agent_session_repository,
        health_repository=health_repository,
        session_manager=session_manager,
    )

    snapshot = await repository.load_generation_snapshot(
        session_id="session-1",
        generation_event_id="event-1",
    )

    assert snapshot is not None
    assert snapshot.agent_id == "agent-1"
    assert snapshot.workspace_id == "workspace-1"
    assert snapshot.operation.kind is ModelOperationKind.TITLE
    assert snapshot.operation.current_candidate.model_selection is selection
    assert events == ["enter", "exit"]
    agent_session_repository.lock_by_id.assert_awaited_once_with(
        session,
        "session-1",
    )
    agent_repository.lock_by_id.assert_awaited_once_with(session, "agent-1")
    agent_session_repository.set_title_model_operation_state.assert_awaited_once()


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
        health_repository=AsyncMock(),
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
