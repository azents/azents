"""Real contention retries only a rolled-back local operation in the same claim."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from uuid6 import uuid7

from azents.core.historical_memory_consolidation import (
    ConsolidationAttemptState,
    ConsolidationDisposition,
)
from azents.core.historical_memory_publication import (
    ConsolidationCoverage,
    ConsolidationWorkDisposition,
    validate_consolidation_overview,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.base import RDBModel
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationDraft,
    RDBConsolidationModelDispatch,
    RDBConsolidationMutationReceipt,
    RDBConsolidationRevision,
    RDBConsolidationUnit,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
    ConsolidationDeadlineError,
    database_now,
)
from azents.repos.historical_memory_consolidation.budget import (
    ConsolidationExecutionRepository,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
    DraftFileChange,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationClaim,
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.publication import (
    ConsolidationPublicationRepository,
)
from azents.repos.historical_memory_consolidation.recovery import (
    ConsolidationRecoveryRepository,
)
from azents.repos.historical_memory_consolidation.sources import (
    ConsolidationSourceRepository,
)
from azents.repos.historical_memory_consolidation.work import (
    ConsolidationWorkRepository,
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
    corpus: ConsolidationCorpus
    claim: ConsolidationClaim


@dataclass
class _LockWaitBarrier:
    observations: int = 0

    async def observe(
        self, manager: SessionManager[WriteSession], holder: WriteSession
    ) -> None:
        """Observe the exact held backend as a PostgreSQL lock blocker."""
        pid = await holder.read_session.scalar(sa.select(sa.func.pg_backend_pid()))
        assert isinstance(pid, int)
        async with asyncio.timeout(3):
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
                    self.observations += 1
                    return


@pytest.fixture
def contention() -> _LockWaitBarrier:
    return _LockWaitBarrier()


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
        await ConsolidationSourceRepository(manager).read(
            claim.principal,
            source_session_id=corpus.team_source,
            offset=0,
            max_bytes=12000,
        )
        await ConsolidationDraftRepository(manager).observe(
            claim.principal, path="summary.md"
        )
        yield _Case(manager, corpus, claim)


async def _assert_running(case: _Case) -> None:
    async with case.manager() as session:
        unit = await session.read_session.get(RDBConsolidationUnit, case.claim.unit_id)
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, case.claim.principal.attempt_id
        )
        assert unit is not None and attempt is not None
        assert attempt.state is ConsolidationAttemptState.RUNNING
        assert attempt.failure_code is None and attempt.finished_at is None
        assert unit.active_attempt_id == attempt.id
        assert unit.owner_generation == case.claim.principal.owner_generation
        assert unit.failure_count == 0 and unit.no_progress_count == 0
        assert unit.retry_at is None
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBConsolidationAttempt)
                .where(RDBConsolidationAttempt.unit_id == unit.id)
            )
            == 1
        )


@pytest.mark.parametrize(
    "operation",
    [
        "authorize",
        "renew",
        "prepare",
        "retire",
        "page",
        "source_read",
        "source_inventory",
        "observe",
        "inventory",
        "reserve_model",
        "reserve_tools",
        "replay_receipt",
    ],
)
async def test_writer_release_continues_same_claim_without_failure_or_backoff(
    case: _Case, contention: _LockWaitBarrier, operation: str
) -> None:
    principal = case.claim.principal
    drafts = ConsolidationDraftRepository(case.manager)
    budget = ConsolidationExecutionRepository(case.manager)

    async def invoke() -> object:
        match operation:
            case "authorize":
                return await budget.authorize(principal)
            case "renew":
                return await ConsolidationOwnershipRepository(case.manager).renew(
                    principal
                )
            case "prepare":
                return await ConsolidationRecoveryRepository(case.manager).prepare(
                    principal
                )
            case "retire":
                return await ConsolidationWorkRepository(
                    case.manager
                ).retire_obsolete_pending(principal)
            case "page":
                return await ConsolidationWorkRepository(case.manager).page(
                    principal, after_sequence=None, limit=50
                )
            case "source_read":
                return await ConsolidationSourceRepository(case.manager).read(
                    principal,
                    source_session_id=case.corpus.team_source,
                    offset=0,
                    max_bytes=12000,
                )
            case "source_inventory":
                return await ConsolidationSourceRepository(case.manager).inventory(
                    principal, after=None, limit=50, source_id_prefix=None
                )
            case "observe":
                return await drafts.observe(principal, path="summary.md")
            case "inventory":
                return await drafts.inventory(principal)
            case "reserve_model":
                return await budget.reserve_model(
                    principal, dispatch_id="d" * 32, input_tokens=1, output_tokens=None
                )
            case "reserve_tools":
                return await budget.reserve_tools(principal, count=1)
            case "replay_receipt":
                return await drafts.replay_receipt(
                    principal, tool_call_id="unseen", request_digest="b" * 64
                )
            case _:
                raise AssertionError(operation)

    async with case.manager() as holder:
        await holder.write_session.scalar(
            sa.select(RDBAgent)
            .where(RDBAgent.id == principal.unit.agent_id)
            .with_for_update()
        )
        task = asyncio.create_task(invoke())
        async with asyncio.timeout(3):
            await contention.observe(case.manager, holder)
        assert not task.done()
    async with asyncio.timeout(3):
        await task
    assert contention.observations == 1
    await _assert_running(case)


async def test_mutation_receipt_and_model_observation_commit_once_after_manifest_retry(
    case: _Case, contention: _LockWaitBarrier
) -> None:
    drafts = ConsolidationDraftRepository(case.manager)
    observation = await drafts.observe(case.claim.principal, path="summary.md")
    budget = ConsolidationExecutionRepository(case.manager)
    dispatch_id = uuid7().hex
    physical_calls = 0

    async def invoke_once() -> None:
        nonlocal physical_calls
        await budget.reserve_model(
            case.claim.principal,
            dispatch_id=dispatch_id,
            input_tokens=1,
            output_tokens=None,
        )
        physical_calls += 1
        await drafts.mutate(
            case.claim.principal,
            tool_call_id="same-call",
            request_digest="b" * 64,
            expected_draft_revision_id=observation.draft_revision_id,
            expected_observation_epoch=observation.observation_epoch,
            changes=[
                DraftFileChange(
                    "summary.md",
                    observation.file_revision_id,
                    "Completed generated text",
                )
            ],
        )

    # Complete external work once, then deliberately contend only its local commit.
    async with case.manager() as holder:
        await holder.write_session.scalar(
            sa.select(RDBHistoricalMemorySource)
            .where(
                RDBHistoricalMemorySource.source_session_id == case.corpus.team_source
            )
            .with_for_update()
        )
        task = asyncio.create_task(invoke_once())
        async with asyncio.timeout(3):
            await contention.observe(case.manager, holder)
    async with asyncio.timeout(3):
        await task
    assert physical_calls == 1
    async with case.manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBConsolidationModelDispatch)
                .where(
                    RDBConsolidationModelDispatch.attempt_id
                    == case.claim.principal.attempt_id
                )
            )
            == 1
        )
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBConsolidationMutationReceipt)
                .where(
                    RDBConsolidationMutationReceipt.attempt_id
                    == case.claim.principal.attempt_id
                )
            )
            == 1
        )
    await _assert_running(case)


@pytest.mark.parametrize("change", ["cancel", "replace_owner", "disable", "expired"])
async def test_retry_cannot_continue_after_cancellation_revocation_or_expiry(
    case: _Case, contention: _LockWaitBarrier, change: str
) -> None:
    async with case.manager() as holder:
        await holder.write_session.scalar(
            sa.select(RDBAgent)
            .where(RDBAgent.id == case.corpus.team.agent_id)
            .with_for_update()
        )
        task = asyncio.create_task(
            ConsolidationExecutionRepository(case.manager).authorize(
                case.claim.principal
            )
        )
        async with asyncio.timeout(3):
            await contention.observe(case.manager, holder)
        if change == "disable":
            await holder.write_session.execute(
                sa.update(RDBAgent)
                .where(RDBAgent.id == case.corpus.team.agent_id)
                .values(memory_enabled=False)
            )
        if change == "cancel":
            task.cancel("shutdown-during-db-retry")
            with pytest.raises(
                asyncio.CancelledError, match="shutdown-during-db-retry"
            ):
                await task
        if change in {"replace_owner", "expired"}:
            async with case.manager() as session:
                unit = await session.write_session.get(
                    RDBConsolidationUnit, case.claim.unit_id
                )
                assert unit is not None
                if change == "replace_owner":
                    unit.owner_token = "x" * 32
                else:
                    unit.lease_until = await database_now(session) - datetime.timedelta(
                        seconds=1
                    )
    if change != "cancel":
        with pytest.raises(ConsolidationAuthorityError):
            async with asyncio.timeout(3):
                await task
    async with case.manager() as session:
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, case.claim.principal.attempt_id
        )
        assert attempt is not None and attempt.model_requests == 0
        assert attempt.state is ConsolidationAttemptState.RUNNING


async def test_heartbeat_extension_while_busy_does_not_freeze_original_lease(
    case: _Case, contention: _LockWaitBarrier
) -> None:
    async with case.manager() as session:
        unit = await session.write_session.get(RDBConsolidationUnit, case.claim.unit_id)
        assert unit is not None
        original_lease = await database_now(session) + datetime.timedelta(seconds=0.3)
        unit.lease_until = original_lease
    async with case.manager() as holder:
        await holder.write_session.scalar(
            sa.select(RDBHistoricalMemorySource)
            .where(
                RDBHistoricalMemorySource.source_session_id == case.corpus.team_source
            )
            .with_for_update()
        )
        task = asyncio.create_task(
            ConsolidationExecutionRepository(case.manager).authorize(
                case.claim.principal
            )
        )
        async with asyncio.timeout(3):
            await contention.observe(case.manager, holder)
        # Participant acquisition waits before unit ownership, so an independent
        # heartbeat must be able to renew without waiting for this source writer.
        async with asyncio.timeout(1):
            renewed = await ConsolidationOwnershipRepository(case.manager).renew(
                case.claim.principal
            )
        assert renewed > original_lease
        remaining = (
            original_lease - datetime.datetime.now(datetime.UTC)
        ).total_seconds()
        # This wait verifies the real lease-time boundary, not scheduling order.
        await asyncio.sleep(max(0, remaining) + 0.02)
    async with asyncio.timeout(3):
        await task
    await _assert_running(case)


async def test_initial_unit_wait_is_bounded_before_locked_owner_admission(
    case: _Case,
) -> None:
    async with case.manager() as session:
        attempt = await session.write_session.get(
            RDBConsolidationAttempt, case.claim.principal.attempt_id
        )
        assert attempt is not None
        attempt.deadline_at = await database_now(session) + datetime.timedelta(
            seconds=0.15
        )
    async with case.manager() as holder:
        await holder.write_session.scalar(
            sa.select(RDBConsolidationUnit)
            .where(RDBConsolidationUnit.id == case.claim.unit_id)
            .with_for_update()
        )
        with pytest.raises(ConsolidationDeadlineError):
            async with asyncio.timeout(3):
                await ConsolidationExecutionRepository(case.manager).authorize(
                    case.claim.principal
                )
    await _assert_running(case)


async def test_terminal_settlement_waits_for_unit_then_preserves_exact_owner(
    case: _Case,
    contention: _LockWaitBarrier,
) -> None:
    async with case.manager() as holder:
        await holder.write_session.scalar(
            sa.select(RDBConsolidationUnit)
            .where(RDBConsolidationUnit.id == case.claim.unit_id)
            .with_for_update()
        )
        task = asyncio.create_task(
            ConsolidationOwnershipRepository(case.manager).fail(
                case.claim.principal, failure_code=None, cancelled=False
            )
        )
        await contention.observe(case.manager, holder)
        assert not task.done()
    async with asyncio.timeout(3):
        await task
    async with case.manager() as session:
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, case.claim.principal.attempt_id
        )
        unit = await session.read_session.get(RDBConsolidationUnit, case.claim.unit_id)
        assert attempt is not None and unit is not None
        assert attempt.state is ConsolidationAttemptState.FAILED
        assert attempt.failure_code is None and attempt.finished_at is not None
        assert unit.failure_count == 1 and unit.active_attempt_id is None


@pytest.mark.parametrize("ending", ["release", "cancel", "deadline"])
async def test_initial_claim_retries_only_before_unchanged_absolute_deadline(
    case: _Case, contention: _LockWaitBarrier, ending: str
) -> None:
    key = case.corpus.personal
    deadline = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        seconds=0.2 if ending == "deadline" else 5
    )
    async with case.manager() as holder:
        await holder.write_session.scalar(
            sa.select(RDBAgent).where(RDBAgent.id == key.agent_id).with_for_update()
        )
        task = asyncio.create_task(
            ConsolidationOwnershipRepository(case.manager).claim(key, deadline=deadline)
        )
        async with asyncio.timeout(3):
            await contention.observe(case.manager, holder)
        if ending == "cancel":
            task.cancel("cancel-initial-claim")
            with pytest.raises(asyncio.CancelledError, match="cancel-initial-claim"):
                await task
        elif ending == "deadline":
            with pytest.raises(ConsolidationDeadlineError):
                async with asyncio.timeout(3):
                    await task
    result = await task if ending == "release" else None
    async with case.manager() as session:
        count = await session.read_session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBConsolidationAttempt)
            .join(RDBConsolidationUnit)
            .where(RDBConsolidationUnit.associated_user_id == key.associated_user_id)
        )
        assert count == (1 if ending == "release" else 0)
        if result is not None:
            attempt = await session.read_session.get(
                RDBConsolidationAttempt, result.principal.attempt_id
            )
            assert attempt is not None and attempt.deadline_at == deadline
            assert attempt.state is ConsolidationAttemptState.RUNNING
            assert result.principal.owner_generation == 1
    await _assert_running(case)


async def test_publication_retries_frozen_result_without_repeating_authorship(
    case: _Case, contention: _LockWaitBarrier
) -> None:
    principal = case.claim.principal
    work = ConsolidationWorkRepository(case.manager)
    drafts = ConsolidationDraftRepository(case.manager)
    page = await work.page(principal, after_sequence=None, limit=50)
    coverage = ConsolidationCoverage(
        dispositions=tuple(
            ConsolidationWorkDisposition(
                work_id=entry.work_id,
                action=ConsolidationDisposition.CONSIDERED,
                reason="Prepared exact work",
            )
            for entry in page.entries
        )
    )
    summary = await drafts.observe(principal, path="summary.md")
    journal = await drafts.observe(principal, path="coverage.json")
    markdown = (
        "## Historical Context\nGenerated once.\n\n## Source Routes\n"
        f"- azents://memory/historical/team/{case.corpus.team_source}/summary.md"
        " — Source\n"
    )
    await drafts.mutate(
        principal,
        tool_call_id="author-once",
        request_digest="c" * 64,
        expected_draft_revision_id=summary.draft_revision_id,
        expected_observation_epoch=summary.observation_epoch,
        changes=[
            DraftFileChange("summary.md", summary.file_revision_id, markdown),
            DraftFileChange(
                "coverage.json", journal.file_revision_id, coverage.model_dump_json()
            ),
        ],
    )
    publication = ConsolidationPublicationRepository(
        session_manager=case.manager, read_session_manager=case.manager
    )
    frozen = await publication.freeze(principal)
    await work.record_coverage(
        principal,
        expected_draft_revision_id=frozen.revision_id,
        coverage=frozen.coverage,
    )
    async with case.manager() as holder:
        await holder.write_session.scalar(
            sa.select(RDBHistoricalMemorySource)
            .where(
                RDBHistoricalMemorySource.source_session_id == case.corpus.team_source
            )
            .with_for_update()
        )
        task = asyncio.create_task(
            publication.publish(
                principal,
                expected_draft_revision_id=frozen.revision_id,
                expected_observation_epoch=frozen.observation_epoch,
                overview=validate_consolidation_overview(
                    key=principal.unit, markdown=markdown
                ),
            )
        )
        async with asyncio.timeout(3):
            await contention.observe(case.manager, holder)
    async with asyncio.timeout(3):
        result = await task
    async with case.manager() as session:
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, principal.attempt_id
        )
        unit = await session.read_session.get(RDBConsolidationUnit, case.claim.unit_id)
        draft = await session.read_session.scalar(
            sa.select(RDBConsolidationDraft).where(
                RDBConsolidationDraft.unit_id == case.claim.unit_id
            )
        )
        revision = await session.read_session.get(
            RDBConsolidationRevision, result.revision_id
        )
        assert draft is None
        assert revision is not None and revision.markdown == frozen.markdown
        assert revision.attempt_id == principal.attempt_id
        assert attempt is not None and unit is not None
        assert attempt.state is ConsolidationAttemptState.COMPLETED
        assert attempt.completed_revision_id == result.revision_id
        assert attempt.failure_code is None
        assert unit.failure_count == unit.no_progress_count == 0
        assert (
            unit.retry_at is None and unit.published_revision_id == result.revision_id
        )
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBConsolidationRevision)
                .where(RDBConsolidationRevision.attempt_id == principal.attempt_id)
            )
            == 1
        )
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBConsolidationMutationReceipt)
                .where(
                    RDBConsolidationMutationReceipt.attempt_id == principal.attempt_id
                )
            )
            == 0
        )
