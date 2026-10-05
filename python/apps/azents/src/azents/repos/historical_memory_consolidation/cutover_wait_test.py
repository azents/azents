"""Offline page waits revalidate exact participants without replaying handover."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

import azents.repos.historical_memory_consolidation.cutover as cutover_module
from azents.core.historical_memory_cutover import (
    MemoryHandoverAction,
    MemoryHandoverRequest,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.base import RDBModel
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.historical_memory_consolidation.cutover import (
    MemoryHandoverRepository,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationClaim,
    ConsolidationOwnershipRepository,
)
from azents.testing.committed_fixture_cleanup import committed_fixture_graph
from azents.testing.consolidation import (
    ConsolidationCorpus,
    consolidation_deadline,
    seed_consolidation_corpus,
)


@dataclass(frozen=True)
class _Case:
    manager: SessionManager[WriteSession]
    engine: AsyncEngine
    corpus: ConsolidationCorpus
    claim: ConsolidationClaim


@pytest_asyncio.fixture
async def case(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncGenerator[_Case, None]:
    factory = async_sessionmaker(rdb_engine, expire_on_commit=False)

    @asynccontextmanager
    async def manager() -> AsyncGenerator[WriteSession, None]:
        async with factory.begin() as session:
            yield ReadWriteSession(session)

    async with committed_fixture_graph(rdb_engine, RDBModel.metadata):
        corpus = await seed_consolidation_corpus(manager)
        claim = await ConsolidationOwnershipRepository(manager).claim(
            corpus.team, deadline=consolidation_deadline()
        )
        assert claim is not None
        yield _Case(manager, rdb_engine, corpus, claim)


async def _wait_for_row_wait(case: _Case, table_name: str) -> None:
    """Observe PostgreSQL's actual wait rather than a scheduler timing guess."""
    async with asyncio.timeout(5):
        while True:
            async with case.manager() as observer:
                waiting = await observer.read_session.scalar(
                    sa.text(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND pid <> pg_backend_pid() "
                        "AND wait_event_type = 'Lock' AND query LIKE :pattern)"
                    ),
                    {"pattern": f"%{table_name}%"},
                )
            if waiting:
                return


def _request(*, size: int) -> MemoryHandoverRequest:
    return MemoryHandoverRequest(MemoryHandoverAction.FORWARD, True, size)


async def test_unit_page_waits_then_fences_once(case: _Case) -> None:
    async with case.manager() as holder:
        unit = await holder.write_session.scalar(
            sa.select(RDBConsolidationUnit)
            .where(RDBConsolidationUnit.id == case.claim.unit_id)
            .with_for_update()
        )
        assert unit is not None
        generation = unit.owner_generation
        task = asyncio.create_task(
            MemoryHandoverRepository(case.manager).fence_units(
                request=_request(size=1), after=None
            )
        )
        await _wait_for_row_wait(case, "historical_consolidation_units")
        assert not task.done()
    async with asyncio.timeout(5):
        result = await task
    assert result.count == 1 and result.next_cursor == case.claim.unit_id
    async with case.manager() as session:
        unit = await session.read_session.get(RDBConsolidationUnit, case.claim.unit_id)
        assert unit is not None and unit.owner_generation == generation + 1
        assert unit.active_attempt_id is None and unit.owner_token is None


async def test_post_wait_snapshot_condition_is_not_replaced_by_lock_success(
    case: _Case,
) -> None:
    async with case.manager() as holder:
        await holder.write_session.scalar(
            sa.select(RDBConsolidationUnit)
            .where(RDBConsolidationUnit.id == case.claim.unit_id)
            .with_for_update()
        )
        task = asyncio.create_task(
            MemoryHandoverRepository(case.manager).fence_units(
                request=_request(size=1), after=None
            )
        )
        await _wait_for_row_wait(case, "historical_consolidation_units")
        holder.write_session.add(
            RDBToolkitState(
                agent_id=case.corpus.team.agent_id,
                session_id=case.corpus.team_source,
                toolkit_namespace="memory",
                state_name="context_snapshot",
                schema_version=1,
                state_json={"schema_version": 1},
            )
        )
    with pytest.raises(ValueError, match="reset"):
        async with asyncio.timeout(5):
            await task
    async with case.manager() as session:
        unit = await session.read_session.get(RDBConsolidationUnit, case.claim.unit_id)
        assert unit is not None
        assert unit.owner_generation == case.claim.principal.owner_generation
        assert unit.active_attempt_id == case.claim.principal.attempt_id


