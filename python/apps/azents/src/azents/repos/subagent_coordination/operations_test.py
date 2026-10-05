"""Completed coordination snapshots use native read-only scopes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.rdb.session_capabilities import (
    ReadOnlySession,
    ReadSession,
    create_read_only_session_manager,
)
from azents.repos.subagent_coordination.data import SubagentCoordinationSnapshot
from azents.repos.subagent_coordination.operations import (
    SubagentCoordinationReadRepository,
)
from azents.repos.subagent_coordination.repository import SubagentCoordinationRepository


class _NativeReadProbe(SubagentCoordinationRepository):
    """Inspect the native scope before running the existing bounded query."""

    async def project_root_tree(
        self,
        session: ReadSession,
        *,
        current_session_id: str,
        configured_capacity: int,
    ) -> SubagentCoordinationSnapshot | None:
        assert (
            await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
            == "on"
        )
        return await super().project_root_tree(
            session,
            current_session_id=current_session_id,
            configured_capacity=configured_capacity,
        )


async def test_native_read_only_coordination_returns_detached_missing_tree(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """The native read-only operation ends before a writable pool reuse."""
    del latest_db_schema
    operations = SubagentCoordinationReadRepository(
        repository=_NativeReadProbe(),
        session_manager=create_read_only_session_manager(rdb_engine),
    )
    assert (
        await operations.project_root_tree(
            current_session_id="0" * 32, configured_capacity=3
        )
        is None
    )
    async with rdb_engine.connect() as connection:
        assert await connection.scalar(sa.text("SHOW transaction_read_only")) == "off"


async def test_coordination_failure_unwinds_owned_scope() -> None:
    """An unrelated query error is not converted to a missing snapshot."""
    active = False

    @asynccontextmanager
    async def sessions() -> AsyncIterator[ReadSession]:
        nonlocal active
        active = True
        try:
            async with AsyncSession() as session:
                yield ReadOnlySession(session)
        finally:
            active = False

    repository = AsyncMock(spec=SubagentCoordinationRepository)
    error = RuntimeError("query failed")
    repository.project_root_tree.side_effect = error
    operations = SubagentCoordinationReadRepository(
        repository=repository, session_manager=sessions
    )
    with pytest.raises(RuntimeError) as raised:
        await operations.project_root_tree(
            current_session_id="missing", configured_capacity=3
        )
    assert raised.value is error
    assert not active
