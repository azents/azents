"""Narrow completed Exchange publication recovery database error boundary."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session_capabilities import ReadOnlySession, ReadSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.exchange_file.operations import (
    ExchangeFileOperationRepository,
    ExchangeFilePublicationRecoveryError,
)
from azents.repos.workspace_user import WorkspaceUserRepository


@pytest.mark.parametrize(
    "error",
    [SQLAlchemyError("failed"), RuntimeError("unexpected"), asyncio.CancelledError()],
)
async def test_recovery_closes_scope_and_translates_only_database_failure(
    error: BaseException,
) -> None:
    """SQL failure is typed, while unexpected failures and cancellation propagate."""
    active = False
    raw = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def read_manager() -> AsyncIterator[ReadSession]:
        nonlocal active
        active = True
        try:
            yield ReadOnlySession(raw)
        finally:
            active = False

    async def unexpected_write_manager() -> AsyncIterator[ReadSession]:
        raise AssertionError("Recovery must use independently injected reads.")
        yield ReadOnlySession(raw)

    files = AsyncMock(spec=ExchangeFileRepository)
    files.get_by_id.side_effect = error
    operations = ExchangeFileOperationRepository(
        exchange_file_repository=files,
        agent_repository=AsyncMock(spec=AgentRepository),
        agent_session_repository=AsyncMock(spec=AgentSessionRepository),
        agent_run_repository=AsyncMock(spec=AgentRunRepository),
        workspace_user_repository=AsyncMock(spec=WorkspaceUserRepository),
        session_manager=AsyncMock(side_effect=unexpected_write_manager),
        read_session_manager=read_manager,
    )
    expected = (
        ExchangeFilePublicationRecoveryError
        if isinstance(error, SQLAlchemyError)
        else type(error)
    )
    with pytest.raises(expected) as caught:
        await operations.load_publication_for_recovery(file_id="publication")
    assert not active
    if isinstance(error, SQLAlchemyError):
        assert caught.value.__cause__ is error
    else:
        assert caught.value is error
