"""Historical Memory candidate preparation repository tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionProductMode
from azents.core.historical_memory import HistoricalMemoryDueSource
from azents.core.model_operation import ModelOperationKind
from azents.repos.historical_memory import HistoricalMemoryPreparationAdmission
from azents.repos.historical_memory.preparation import (
    HistoricalMemoryPreparationRepository,
)

_NOW = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.UTC)


async def test_begin_next_freezes_lightweight_candidate_and_source_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Candidate selection and source capture commit in one DB-only transaction."""
    session = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        yield session

    source = HistoricalMemoryDueSource(
        source_session_id="s" * 32,
        agent_id="a" * 32,
        workspace_id="w" * 32,
        source_activity_at=_NOW - datetime.timedelta(hours=7),
        source_tail_event_id="e" * 32,
        source_title="Prior work",
        admitted_at=_NOW - datetime.timedelta(hours=1),
        prepared_at=None,
        completed_source_activity_at=None,
        next_retry_at=None,
        failure_count=0,
        model_operation_state=None,
    )
    admission = HistoricalMemoryPreparationAdmission(
        source=source,
        product_mode=AgentSessionProductMode.TEAM,
        associated_user_id=None,
    )
    historical = Mock()
    historical.list_due_for_agent_in_session = AsyncMock(return_value=[source])
    historical.lock_preparation_admission_in_session = AsyncMock(return_value=admission)
    historical.lock_preparation_membership_in_session = AsyncMock(return_value=True)
    prepared = SimpleNamespace(source_session_id="s" * 32)
    historical.persist_preparation_operation_in_session = AsyncMock(
        return_value=prepared
    )
    option = SimpleNamespace(label="lightweight")
    agent = SimpleNamespace(
        id="a" * 32,
        workspace_id="w" * 32,
        memory_enabled=True,
        lightweight_model_label="lightweight",
        selectable_model_options=[option],
    )
    agent_repository = Mock()
    agent_repository.lock_by_id = AsyncMock(return_value=agent)
    agent_repository.get_by_id = AsyncMock()
    operation = SimpleNamespace(
        kind=ModelOperationKind.HISTORICAL_MEMORY,
        semantic_label="lightweight",
        terminal_reason=None,
    )
    build = Mock(return_value=operation)
    selection = SimpleNamespace(operation=operation)
    select_candidate = AsyncMock(return_value=selection)
    monkeypatch.setattr(
        "azents.repos.historical_memory.preparation.build_model_operation",
        build,
    )
    monkeypatch.setattr(
        "azents.repos.historical_memory.preparation.select_model_operation_candidate",
        select_candidate,
    )
    repository = HistoricalMemoryPreparationRepository(
        historical_repository=historical,
        agent_repository=agent_repository,
        health_repository=Mock(),
        session_manager=session_manager,
    )

    result = await repository.begin_next(
        agent_id="a" * 32,
        attempted_at=_NOW,
        inactive_before=_NOW - datetime.timedelta(hours=6),
    )

    assert result is prepared
    agent_repository.lock_by_id.assert_awaited_once_with(session, "a" * 32)
    agent_repository.get_by_id.assert_not_awaited()
    build.assert_called_once()
    select_candidate.assert_awaited_once()
    historical.persist_preparation_operation_in_session.assert_awaited_once_with(
        session,
        admission,
        attempted_at=_NOW,
        operation=operation,
    )
    session.commit.assert_awaited_once()