@pytest.mark.parametrize("target", ["agent", "grant", "root", "source"])
async def test_source_page_cancellation_releases_partial_acquisitions(
    case: _Case, target: str
) -> None:
    async with case.manager() as holder:
        match target:
            case "agent":
                await holder.write_session.scalar(
                    sa.select(RDBAgent)
                    .where(RDBAgent.id == case.corpus.team.agent_id)
                    .with_for_update()
                )
                table = "agents"
            case "grant":
                await holder.write_session.scalar(
                    sa.select(RDBWorkspaceUser)
                    .where(
                        RDBWorkspaceUser.workspace_id
                        == case.corpus.personal.workspace_id,
                        RDBWorkspaceUser.user_id
                        == case.corpus.personal.associated_user_id,
                    )
                    .with_for_update()
                )
                table = "workspace_users"
            case "root":
                await holder.write_session.scalar(
                    sa.select(RDBAgentSession)
                    .where(RDBAgentSession.id == case.corpus.team_source)
                    .with_for_update()
                )
                table = "agent_sessions"
            case "source":
                await holder.write_session.scalar(
                    sa.select(RDBHistoricalMemorySource)
                    .where(
                        RDBHistoricalMemorySource.source_session_id
                        == case.corpus.team_source
                    )
                    .with_for_update()
                )
                table = "historical_memory_sources"
            case _:
                raise AssertionError(target)
        task = asyncio.create_task(
            MemoryHandoverRepository(case.manager).reconcile_sources(
                request=_request(size=2), after=None
            )
        )
        await _wait_for_row_wait(case, table)
        task.cancel("cancel-offline-page")
        with pytest.raises(asyncio.CancelledError, match="cancel-offline-page"):
            await task
    async with asyncio.timeout(5):
        result = await MemoryHandoverRepository(case.manager).reconcile_sources(
            request=_request(size=2), after=None
        )
    assert result.count == 2


async def test_candidate_change_replans_only_current_page(
    case: _Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    candidates = cutover_module._source_candidates

    async def observed(
        session: WriteSession, *, request: MemoryHandoverRequest, after: str | None
    ) -> tuple[cutover_module.MemorySourceHandoverCandidate, ...]:
        nonlocal calls
        calls += 1
        return await candidates(session, request=request, after=after)

    monkeypatch.setattr(cutover_module, "_source_candidates", observed)
    async with case.manager() as holder:
        await holder.write_session.scalar(
            sa.select(RDBAgent)
            .where(RDBAgent.id == case.corpus.team.agent_id)
            .with_for_update()
        )
        task = asyncio.create_task(
            MemoryHandoverRepository(case.manager).reconcile_sources(
                request=_request(size=1), after=None
            )
        )
        await _wait_for_row_wait(case, "agents")
        await holder.write_session.execute(
            sa.delete(RDBHistoricalMemorySource).where(
                RDBHistoricalMemorySource.source_session_id == case.corpus.team_source
            )
        )
    async with asyncio.timeout(5):
        result = await task
    assert result.count == 1 and result.next_cursor == case.corpus.personal_source
    assert calls == 4
    async with case.manager() as session:
        unit = await session.read_session.get(RDBConsolidationUnit, case.claim.unit_id)
        assert unit is not None
        assert unit.owner_generation == case.claim.principal.owner_generation
        assert unit.active_attempt_id == case.claim.principal.attempt_id


async def test_source_page_refreshes_disabled_agent_after_wait(case: _Case) -> None:
    async with case.manager() as session:
        await session.write_session.execute(
            sa.delete(RDBConsolidationWork).where(
                RDBConsolidationWork.agent_id == case.corpus.team.agent_id
            )
        )
    async with case.manager() as holder:
        agent = await holder.write_session.scalar(
            sa.select(RDBAgent)
            .where(RDBAgent.id == case.corpus.team.agent_id)
            .with_for_update()
        )
        assert agent is not None
        task = asyncio.create_task(
            MemoryHandoverRepository(case.manager).reconcile_sources(
                request=_request(size=2), after=None
            )
        )
        await _wait_for_row_wait(case, "agents")
        agent.memory_enabled = False
    async with asyncio.timeout(5):
        result = await task
    assert result.count == 2
    async with case.manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBConsolidationWork)
                .where(RDBConsolidationWork.agent_id == case.corpus.team.agent_id)
            )
            == 0
        )


async def test_source_page_locks_in_explicit_agent_grant_root_source_order(
    case: _Case,
) -> None:
    locked_statements: list[str] = []

    def capture(*args: object) -> None:
        statement = args[2]
        assert isinstance(statement, str)
        if "FOR UPDATE" in statement or "FOR NO KEY UPDATE" in statement:
            locked_statements.append(statement)

    event.listen(case.engine.sync_engine, "before_cursor_execute", capture)
    try:
        await MemoryHandoverRepository(case.manager).reconcile_sources(
            request=_request(size=2), after=None
        )
    finally:
        event.remove(case.engine.sync_engine, "before_cursor_execute", capture)
    assert len(locked_statements) == 4
    assert "FROM agents" in locked_statements[0]
    assert "FOR NO KEY UPDATE" in locked_statements[0]
    assert "FROM workspace_users" in locked_statements[1]
    assert "FROM agent_sessions" in locked_statements[2]
    assert "FROM historical_memory_sources" in locked_statements[3]
    assert all("NOWAIT" not in statement for statement in locked_statements)
