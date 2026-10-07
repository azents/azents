"""Submission authority, exact change settlement and broker-owned recovery tests."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine
from uuid6 import uuid7

from azents.core.enums import AgentRunStatus, AgentSessionRunState, AgentSessionStatus
from azents.core.historical_memory_consolidation import (
    ConsolidationWorkKind,
    FreshMemoryAdmission,
    MemoryExecutionAuthorityError,
    MemoryExecutionPrincipal,
    MemorySubmissionUncertainError,
)
from azents.core.historical_memory_publication import MemorySubmissionError
from azents.core.historical_memory_system_setting import HistoricalMemoryExecutionConfig
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.base import RDBModel
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_execution import (
    RDBMemoryExecution,
    RDBMemoryUnit,
    RDBMemoryWork,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunPatch
from azents.repos.historical_memory.locking_order_test import _pid, _wait_for_blocker
from azents.repos.historical_memory_consolidation.enrollment import (
    enroll_source_in_session,
)
from azents.repos.historical_memory_consolidation.execution import (
    MemoryExecutionRepository,
)
from azents.repos.historical_memory_consolidation.work import enroll_memory_work
from azents.repos.session_execution_file import SessionExecutionFileRepository
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.testing.committed_fixture_cleanup import committed_fixture_graph
from azents.testing.consolidation import (
    ConsolidationCorpus,
    consolidation_deadline,
    memory_execution_repository,
    seed_consolidation_corpus,
)


@dataclasses.dataclass(frozen=True)
class _Case:
    manager: SessionManager[WriteSession]
    repository: MemoryExecutionRepository
    corpus: ConsolidationCorpus
    principal: MemoryExecutionPrincipal


async def _start(manager: SessionManager[WriteSession]) -> _Case:
    corpus = await seed_consolidation_corpus(manager)
    repository = memory_execution_repository(manager)
    binding = await repository.ensure_execution(
        corpus.team,
        admission=FreshMemoryAdmission(
            consolidation_deadline(),
            HistoricalMemoryExecutionConfig(max_turns=2),
        ),
    )
    assert binding is not None
    async with manager() as session:
        generation = await SessionExecutionRecordRepository().claim_owner_generation(
            session, binding.session_id
        )
    principal = await repository.open_run(
        binding, SessionExecutionOwner(binding.session_id, generation)
    )
    await repository.provision_inputs(principal)
    return _Case(manager, repository, corpus, principal)


async def test_last_allowed_turn_submit_settles_only_admitted_work(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A correctable error retains the execution and its final-turn authority."""
    case = await _start(rdb_session_manager)
    principal = case.principal
    await case.repository.start_turn(principal)
    await case.repository.start_turn(principal)
    with pytest.raises(MemoryExecutionAuthorityError, match="turn limit"):
        await case.repository.start_turn(principal)
    files = SessionExecutionFileRepository(case.manager)
    await files.write(
        principal.owner, "result.md", "x" * 10001, None, True, overwrite=False
    )
    with pytest.raises(MemorySubmissionError):
        await case.repository.submit(
            principal, tool_call_id="wrong", authored_path="result.md"
        )
    await files.write(
        principal.owner,
        "result.md",
        "Corrected integrated body",
        "x" * 10001,
        True,
        overwrite=True,
    )
    async with case.manager() as session:
        late = await enroll_memory_work(
            session,
            case.corpus.team,
            source_session_id=case.corpus.team_source,
            kind=ConsolidationWorkKind.PREPARED,
        )
    accepted = await case.repository.submit(
        principal, tool_call_id="final-turn", authored_path="result.md"
    )
    assert accepted.settled_work_count == 1
    assert (
        await case.repository.inspect_accepted(
            principal.owner.session_id, tool_call_id="wrong"
        )
        is None
    )
    assert (
        await case.repository.submit(
            principal, tool_call_id="final-turn", authored_path="result.md"
        )
        == accepted
    )
    with pytest.raises(PermissionError):
        await files.write(
            principal.owner, "late.md", "must not write", None, True, overwrite=False
        )
    async with case.manager() as session:
        pending = list(
            await session.read_session.scalars(
                sa.select(RDBMemoryWork).where(
                    RDBMemoryWork.unit_id == principal.binding.unit_id
                )
            )
        )
        assert [work.id for work in pending] == [late]
        assert pending[0].admitted_session_id is None
        run = await session.read_session.get(RDBAgentRun, principal.run_id)
        current = await session.read_session.get(
            RDBAgentSession, principal.owner.session_id
        )
        assert run is not None and run.status is AgentRunStatus.COMPLETED
        assert current is not None and current.run_state is AgentSessionRunState.IDLE


