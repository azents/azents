"""Completed Session History operation tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
)
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.message import MessageRepository
from azents.repos.session_history.operations import (
    SessionHistoryOperationRepository,
)
from azents.repos.session_history.repository import (
    SearchPage,
    SessionHistoryRepository,
    SessionHistoryScope,
    SessionSearchHit,
)
from azents.repos.workspace_user import WorkspaceUserRepository


async def test_session_history_search_closes_transaction_before_returning() -> None:
    """Authorized History search returns after its repository transaction closes."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    transaction_active = False

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        nonlocal transaction_active
        assert not transaction_active
        transaction_active = True
        try:
            yield session
        finally:
            transaction_active = False

    agent_sessions = AsyncMock(spec=AgentSessionRepository)
    users = AsyncMock(spec=WorkspaceUserRepository)
    history = AsyncMock(spec=SessionHistoryRepository)
    messages = AsyncMock(spec=MessageRepository)
    root = SimpleNamespace(
        id="session-1",
        status=AgentSessionStatus.ACTIVE,
        session_kind=AgentSessionKind.ROOT,
        product_mode=AgentSessionProductMode.TEAM,
        associated_user_id=None,
        agent_id="agent-1",
        workspace_id="workspace-1",
    )

    async def get_session(
        current_session: WriteSession,
        session_id: str,
    ) -> object:
        assert transaction_active
        assert current_session is session
        assert session_id == "session-1"
        return root

    async def search_roots(
        current_session: WriteSession,
        *,
        scope: SessionHistoryScope,
        query: str,
        limit: int,
        before: tuple[datetime.datetime, str] | None,
    ) -> SearchPage[SessionSearchHit]:
        assert transaction_active
        assert current_session is session
        assert query == ""
        assert limit == 10
        assert before is None
        assert scope.agent_id == "agent-1"
        return SearchPage(items=[], has_more=False)

    agent_sessions.get_by_id.side_effect = get_session
    history.search_roots.side_effect = search_roots
    operations = SessionHistoryOperationRepository(
        session_manager=session_manager,
        agent_session_repository=agent_sessions,
        workspace_user_repository=users,
        history_repository=history,
        message_repository=messages,
    )

    page = await operations.search_roots(
        agent_id="agent-1",
        current_session_id="session-1",
        query="",
        limit=10,
        before=None,
    )

    assert page.items == []
    assert not transaction_active
