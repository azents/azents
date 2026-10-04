"""Completed provider-output metadata operation tests."""

import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session_capabilities import ReadSession, ReadWriteSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.file_metadata_authority import FileResourceAuthority
from azents.repos.model_file import ModelFileRepository
from azents.repos.provider_output_operation import (
    ProviderOutputOperationRepository,
)


class _AuthorityRepository:
    """Record authority validation inside an active transaction."""

    def __init__(self, active: list[bool]) -> None:
        self.active = active

    async def validate(
        self,
        session: ReadSession,
        authority: FileResourceAuthority,
        *,
        lock: bool,
    ) -> bool:
        """Return valid authority while observing transaction state."""
        del session, authority, lock
        assert self.active[0]
        return True


@dataclasses.dataclass
class _OperationRepository(ProviderOutputOperationRepository):
    """Provider-output operations with a focused authority fake."""

    authority: _AuthorityRepository

    @property
    def authority_repository(self) -> _AuthorityRepository:
        """Return the focused authority validator."""
        return self.authority


async def test_provider_output_reads_close_transactions_before_returning() -> None:
    """Scope, retry, and cleanup reads return only after transaction closure."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    active = [False]
    transaction_count = 0

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        nonlocal transaction_count
        assert not active[0]
        active[0] = True
        transaction_count += 1
        try:
            yield session
        finally:
            active[0] = False

    runs = AsyncMock(spec=AgentRunRepository)
    runs.get_by_id.return_value = SimpleNamespace(session_id="session-1")
    operations = _OperationRepository(
        session_manager=session_manager,
        exchange_file_repository=AsyncMock(spec=ExchangeFileRepository),
        model_file_repository=AsyncMock(spec=ModelFileRepository),
        agent_session_repository=AsyncMock(spec=AgentSessionRepository),
        agent_run_repository=runs,
        authority=_AuthorityRepository(active),
    )
    authority = FileResourceAuthority(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        root_session_id="session-1",
        run_id="run-1",
        run_index=1,
        owner_generation=1,
    )

    assert await operations.validate_scope(authority) == "session-1"
    assert not active[0]
    assert (
        await operations.load_existing_object_keys(
            authority=authority,
            generated_images=[],
        )
        == set()
    )
    assert not active[0]
    assert (
        await operations.load_cleanup_protected_keys(
            authority=authority,
            generated_images=[],
        )
        == set()
    )
    assert not active[0]
    assert transaction_count == 3