async def test_two_connection_owner_handover_fences_waiting_submission(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A submission queued behind common ownership cannot commit after handover."""
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    async with committed_fixture_graph(rdb_engine, RDBModel.metadata):
        case = await _start(manager)
        principal = case.principal
        await case.repository.start_turn(principal)
        await SessionExecutionFileRepository(manager).write(
            principal.owner,
            "result.md",
            "Unaccepted authored body",
            None,
            True,
            overwrite=False,
        )
        waiter_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

        @asynccontextmanager
        async def observed_manager() -> AsyncIterator[WriteSession]:
            async with manager() as session:
                if not waiter_pid.done():
                    waiter_pid.set_result(await _pid(session))
                yield session

        observed = dataclasses.replace(
            case.repository, session_manager=observed_manager
        )
        task: asyncio.Task[object] | None = None
        try:
            async with manager() as holder:
                assert (
                    await SessionExecutionRecordRepository().fence_owner(
                        holder, principal.owner
                    )
                    is not None
                )
                holder_pid = await _pid(holder)
                task = asyncio.create_task(
                    observed.submit(
                        principal, tool_call_id="stale-call", authored_path="result.md"
                    )
                )
                pid = await asyncio.wait_for(waiter_pid, timeout=5)
                await asyncio.wait_for(
                    _wait_for_blocker(rdb_engine, waiter=pid, holder=holder_pid),
                    timeout=5,
                )
                new_generation = (
                    await SessionExecutionRecordRepository().claim_owner_generation(
                        holder, principal.owner.session_id
                    )
                )
            with pytest.raises(MemoryExecutionAuthorityError):
                await asyncio.wait_for(task, timeout=5)
            assert await case.repository.current_result(case.corpus.team) is None
            replacement = await case.repository.recover_worker_execution(
                principal.binding,
                SessionExecutionOwner(principal.owner.session_id, new_generation),
            )
            assert replacement is not None
            assert replacement.session_id != principal.owner.session_id
            assert replacement.started_turns == 1
            assert replacement.deadline_at == principal.binding.deadline_at
            assert replacement.execution_policy == principal.binding.execution_policy
            async with manager() as session:
                old = await session.read_session.get(RDBAgentRun, principal.run_id)
                assert old is not None and old.status is AgentRunStatus.CANCELLED
                work = list(
                    await session.read_session.scalars(
                        sa.select(RDBMemoryWork).where(
                            RDBMemoryWork.unit_id == principal.binding.unit_id
                        )
                    )
                )
                assert len(work) == 1 and work[0].admitted_session_id is None
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def test_exhausted_worker_recovery_is_terminal_and_retains_pending_work(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Deadline exhaustion closes the old common Run and schedules bounded retry."""
    case = await _start(rdb_session_manager)
    async with case.manager() as session:
        execution = await session.write_session.get(
            RDBMemoryExecution, case.principal.owner.session_id
        )
        assert execution is not None
        execution.deadline_at = datetime.datetime.now(
            datetime.UTC
        ) - datetime.timedelta(seconds=1)
        generation = await SessionExecutionRecordRepository().claim_owner_generation(
            session, execution.session_id
        )
    assert (
        await case.repository.recover_worker_execution(
            case.principal.binding,
            SessionExecutionOwner(case.principal.owner.session_id, generation),
        )
        is None
    )
    assert (
        await case.repository.ensure_execution(
            case.corpus.team,
            admission=FreshMemoryAdmission(
                consolidation_deadline(), HistoricalMemoryExecutionConfig(max_turns=2)
            ),
        )
        is None
    )
    async with case.manager() as session:
        unit = await session.read_session.get(
            RDBMemoryUnit, case.principal.binding.unit_id
        )
        run = await session.read_session.get(RDBAgentRun, case.principal.run_id)
        assert unit is not None and unit.active_session_id is None
        assert unit.failure_count == 1 and unit.retry_at is not None
        assert run is not None and run.status is AgentRunStatus.CANCELLED
        work = list(
            await session.read_session.scalars(
                sa.select(RDBMemoryWork).where(RDBMemoryWork.unit_id == unit.id)
            )
        )
        assert len(work) == 1 and work[0].admitted_session_id is None


async def test_first_worker_start_and_terminal_signal_never_reopen_a_run(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Only a genuinely unstarted private Session can take the first-start path."""
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    repository = memory_execution_repository(rdb_session_manager)
    binding = await repository.ensure_execution(
        corpus.team,
        admission=FreshMemoryAdmission(
            consolidation_deadline(), HistoricalMemoryExecutionConfig(max_turns=2)
        ),
    )
    assert binding is not None
    async with rdb_session_manager() as session:
        generation = await SessionExecutionRecordRepository().claim_owner_generation(
            session, binding.session_id
        )
    owner = SessionExecutionOwner(binding.session_id, generation)
    assert await repository.recover_worker_execution(binding, owner) == binding
    principal = await repository.open_run(binding, owner)
    assert await repository.open_run(binding, owner) == principal
    await repository.finish_unaccepted(principal, status=AgentRunStatus.FAILED)
    assert await repository.recover_worker_execution(binding, owner) is None
    with pytest.raises(MemoryExecutionAuthorityError):
        await repository.open_run(binding, owner)


async def test_missing_removed_source_is_admitted_without_agent_action_ledger(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A server removal survives source purge while ineligible positive work remains."""
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    repository = memory_execution_repository(rdb_session_manager)
    async with rdb_session_manager() as session:
        removed_id = await enroll_memory_work(
            session,
            corpus.team,
            source_session_id=uuid7().hex,
            kind=ConsolidationWorkKind.REMOVED,
        )
        ineligible_id = await enroll_memory_work(
            session,
            corpus.team,
            source_session_id=uuid7().hex,
            kind=ConsolidationWorkKind.PREPARED,
        )
    binding = await repository.ensure_execution(
        corpus.team,
        admission=FreshMemoryAdmission(
            consolidation_deadline(), HistoricalMemoryExecutionConfig(max_turns=2)
        ),
    )
    assert binding is not None
    async with rdb_session_manager() as session:
        generation = await SessionExecutionRecordRepository().claim_owner_generation(
            session, binding.session_id
        )
    principal = await repository.open_run(
        binding, SessionExecutionOwner(binding.session_id, generation)
    )
    provided = await repository.provision_inputs(principal)
    assert len(provided.files) == 1
    assert removed_id not in provided.files[0].content
    await SessionExecutionFileRepository(rdb_session_manager).write(
        principal.owner,
        "result.md",
        "Integrated current corpus",
        None,
        True,
        overwrite=False,
    )
    accepted = await repository.submit(
        principal, tool_call_id="remove-aware", authored_path="result.md"
    )
    assert accepted.settled_work_count == 2
    async with rdb_session_manager() as session:
        assert await session.read_session.get(RDBMemoryWork, removed_id) is None
        remaining = await session.read_session.get(RDBMemoryWork, ineligible_id)
        assert remaining is not None and remaining.admitted_session_id is None


async def test_lost_commit_ack_resolves_original_call_after_later_publication(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Resolve the original accepted scalar instead of inferring from current text."""
    case = await _start(rdb_session_manager)
    files = SessionExecutionFileRepository(case.manager)
    await files.write(
        case.principal.owner, "first.md", "First result", None, True, overwrite=False
    )

    @asynccontextmanager
    async def lost_ack_manager() -> AsyncIterator[WriteSession]:
        async with case.manager() as session:
            yield session
        raise DBAPIError(
            "COMMIT",
            None,
            RuntimeError("Commit acknowledgement was lost."),
            connection_invalidated=True,
        )

    uncertain = dataclasses.replace(case.repository, session_manager=lost_ack_manager)
    with pytest.raises(MemorySubmissionUncertainError):
        await uncertain.submit(
            case.principal, tool_call_id="first-exact-call", authored_path="first.md"
        )
    original = await case.repository.inspect_accepted(
        case.principal.owner.session_id, tool_call_id="first-exact-call"
    )
    assert original is not None
    async with case.manager() as session:
        await enroll_memory_work(
            session,
            case.corpus.team,
            source_session_id=case.corpus.team_source,
            kind=ConsolidationWorkKind.PREPARED,
        )
    second_binding = await case.repository.ensure_execution(
        case.corpus.team,
        admission=FreshMemoryAdmission(
            consolidation_deadline(), HistoricalMemoryExecutionConfig(max_turns=2)
        ),
    )
    assert second_binding is not None
    async with case.manager() as session:
        generation = await SessionExecutionRecordRepository().claim_owner_generation(
            session, second_binding.session_id
        )
    second = await case.repository.open_run(
        second_binding, SessionExecutionOwner(second_binding.session_id, generation)
    )
    await case.repository.provision_inputs(second)
    await files.write(
        second.owner, "second.md", "Different later result", None, True, overwrite=False
    )
    newer = await case.repository.submit(
        second, tool_call_id="second-exact-call", authored_path="second.md"
    )
    assert newer.session_id != original.session_id
    assert newer.rendered_bytes != original.rendered_bytes
    current = await case.repository.current_result(case.corpus.team)
    assert current is not None and current.markdown == "Different later result"
    assert (
        await case.repository.inspect_accepted(
            case.principal.owner.session_id, tool_call_id="first-exact-call"
        )
        == original
    )
    assert (
        await case.repository.submit(
            case.principal, tool_call_id="first-exact-call", authored_path="first.md"
        )
        == original
    )
    assert (
        await case.repository.inspect_accepted(
            case.principal.owner.session_id, tool_call_id="second-exact-call"
        )
        is None
    )


async def test_terminal_crash_cleanup_preserves_successor_routing(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Recover leftover associations, then ignore retired predecessor signals."""
    case = await _start(rdb_session_manager)
    async with case.manager() as session:
        await AgentRunRepository().update(
            session,
            case.principal.run_id,
            AgentRunPatch(status=AgentRunStatus.FAILED),
        )
        generation = await SessionExecutionRecordRepository().claim_owner_generation(
            session, case.principal.owner.session_id
        )
    recovered_owner = SessionExecutionOwner(case.principal.owner.session_id, generation)
    assert (
        await case.repository.recover_worker_execution(
            case.principal.binding, recovered_owner
        )
        is None
    )
    async with case.manager() as session:
        unit = await session.write_session.get(
            RDBMemoryUnit, case.principal.binding.unit_id
        )
        assert unit is not None and unit.active_session_id is None
        assert unit.failure_count == 1
        current = await session.read_session.get(
            RDBAgentSession, case.principal.owner.session_id
        )
        assert current is not None and current.run_state is AgentSessionRunState.IDLE
        work = list(
            await session.read_session.scalars(
                sa.select(RDBMemoryWork).where(RDBMemoryWork.unit_id == unit.id)
            )
        )
        assert len(work) == 1 and work[0].admitted_session_id is None
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBMemoryExecution)
                .where(RDBMemoryExecution.unit_id == unit.id)
            )
            == 1
        )
        unit.retry_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            seconds=1
        )
    successor = await case.repository.ensure_execution(
        case.corpus.team,
        admission=FreshMemoryAdmission(
            consolidation_deadline(), HistoricalMemoryExecutionConfig(max_turns=2)
        ),
    )
    assert successor is not None
    assert (
        await case.repository.recover_worker_execution(
            case.principal.binding, recovered_owner
        )
        is None
    )
    async with case.manager() as session:
        unit = await session.read_session.get(
            RDBMemoryUnit, case.principal.binding.unit_id
        )
        assert unit is not None and unit.active_session_id == successor.session_id
        assert unit.failure_count == 1


