"""Uncapped routing metadata and captured model outputs retain exact acceptance."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from azents.core.historical_memory_consolidation import ConsolidationAttemptState
from azents.engine.events.iteration import AdmittedIteration
from azents.engine.events.model_messages import TransientModelMessage
from azents.engine.events.protocols import NormalizedAdapterOutput
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.base import RDBModel
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationDraft,
    RDBConsolidationEvidence,
    RDBConsolidationModelDispatch,
    RDBConsolidationMutationReceipt,
    RDBConsolidationRevision,
    RDBConsolidationUnit,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
)
from azents.repos.historical_memory_consolidation.budget import (
    ConsolidationExecutionRepository,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.participant_types import (
    DraftParticipants,
)
from azents.repos.historical_memory_consolidation.participants import (
    prelock_participants,
    validate_participant_plan,
)
from azents.services.historical_memory.consolidation_host import (
    ConsolidationAdmission,
    ConsolidationIterationHost,
    ConsolidationPreparedTurn,
)
from azents.services.historical_memory.consolidation_host_test import (
    _host,
    _ScriptedModel,
)
from azents.testing.committed_fixture_cleanup import committed_fixture_graph
from azents.testing.consolidation import (
    consolidation_deadline,
    seed_consolidation_corpus,
)


def _manager(engine: AsyncEngine) -> SessionManager[WriteSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def manager() -> AsyncGenerator[WriteSession, None]:
        async with factory.begin() as session:
            yield ReadWriteSession(session)

    return manager


async def _wait_for_blocker(manager: SessionManager[WriteSession], pid: int) -> None:
    async with asyncio.timeout(5):
        while True:
            async with manager() as observer:
                blocked = await observer.read_session.scalar(
                    sa.text(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE datname = current_database() AND state = 'active' "
                        "AND :holder = ANY(pg_blocking_pids(pid)))"
                    ),
                    {"holder": pid},
                )
            if blocked:
                return


async def _clear_fixture_evidence(
    manager: SessionManager[WriteSession], attempt_id: str
) -> None:
    """Remove only this synthetic batch before generic graph teardown."""
    async with manager() as session:
        await session.write_session.execute(
            sa.delete(RDBConsolidationEvidence).where(
                RDBConsolidationEvidence.attempt_id == attempt_id
            )
        )


@pytest.mark.parametrize("source_count", [10100, 20000])
async def test_uncapped_exact_uuid_plan_does_not_authorize_missing_canonical_sources(
    rdb_engine: AsyncEngine, latest_db_schema: None, source_count: int
) -> None:
    """All routing IDs survive planning; actual full-manifest SQL still denies."""
    manager = _manager(rdb_engine)
    async with (
        committed_fixture_graph(rdb_engine, RDBModel.metadata),
        AsyncExitStack() as teardown,
    ):
        corpus = await seed_consolidation_corpus(manager)
        claim = await ConsolidationOwnershipRepository(manager).claim(
            corpus.team, deadline=consolidation_deadline()
        )
        assert claim is not None
        teardown.push_async_callback(
            _clear_fixture_evidence, manager, claim.principal.attempt_id
        )
        await ConsolidationDraftRepository(manager).observe(
            claim.principal, path="summary.md"
        )
        # These are body-free receipt identities only. Canonical root/source rows
        # are deliberately absent, so this fixture never supplies a Python body
        # collection or routing plan as acceptance authority.
        source_ids = tuple(f"{index + 1:032x}" for index in range(source_count))
        async with manager() as session:
            await session.write_session.execute(
                sa.insert(RDBConsolidationEvidence),
                [
                    {
                        "id": f"{source_count + index + 1:032x}",
                        "attempt_id": claim.principal.attempt_id,
                        "source_session_id": source_id,
                        "summary_generation": 1,
                        "evidence_hash": "a" * 64,
                        "availability_generation": 1,
                        "membership_grant_id": None,
                    }
                    for index, source_id in enumerate(source_ids)
                ],
            )
            attempt = await session.write_session.get(
                RDBConsolidationAttempt, claim.principal.attempt_id
            )
            assert attempt is not None
            attempt.observation_epoch += source_count
        async with manager() as session:
            plan = await prelock_participants(
                session, claim.principal, DraftParticipants(recovery=False)
            )
            assert plan.source_ids == source_ids
            assert len(plan.source_ids) == source_count
            assert plan.locked_root_ids == plan.locked_source_ids == frozenset()
            await validate_participant_plan(session, claim.principal, plan)
        with pytest.raises(ConsolidationAuthorityError, match="source is unavailable"):
            async with asyncio.timeout(15):
                await ConsolidationExecutionRepository(manager).authorize(
                    claim.principal
                )
        async with manager() as session:
            unit = await session.read_session.get(RDBConsolidationUnit, claim.unit_id)
            attempt = await session.read_session.get(
                RDBConsolidationAttempt, claim.principal.attempt_id
            )
            assert unit is not None and attempt is not None
            assert unit.active_attempt_id == claim.principal.attempt_id
            assert unit.failure_count == unit.no_progress_count == 0
            assert unit.retry_at is None
            assert attempt.state is ConsolidationAttemptState.RUNNING
            assert attempt.model_requests == attempt.tool_calls == 0
            assert attempt.finished_at is None and attempt.failure_code is None
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBConsolidationEvidence)
                    .where(RDBConsolidationEvidence.attempt_id == attempt.id)
                )
                == source_count
            )


async def test_full_host_uses_captured_response_once_after_agent_blocking(
    rdb_engine: AsyncEngine, latest_db_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One captured turn waits, then the original host publishes without replay."""
    manager = _manager(rdb_engine)
    async with committed_fixture_graph(rdb_engine, RDBModel.metadata):
        host = await _host(
            manager, personal=False, empty=False, invalid_final=False, hard_input=False
        )
        model = host.model
        assert isinstance(model, _ScriptedModel)
        captured = asyncio.Event()
        writer_locked = asyncio.Event()
        release_writer = asyncio.Event()
        pid_queue: asyncio.Queue[int] = asyncio.Queue()
        admit = ConsolidationIterationHost.admit_output
        receipt_inserts = 0

        async def paused_admission(
            self: ConsolidationIterationHost,
            prepared: ConsolidationPreparedTurn,
            output: NormalizedAdapterOutput[TransientModelMessage],
        ) -> AdmittedIteration[ConsolidationAdmission]:
            if self is host and model.turn == 1:
                captured.set()
                await writer_locked.wait()
            return await admit(self, prepared, output)

        async def writer() -> None:
            await captured.wait()
            async with manager() as session:
                await session.write_session.scalar(
                    sa.select(RDBAgent)
                    .where(RDBAgent.id == host.claim.principal.unit.agent_id)
                    .with_for_update()
                )
                pid = await session.read_session.scalar(
                    sa.select(sa.func.pg_backend_pid())
                )
                assert isinstance(pid, int)
                await pid_queue.put(pid)
                writer_locked.set()
                await release_writer.wait()

        def count_receipts(*args: object) -> None:
            nonlocal receipt_inserts
            statement = args[2]
            if isinstance(statement, str) and statement.startswith(
                "INSERT INTO historical_consolidation_mutation_receipts"
            ):
                receipt_inserts += 1

        monkeypatch.setattr(
            ConsolidationIterationHost, "admit_output", paused_admission
        )
        event.listen(rdb_engine.sync_engine, "after_cursor_execute", count_receipts)
        holder = asyncio.create_task(writer())
        execution = asyncio.create_task(host.run())
        try:
            async with asyncio.timeout(5):
                pid = await pid_queue.get()
            await _wait_for_blocker(manager, pid)
            assert not execution.done()
            assert model.turn == host.started_turns == 1
            release_writer.set()
            await holder
            async with asyncio.timeout(15):
                outcome = await execution
            assert model.turn == host.started_turns == 8
            assert model.closed and host.closed
            assert receipt_inserts == 3
            async with manager() as session:
                attempt = await session.read_session.get(
                    RDBConsolidationAttempt, host.claim.principal.attempt_id
                )
                unit = await session.read_session.get(
                    RDBConsolidationUnit, host.claim.unit_id
                )
                revision = await session.read_session.get(
                    RDBConsolidationRevision, outcome.revision_id
                )
                assert attempt is not None and unit is not None and revision is not None
                assert attempt.state is ConsolidationAttemptState.COMPLETED
                assert attempt.model_requests == 8 and attempt.tool_calls == 7
                assert attempt.input_tokens == 160 and attempt.output_tokens == 40
                assert attempt.failure_code is None
                assert unit.failure_count == unit.no_progress_count == 0
                assert unit.retry_at is None
                assert (
                    unit.published_revision_id
                    == attempt.completed_revision_id
                    == outcome.revision_id
                )
                dispatches = list(
                    await session.read_session.scalars(
                        sa.select(RDBConsolidationModelDispatch).where(
                            RDBConsolidationModelDispatch.attempt_id == attempt.id
                        )
                    )
                )
                assert len(dispatches) == 8
                assert all(row.usage_recorded for row in dispatches)
                assert (
                    await session.read_session.scalar(
                        sa.select(sa.func.count())
                        .select_from(RDBConsolidationAttempt)
                        .where(RDBConsolidationAttempt.unit_id == unit.id)
                    )
                    == 1
                )
                assert (
                    await session.read_session.scalar(
                        sa.select(sa.func.count())
                        .select_from(RDBConsolidationDraft)
                        .where(RDBConsolidationDraft.unit_id == unit.id)
                    )
                    == 0
                )
                assert (
                    await session.read_session.scalar(
                        sa.select(sa.func.count())
                        .select_from(RDBConsolidationMutationReceipt)
                        .where(RDBConsolidationMutationReceipt.attempt_id == attempt.id)
                    )
                    == 0
                )
            assert (
                await host.publication_repository.inspect_outcome(host.claim.principal)
                == outcome
            )
        finally:
            release_writer.set()
            for task in (holder, execution):
                if not task.done():
                    task.cancel()
            await asyncio.gather(holder, execution, return_exceptions=True)
            event.remove(rdb_engine.sync_engine, "after_cursor_execute", count_receipts)
