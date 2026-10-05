"""Ordered Stage 1 admission/publication and FK-compatible Agent setting locks."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.engine.interfaces import ExecutionContext
from sqlalchemy.ext.asyncio import AsyncEngine
from uuid6 import uuid7

from azents.core.enums import AgentSessionProductMode, AgentSessionStatus
from azents.core.historical_memory import HistoricalMemoryCompletion
from azents.core.historical_memory_consolidation import ConsolidationWorkKind
from azents.core.model_operation import (
    ModelOperationCandidateOutcomeReason,
    mark_current_candidate_active,
)
from azents.engine.run.provider_failure import ModelProviderFailure
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.base import RDBModel
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import RDBConsolidationWork
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import AgentUpdate
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.historical_memory.preparation import (
    HistoricalMemoryPreparationRepository,
)
from azents.repos.historical_memory.repository_test import (
    _NOW,
    _create_source,
    _operation,
    _SourceFixture,
)
from azents.repos.historical_memory_consolidation.enrollment import (
    enroll_source_in_session,
)
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.testing.committed_fixture_cleanup import committed_fixture_graph


@dataclasses.dataclass(frozen=True)
class _Case:
    manager: SessionManager[WriteSession]
    source: _SourceFixture


@pytest_asyncio.fixture
async def case(rdb_engine: AsyncEngine, latest_db_schema: None) -> AsyncIterator[_Case]:
    """Use committed synthetic rows and independent transaction connections."""
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    async with committed_fixture_graph(rdb_engine, RDBModel.metadata):
        async with manager() as session:
            source = await _create_source(
                session,
                slug=f"source-order-{uuid7().hex}",
                activity_at=_NOW,
                product_mode=AgentSessionProductMode.USER,
            )
            row = RDBHistoricalMemorySource(
                source_session_id=source.session_id, admitted_at=_NOW
            )
            row.model_operation_state = mark_current_candidate_active(
                _operation(),
                reason=ModelOperationCandidateOutcomeReason.SELECTED,
                recorded_at=_NOW,
            ).model_dump(mode="json")
            session.write_session.add(row)
        yield _Case(manager=manager, source=source)


def _completion(case: _Case) -> HistoricalMemoryCompletion:
    return HistoricalMemoryCompletion(
        source_activity_at=_NOW,
        source_tail_event_id=case.source.event_id,
        prepared_at=_NOW,
        source_title_snapshot="Prepared title",
        summary="Captured provider response",
    )


async def _invoke(
    case: _Case,
    session: WriteSession,
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    historical = HistoricalMemoryRepository(case.manager)
    if operation == "publish":
        return await historical.publish_completed_in_session(
            session,
            source_session_id=case.source.session_id,
            completion=_completion(case),
        )
    if operation == "admission":
        return await historical.lock_preparation_admission_in_session(
            session,
            source_session_id=case.source.session_id,
            attempted_at=_NOW,
            inactive_before=_NOW,
        )

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        yield session

    async def select(_session: WriteSession, **kwargs: object) -> object:
        return SimpleNamespace(operation=kwargs["operation"])

    monkeypatch.setattr(
        "azents.repos.historical_memory.preparation.select_model_operation_candidate",
        select,
    )
    health = AsyncMock(spec=ModelCandidateHealthRepository)
    health.renew_quota_in_session.return_value = SimpleNamespace(server_time=_NOW)
    repository = HistoricalMemoryPreparationRepository(
        historical_repository=historical,
        agent_repository=AgentRepository(),
        health_repository=health,
        active_capabilities_repository=AsyncMock(
            spec=ActiveModelCapabilitiesRepository
        ),
        session_manager=manager,
    )
    if operation == "begin":
        return await repository.begin_next(
            agent_id=case.source.agent_id,
            attempted_at=_NOW,
            inactive_before=_NOW,
        )
    assert operation in {"advance", "quota"}
    failure = AsyncMock(spec=ModelProviderFailure)
    # An unrelated captured route still uses ordered fresh admission but retains
    # the existing refusal outcome, with no quota health or source mutation.
    failure.route_integration = "different-route"
    failure.route_provider = "different-route"
    failure.route_model = "different-route"
    if operation == "quota":
        selected = _operation().current_candidate.model_selection
        failure.route_integration = selected.llm_provider_integration_id
        failure.route_provider = selected.provider.value
        failure.route_model = selected.model_identifier
    return await repository.advance_after_quota(
        source_session_id=case.source.session_id,
        failure=failure,
        attempted_at=_NOW,
        inactive_before=_NOW,
    )


async def _wait_for_blocker(engine: AsyncEngine, *, waiter: int, holder: int) -> None:
    async with engine.connect() as observer:
        while not await observer.scalar(
            sa.text("SELECT :holder = ANY(pg_blocking_pids(:waiter))"),
            {"holder": holder, "waiter": waiter},
        ):
            pass


async def _pid(session: WriteSession) -> int:
    value = await session.read_session.scalar(sa.text("SELECT pg_backend_pid()"))
    assert isinstance(value, int)
    return value


async def _lock_participant(
    case: _Case, session: WriteSession, participant: str, *, nowait: bool
) -> None:
    """Hold one exact writer row on an independent PostgreSQL connection."""
    match participant:
        case "agent":
            statement = sa.select(RDBAgent.id).where(
                RDBAgent.id == case.source.agent_id
            )
        case "membership":
            statement = sa.select(RDBWorkspaceUser.id).where(
                RDBWorkspaceUser.workspace_id == case.source.workspace_id,
                RDBWorkspaceUser.user_id == case.source.associated_user_id,
            )
        case "root":
            statement = sa.select(RDBAgentSession.id).where(
                RDBAgentSession.id == case.source.session_id
            )
        case "source":
            statement = sa.select(RDBHistoricalMemorySource.source_session_id).where(
                RDBHistoricalMemorySource.source_session_id == case.source.session_id
            )
        case _:
            raise AssertionError(participant)
    assert (
        await session.write_session.scalar(statement.with_for_update(nowait=nowait))
        is not None
    )


@pytest.mark.parametrize("operation", ["admission", "publish"])
@pytest.mark.parametrize("participant", ["membership", "root", "source"])
async def test_each_participant_wait_preserves_same_source_outcome(
    case: _Case,
    rdb_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    participant: str,
) -> None:
    """Current grant/root/source writers cause a wait, not lost progress."""
    task: asyncio.Task[object] | None = None
    waiter_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:
        async with case.manager() as holder:
            await _lock_participant(case, holder, participant, nowait=False)
            holder_pid = await _pid(holder)

            async def invoke() -> object:
                async with case.manager() as session:
                    waiter_pid.set_result(await _pid(session))
                    return await _invoke(case, session, operation, monkeypatch)

            task = asyncio.create_task(invoke())
            pid = await asyncio.wait_for(waiter_pid, timeout=5)
            await asyncio.wait_for(
                _wait_for_blocker(rdb_engine, waiter=pid, holder=holder_pid), timeout=5
            )
            assert not task.done()
            if participant == "membership":
                await _lock_participant(case, holder, "root", nowait=True)
            if participant in {"membership", "root"}:
                await _lock_participant(case, holder, "source", nowait=True)
                # A grant/root owner can enroll work while Stage 1 owns Agent.
                await holder.write_session.scalar(
                    sa.select(RDBAgent.id)
                    .where(RDBAgent.id == case.source.agent_id)
                    .with_for_update(read=True, key_share=True, nowait=True)
                )
            await holder.write_session.commit()
        assert await asyncio.wait_for(task, timeout=5) is not None
        stored = await HistoricalMemoryRepository(case.manager).get(
            case.source.session_id
        )
        assert stored is not None
        assert stored.failure_count == 0
        assert stored.next_retry_at is None
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("participant", ["agent", "membership", "root", "source"])
async def test_wait_cancellation_rolls_back_every_acquired_participant(
    case: _Case,
    rdb_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    participant: str,
) -> None:
    """Cancellation leaves no partial authority fence or prepared publication."""
    task: asyncio.Task[object] | None = None
    waiter_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:
        async with case.manager() as holder:
            await _lock_participant(case, holder, participant, nowait=False)
            holder_pid = await _pid(holder)

            async def invoke() -> object:
                async with case.manager() as session:
                    waiter_pid.set_result(await _pid(session))
                    return await _invoke(case, session, "publish", monkeypatch)

            task = asyncio.create_task(invoke())
            pid = await asyncio.wait_for(waiter_pid, timeout=5)
            await asyncio.wait_for(
                _wait_for_blocker(rdb_engine, waiter=pid, holder=holder_pid), timeout=5
            )
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
            for target in ("agent", "membership", "root", "source"):
                await _lock_participant(case, holder, target, nowait=True)
        stored = await HistoricalMemoryRepository(case.manager).get(
            case.source.session_id
        )
        assert stored is not None
        assert stored.summary is None
        assert stored.prepared_at is None
        assert stored.failure_count == 0
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "operation", ["admission", "begin", "advance", "quota", "publish"]
)
async def test_stage_one_locks_exact_participants_in_explicit_order(
    case: _Case,
    rdb_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """Every Stage 1 entry acquires Agent/grant/root/source, never a joined lock."""
    locks: list[str] = []

    def observe(
        _connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: ExecutionContext,
        _executemany: bool,
    ) -> None:
        if "FOR " in statement:
            locks.append(statement)

    event.listen(rdb_engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with case.manager() as session:
            await _invoke(case, session, operation, monkeypatch)
    finally:
        event.remove(rdb_engine.sync_engine, "before_cursor_execute", observe)
    participant_locks = [
        statement
        for statement in locks
        if any(
            f"FROM {table} " in statement or f"FROM {table}\n" in statement
            for table in (
                "agents",
                "workspace_users",
                "agent_sessions",
                "historical_memory_sources",
            )
        )
    ]
    assert len(participant_locks) == 4
    for statement, table in zip(
        participant_locks,
        ("agents", "workspace_users", "agent_sessions", "historical_memory_sources"),
        strict=True,
    ):
        assert f"FROM {table}" in statement
        assert "JOIN" not in statement
        assert "NOWAIT" not in statement
    assert "FOR NO KEY UPDATE" in participant_locks[0]
    assert all("FOR UPDATE" in statement for statement in participant_locks[1:])


@pytest.mark.parametrize(
    "operation", ["admission", "begin", "advance", "quota", "publish"]
)
async def test_agent_wait_holds_no_root_or_source_lock(
    case: _Case,
    rdb_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """The Agent owner can finish root/source work while Stage 1 waits."""
    task: asyncio.Task[object] | None = None
    waiter_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:
        async with case.manager() as holder:
            await holder.write_session.scalar(
                sa.select(RDBAgent)
                .where(RDBAgent.id == case.source.agent_id)
                .with_for_update()
            )
            holder_pid = await _pid(holder)

            async def invoke() -> object:
                async with case.manager() as session:
                    waiter_pid.set_result(await _pid(session))
                    return await _invoke(case, session, operation, monkeypatch)

            task = asyncio.create_task(invoke())
            pid = await asyncio.wait_for(waiter_pid, timeout=5)
            await asyncio.wait_for(
                _wait_for_blocker(rdb_engine, waiter=pid, holder=holder_pid), timeout=5
            )
            assert not task.done()
            # Former source-first admission/joined publication can already own
            # these rows when waiting for Agent, closing the inverse writer cycle.
            await holder.write_session.scalar(
                sa.select(RDBAgentSession)
                .where(RDBAgentSession.id == case.source.session_id)
                .with_for_update(nowait=True)
            )
            await holder.write_session.scalar(
                sa.select(RDBHistoricalMemorySource)
                .where(
                    RDBHistoricalMemorySource.source_session_id
                    == case.source.session_id
                )
                .with_for_update(nowait=True)
            )
            await holder.write_session.commit()
        result = await asyncio.wait_for(task, timeout=5)
        assert (result is None) == (operation in {"advance", "quota"})
        if operation == "quota":
            stored = await HistoricalMemoryRepository(case.manager).get(
                case.source.session_id
            )
            assert stored is not None
            assert stored.failure_count == 1
            assert stored.last_failure_code == "candidate_chain_exhausted"
            assert stored.next_retry_at is not None
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("operation", ["admission", "publish"])
@pytest.mark.parametrize("changed", ["disabled", "archived", "grant_removed", "retry"])
async def test_waiter_rechecks_current_authority_and_progress(
    case: _Case,
    rdb_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    changed: str,
) -> None:
    """Preloaded ORM rows/routing observations cannot survive committed denial."""
    task: asyncio.Task[object] | None = None
    waiter_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:
        async with case.manager() as holder:
            await holder.write_session.scalar(
                sa.select(RDBAgent)
                .where(RDBAgent.id == case.source.agent_id)
                .with_for_update()
            )
            holder_pid = await _pid(holder)

            async def invoke() -> object:
                async with case.manager() as session:
                    # Seed all ORM identities before the competing commit.
                    preloaded = (
                        await session.read_session.get(RDBAgent, case.source.agent_id),
                        await session.read_session.get(
                            RDBAgentSession, case.source.session_id
                        ),
                        await session.read_session.get(
                            RDBHistoricalMemorySource, case.source.session_id
                        ),
                    )
                    assert all(row is not None for row in preloaded)
                    waiter_pid.set_result(await _pid(session))
                    return await _invoke(case, session, operation, monkeypatch)

            task = asyncio.create_task(invoke())
            pid = await asyncio.wait_for(waiter_pid, timeout=5)
            await asyncio.wait_for(
                _wait_for_blocker(rdb_engine, waiter=pid, holder=holder_pid), timeout=5
            )
            match changed:
                case "disabled":
                    await holder.write_session.execute(
                        sa.update(RDBAgent)
                        .where(RDBAgent.id == case.source.agent_id)
                        .values(memory_enabled=False)
                    )
                case "archived":
                    await holder.write_session.execute(
                        sa.update(RDBAgentSession)
                        .where(RDBAgentSession.id == case.source.session_id)
                        .values(status=AgentSessionStatus.ARCHIVED)
                    )
                case "grant_removed":
                    await holder.write_session.execute(
                        sa.delete(RDBWorkspaceUser).where(
                            RDBWorkspaceUser.workspace_id == case.source.workspace_id,
                            RDBWorkspaceUser.user_id == case.source.associated_user_id,
                        )
                    )
                case "retry":
                    await holder.write_session.execute(
                        sa.update(RDBHistoricalMemorySource)
                        .where(
                            RDBHistoricalMemorySource.source_session_id
                            == case.source.session_id
                        )
                        .values(next_retry_at=_NOW.replace(year=2030))
                    )
                case _:
                    raise AssertionError(changed)
            await holder.write_session.commit()
        result = await asyncio.wait_for(task, timeout=5)
        # Publication deliberately keeps existing best-effort freshness semantics:
        # a provider response is not discarded merely because retry time changed.
        assert (result is not None) == (operation == "publish" and changed == "retry")
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_memory_toggle_wait_allows_archive_enrollment_agent_fk(
    case: _Case, rdb_engine: AsyncEngine
) -> None:
    """Source-owning enrollment can complete while toggle owns the Agent guard."""
    historical = HistoricalMemoryRepository(case.manager)
    assert (
        await historical.publish_completed(
            source_session_id=case.source.session_id, completion=_completion(case)
        )
        is not None
    )
    task: asyncio.Task[None] | None = None
    waiter_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:
        async with case.manager() as holder:
            root = await holder.write_session.scalar(
                sa.select(RDBAgentSession)
                .where(RDBAgentSession.id == case.source.session_id)
                .with_for_update()
            )
            source = await holder.write_session.scalar(
                sa.select(RDBHistoricalMemorySource)
                .where(
                    RDBHistoricalMemorySource.source_session_id
                    == case.source.session_id
                )
                .with_for_update()
            )
            assert root is not None and source is not None
            original_availability = source.availability_generation
            holder_pid = await _pid(holder)

            async def toggle() -> None:
                async with case.manager() as session:
                    waiter_pid.set_result(await _pid(session))
                    result = await AgentRepository().update_by_id(
                        session,
                        case.source.agent_id,
                        AgentUpdate(memory_enabled=False),
                    )
                    assert result.success

            task = asyncio.create_task(toggle())
            pid = await asyncio.wait_for(waiter_pid, timeout=5)
            await asyncio.wait_for(
                _wait_for_blocker(rdb_engine, waiter=pid, holder=holder_pid), timeout=5
            )
            root.status = AgentSessionStatus.ARCHIVED
            source.availability_generation += 1
            # Test-only acquisition exposes exactly the KEY SHARE mode used by
            # enrollment's Agent foreign key, deterministically before INSERT.
            await holder.write_session.scalar(
                sa.select(RDBAgent.id)
                .where(RDBAgent.id == case.source.agent_id)
                .with_for_update(read=True, key_share=True, nowait=True)
            )
            work_id = await enroll_source_in_session(
                holder, source=source, root=root, kind=ConsolidationWorkKind.REMOVED
            )
            assert work_id is not None
            await holder.write_session.commit()
        await asyncio.wait_for(task, timeout=5)
        async with case.manager() as session:
            source = await session.read_session.get(
                RDBHistoricalMemorySource, case.source.session_id
            )
            assert source is not None
            assert source.availability_generation == original_availability + 2
            assert source.summary_generation == 1
            assert source.summary == "Captured provider response"
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBConsolidationWork)
                    .where(
                        RDBConsolidationWork.source_session_id
                        == case.source.session_id,
                        RDBConsolidationWork.kind == ConsolidationWorkKind.REMOVED,
                    )
                )
                == 2
            )
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