async def test_source_archive_enrollment_can_finish_while_provision_waits(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Unit locks admit enrollment while rechecking source authority after waiting."""
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    async with committed_fixture_graph(rdb_engine, RDBModel.metadata):
        corpus = await seed_consolidation_corpus(manager)
        repository = memory_execution_repository(manager)
        binding = await repository.ensure_execution(
            corpus.team,
            admission=FreshMemoryAdmission(
                consolidation_deadline(), HistoricalMemoryExecutionConfig(max_turns=2)
            ),
        )
        assert binding is not None
        async with manager() as session:
            generation = (
                await SessionExecutionRecordRepository().claim_owner_generation(
                    session, binding.session_id
                )
            )
        principal = await repository.open_run(
            binding, SessionExecutionOwner(binding.session_id, generation)
        )
        waiter_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

        @asynccontextmanager
        async def observed_manager() -> AsyncIterator[WriteSession]:
            async with manager() as session:
                if not waiter_pid.done():
                    waiter_pid.set_result(await _pid(session))
                yield session

        observed = dataclasses.replace(repository, session_manager=observed_manager)
        task: asyncio.Task[object] | None = None
        try:
            async with manager() as holder:
                root = await holder.write_session.scalar(
                    sa.select(RDBAgentSession)
                    .where(RDBAgentSession.id == corpus.team_source)
                    .with_for_update(of=RDBAgentSession)
                )
                source = await holder.write_session.get(
                    RDBHistoricalMemorySource, corpus.team_source, with_for_update=True
                )
                assert root is not None and source is not None
                holder_pid = await _pid(holder)
                provision = asyncio.create_task(observed.provision_inputs(principal))
                task = provision
                pid = await asyncio.wait_for(waiter_pid, timeout=5)
                await asyncio.wait_for(
                    _wait_for_blocker(rdb_engine, waiter=pid, holder=holder_pid),
                    timeout=5,
                )
                root.status = AgentSessionStatus.ARCHIVED
                work_id = await enroll_source_in_session(
                    holder, source=source, root=root, kind=ConsolidationWorkKind.REMOVED
                )
                assert work_id is not None
            provided = await asyncio.wait_for(provision, timeout=5)
            assert not provided.files
            async with manager() as session:
                work = list(
                    await session.read_session.scalars(
                        sa.select(RDBMemoryWork).where(
                            RDBMemoryWork.unit_id == binding.unit_id
                        )
                    )
                )
                assert len(work) == 2
                assert all(
                    row.admitted_session_id == binding.session_id for row in work
                )
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
