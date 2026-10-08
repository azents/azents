"""Completed Runtime Control read operation tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.runtime_connection_generation.repository import (
    RuntimeConnectionGenerationRepository,
)
from azents.repos.runtime_control_read import RuntimeControlReadRepository


async def test_reads_complete_their_session_before_returning() -> None:
    """Runtime and cutover snapshots return after the repository session closes."""
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

    runtime_repository = AsyncMock(spec=AgentRuntimeRepository)
    generation_repository = AsyncMock(spec=RuntimeConnectionGenerationRepository)

    async def get_runtime(current_session: WriteSession, runtime_id: str) -> None:
        assert transaction_active
        assert current_session is session
        assert runtime_id == "runtime-1"
        return None

    async def get_cutover(current_session: WriteSession) -> None:
        assert transaction_active
        assert current_session is session
        return None

    runtime_repository.get_by_id.side_effect = get_runtime
    generation_repository.get_cutover.side_effect = get_cutover
    repository = RuntimeControlReadRepository(
        session_manager=session_manager,
        runtime_repository=runtime_repository,
        generation_repository=generation_repository,
    )

    assert await repository.get_runtime("runtime-1") is None
    assert not transaction_active
    assert await repository.get_generation_cutover() is None
    assert not transaction_active
