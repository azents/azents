"""Completed replay transaction boundaries before broker effects."""

import dataclasses
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.session_execution.cutover_replay import CutoverReplayCandidateBatch
from azents.repos.session_execution.cutover_replay_data import (
    TeamSessionCutoverReplayInvariantFailure,
)
from azents.repos.session_execution.cutover_replay_operations import (
    TeamSessionCutoverReplayOperationsRepository,
)
from azents.services.team_session_cutover_replay_test import (
    _Broker,
    _candidate,
    _CanonicalRepository,
    _ReplayRepository,
    _snapshot,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", [False, True])
async def test_fence_settles_whole_transaction_before_return(drift: bool) -> None:
    """One rejected member rolls back the batch before caller-side effects."""
    trace: list[str] = []

    class Session:
        async def commit(self) -> None:
            trace.append("commit")

        async def rollback(self) -> None:
            trace.append("rollback")

    @asynccontextmanager
    async def manager() -> AsyncGenerator[WriteSession, None]:
        trace.append("enter")
        try:
            yield ReadWriteSession(cast(AsyncSession, Session()))
        finally:
            trace.append("exit")

    candidate = _candidate()
    canonical = _snapshot()
    if drift:
        canonical = dataclasses.replace(canonical, recoverable_run_id="changed-run")
    operations = TeamSessionCutoverReplayOperationsRepository(
        replay_repository=_ReplayRepository(
            CutoverReplayCandidateBatch(
                candidates=(candidate,), next_session_cursor=None
            )
        ),
        canonical_execution_repository=_CanonicalRepository(
            {candidate.session_id: canonical}
        ),
        session_manager=manager,
    )
    if drift:
        with pytest.raises(TeamSessionCutoverReplayInvariantFailure):
            await operations.fence_replay_batch((candidate,))
        assert trace == ["enter", "rollback", "exit"]
    else:
        await operations.fence_replay_batch((candidate,))
        assert trace == ["enter", "commit", "exit"]
    broker = _Broker()
    if not drift:
        await broker.purge_session_state(candidate.session_id)
        trace.append("broker")
        assert trace == ["enter", "commit", "exit", "broker"]
