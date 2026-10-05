"""Participant waits precede unit ownership and never authorize stale discovery."""

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

import azents.repos.historical_memory_consolidation.authority as authority_module
from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.base import RDBModel
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationDraft,
    RDBConsolidationDraftFile,
    RDBConsolidationEvidence,
    RDBConsolidationUnit,
)
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, ReadWriteSession, WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
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
from azents.repos.historical_memory_consolidation.participants import (
    ConsolidationParticipantPlan,
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
    create_consolidation_source,
    seed_consolidation_corpus,
)


@dataclass(frozen=True)
class _Database:
    manager: SessionManager[WriteSession]
    corpus: ConsolidationCorpus


@pytest_asyncio.fixture
async def database(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncGenerator[_Database, None]:
    factory = async_sessionmaker(rdb_engine, expire_on_commit=False)

    @asynccontextmanager
    async def manager() -> AsyncGenerator[WriteSession, None]:
        async with factory.begin() as session:
            yield ReadWriteSession(session)

    async with committed_fixture_graph(rdb_engine, RDBModel.metadata):
        corpus = await seed_consolidation_corpus(manager)
        yield _Database(manager, corpus)


async def _wait_for_blocked_backend(
    manager: SessionManager[WriteSession], holder: WriteSession
) -> None:
    """Wait until PostgreSQL reports this held transaction as a real blocker."""
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
                return


async def _claim(database: _Database, *, personal: bool) -> ConsolidationClaim:
    result = await ConsolidationOwnershipRepository(database.manager).claim(
        database.corpus.personal if personal else database.corpus.team,
        deadline=consolidation_deadline(),
    )
    assert result is not None
    return result


async def _add_team_source(database: _Database, *, title: str) -> str:
    async with database.manager() as session:
        return await create_consolidation_source(
            session,
            manager=database.manager,
            key=database.corpus.team,
            title=title,
            summary="Prepared exact new source",
        )


async def _assert_same_claim(database: _Database, claim: ConsolidationClaim) -> None:
    async with database.manager() as session:
        unit = await session.read_session.get(RDBConsolidationUnit, claim.unit_id)
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, claim.principal.attempt_id
        )
        assert unit is not None and attempt is not None
        assert unit.active_attempt_id == claim.principal.attempt_id
        assert unit.owner_token == claim.principal.owner_token
        assert unit.owner_generation == claim.principal.owner_generation
        assert unit.retry_at is None
        assert unit.failure_count == unit.no_progress_count == 0
        assert attempt.finished_at is None and attempt.failure_code is None
        assert attempt.model_requests == 0


async def _establish_draft(database: _Database, claim: ConsolidationClaim) -> str:
    await ConsolidationSourceRepository(database.manager).read(
        claim.principal,
        source_session_id=database.corpus.team_source,
        offset=0,
        max_bytes=12000,
    )
    drafts = ConsolidationDraftRepository(database.manager)
    observed = await drafts.observe(claim.principal, path="summary.md")
    mutation = await drafts.mutate(
        claim.principal,
        tool_call_id="establish-derived-draft",
        request_digest="a" * 64,
        expected_draft_revision_id=observed.draft_revision_id,
        expected_observation_epoch=observed.observation_epoch,
        changes=[
            DraftFileChange(
                "summary.md", observed.file_revision_id, "Source-dependent prose"
            )
        ],
    )
    return mutation.draft_revision_id


@pytest.mark.parametrize("participant", ["root", "source"])
async def test_first_source_exposure_waits_before_unit_and_heartbeat_renews_live_lease(
    database: _Database, participant: str
) -> None:
    """A source absent from the old manifest still has exact pre-unit protection."""
    claim = await _claim(database, personal=False)
    async with database.manager() as session:
        unit = await session.write_session.get(RDBConsolidationUnit, claim.unit_id)
        assert unit is not None
        original_lease = await database_now(session) + datetime.timedelta(seconds=0.3)
        unit.lease_until = original_lease
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBConsolidationEvidence)
                .where(
                    RDBConsolidationEvidence.attempt_id == claim.principal.attempt_id
                )
            )
            == 0
        )
    async with database.manager() as holder:
        if participant == "root":
            statement = sa.select(RDBAgentSession).where(
                RDBAgentSession.id == database.corpus.team_source
            )
        else:
            statement = sa.select(RDBHistoricalMemorySource).where(
                RDBHistoricalMemorySource.source_session_id
                == database.corpus.team_source
            )
        await holder.write_session.scalar(statement.with_for_update())
        reading = asyncio.create_task(
            ConsolidationSourceRepository(database.manager).read(
                claim.principal,
                source_session_id=database.corpus.team_source,
                offset=0,
                max_bytes=12000,
            )
        )
        await _wait_for_blocked_backend(database.manager, holder)
        assert not reading.done()
        async with asyncio.timeout(1):
            renewed = await ConsolidationOwnershipRepository(database.manager).renew(
                claim.principal
            )
        assert renewed > original_lease
        remaining = (
            original_lease - datetime.datetime.now(datetime.UTC)
        ).total_seconds()
        # Only this wall-clock wait tests the actual elapsed lease contract.
        await asyncio.sleep(max(0, remaining) + 0.02)
    async with asyncio.timeout(3):
        result = await reading
    assert result.version.source_session_id == database.corpus.team_source
    await _assert_same_claim(database, claim)


async def test_waiting_manifest_replans_after_new_exposure_changes_epoch(
    database: _Database,
) -> None:
    extra = await _add_team_source(database, title="New influence")
    claim = await _claim(database, personal=False)
    await _establish_draft(database, claim)
    async with database.manager() as holder:
        await holder.write_session.scalar(
            sa.select(RDBHistoricalMemorySource)
            .where(
                RDBHistoricalMemorySource.source_session_id
                == database.corpus.team_source
            )
            .with_for_update()
        )
        authorizing = asyncio.create_task(
            ConsolidationExecutionRepository(database.manager).authorize(
                claim.principal
            )
        )
        await _wait_for_blocked_backend(database.manager, holder)
        async with asyncio.timeout(2):
            exposed = await ConsolidationSourceRepository(database.manager).read(
                claim.principal, source_session_id=extra, offset=0, max_bytes=12000
            )
        assert exposed.version.source_session_id == extra
        assert not authorizing.done()
    async with asyncio.timeout(3):
        await authorizing
    async with database.manager() as session:
        ids = set(
            await session.read_session.scalars(
                sa.select(RDBConsolidationEvidence.source_session_id).where(
                    RDBConsolidationEvidence.attempt_id == claim.principal.attempt_id
                )
            )
        )
        assert ids == {database.corpus.team_source, extra}
    await _assert_same_claim(database, claim)


async def test_waiting_manifest_replans_after_serialized_draft_revision_change(
    database: _Database,
) -> None:
    claim = await _claim(database, personal=False)
    original = await _establish_draft(database, claim)
    replacement = uuid7().hex
    async with database.manager() as holder:
        await holder.write_session.scalar(
            sa.select(RDBHistoricalMemorySource)
            .where(
                RDBHistoricalMemorySource.source_session_id
                == database.corpus.team_source
            )
            .with_for_update()
        )
        authorizing = asyncio.create_task(
            ConsolidationExecutionRepository(database.manager).authorize(
                claim.principal
            )
        )
        await _wait_for_blocked_backend(database.manager, holder)
        async with database.manager() as writer:
            unit = await writer.write_session.scalar(
                sa.select(RDBConsolidationUnit)
                .where(RDBConsolidationUnit.id == claim.unit_id)
                .with_for_update()
            )
            assert unit is not None and unit.owner_token == claim.principal.owner_token
            # A serialized metadata revision change exercises the planning anchor,
            # not a second provider/tool operation or acceptance of new prose.
            await writer.write_session.execute(
                sa.update(RDBConsolidationDraft)
                .where(RDBConsolidationDraft.unit_id == claim.unit_id)
                .values(revision_id=replacement)
            )
        assert not authorizing.done()
    async with asyncio.timeout(3):
        await authorizing
    assert original != replacement
    async with database.manager() as session:
        revision = await session.read_session.scalar(
            sa.select(RDBConsolidationDraft.revision_id).where(
                RDBConsolidationDraft.unit_id == claim.unit_id
            )
        )
        assert revision == replacement
    await _assert_same_claim(database, claim)


@pytest.mark.parametrize("page_kind", ["inventory", "work"])
async def test_page_lookahead_is_prelocked_but_not_exposed_as_receipt(
    database: _Database, page_kind: str
) -> None:
    lookahead = await _add_team_source(database, title="Lookahead source")
    claim = await _claim(database, personal=False)
    async with database.manager() as holder:
        await holder.write_session.scalar(
            sa.select(RDBHistoricalMemorySource)
            .where(RDBHistoricalMemorySource.source_session_id == lookahead)
            .with_for_update()
        )
        if page_kind == "inventory":
            task = asyncio.create_task(
                ConsolidationSourceRepository(database.manager).inventory(
                    claim.principal,
                    after=None,
                    limit=1,
                    source_id_prefix=None,
                )
            )
        else:
            task = asyncio.create_task(
                ConsolidationWorkRepository(database.manager).page(
                    claim.principal,
                    after_sequence=None,
                    limit=1,
                )
            )
        await _wait_for_blocked_backend(database.manager, holder)
        assert not task.done()
        async with asyncio.timeout(1):
            await ConsolidationOwnershipRepository(database.manager).renew(
                claim.principal
            )
    async with asyncio.timeout(3):
        page = await task
    assert len(page.entries) == 1
    assert page.entries[0].version.source_session_id == database.corpus.team_source
    async with database.manager() as session:
        ids = set(
            await session.read_session.scalars(
                sa.select(RDBConsolidationEvidence.source_session_id).where(
                    RDBConsolidationEvidence.attempt_id == claim.principal.attempt_id
                )
            )
        )
        assert ids == {database.corpus.team_source}
    await _assert_same_claim(database, claim)


@pytest.mark.parametrize("page_kind", ["inventory", "work"])
async def test_changed_lookahead_replans_and_locks_its_replacement_before_exposure(
    database: _Database, page_kind: str
) -> None:
    disappearing = await _add_team_source(database, title="Original lookahead")
    replacement = await _add_team_source(database, title="Replacement lookahead")
    claim = await _claim(database, personal=False)
    async with database.manager() as replacement_holder:
        await replacement_holder.write_session.scalar(
            sa.select(RDBHistoricalMemorySource)
            .where(RDBHistoricalMemorySource.source_session_id == replacement)
            .with_for_update()
        )
        async with database.manager() as first_holder:
            await first_holder.write_session.scalar(
                sa.select(RDBAgentSession)
                .where(RDBAgentSession.id == disappearing)
                .with_for_update()
            )
            if page_kind == "inventory":
                task = asyncio.create_task(
                    ConsolidationSourceRepository(database.manager).inventory(
                        claim.principal,
                        after=None,
                        limit=1,
                        source_id_prefix=None,
                    )
                )
            else:
                task = asyncio.create_task(
                    ConsolidationWorkRepository(database.manager).page(
                        claim.principal, after_sequence=None, limit=1
                    )
                )
            await _wait_for_blocked_backend(database.manager, first_holder)
            await AgentSessionRepository().archive(
                first_holder,
                disappearing,
                ended_at=datetime.datetime.now(datetime.UTC),
            )
        # The refreshed page must not return until its new lookahead is also
        # serialized, even though that source was outside the original page.
        await _wait_for_blocked_backend(database.manager, replacement_holder)
        assert not task.done()
        async with asyncio.timeout(1):
            await ConsolidationOwnershipRepository(database.manager).renew(
                claim.principal
            )
    async with asyncio.timeout(3):
        result = await task
    assert len(result.entries) == 1
    assert result.entries[0].version.source_session_id == database.corpus.team_source
    async with database.manager() as session:
        exposed = set(
            await session.read_session.scalars(
                sa.select(RDBConsolidationEvidence.source_session_id).where(
                    RDBConsolidationEvidence.attempt_id == claim.principal.attempt_id
                )
            )
        )
        assert exposed == {database.corpus.team_source}
    await _assert_same_claim(database, claim)


@pytest.mark.parametrize("loss", ["archived", "missing"])
async def test_recovery_rebuilds_denied_or_missing_influence_without_perpetual_replan(
    database: _Database, loss: str
) -> None:
    claim = await _claim(database, personal=False)
    original_revision = await _establish_draft(database, claim)
    async with database.manager() as writer:
        if loss == "archived":
            await AgentSessionRepository().archive(
                writer,
                database.corpus.team_source,
                ended_at=datetime.datetime.now(datetime.UTC),
            )
        else:
            await writer.write_session.execute(
                sa.delete(RDBHistoricalMemorySource).where(
                    RDBHistoricalMemorySource.source_session_id
                    == database.corpus.team_source
                )
            )
    async with asyncio.timeout(3):
        result = await ConsolidationRecoveryRepository(database.manager).prepare(
            claim.principal
        )
    assert result.rebuilt
    assert result.draft_revision_id != original_revision
    async with database.manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBConsolidationEvidence)
                .where(
                    RDBConsolidationEvidence.attempt_id == claim.principal.attempt_id
                )
            )
            == 0
        )
        files = list(
            await session.read_session.scalars(
                sa.select(RDBConsolidationDraftFile.content)
                .join(
                    RDBConsolidationDraft,
                    RDBConsolidationDraft.id == RDBConsolidationDraftFile.draft_id,
                )
                .where(RDBConsolidationDraft.unit_id == claim.unit_id)
            )
        )
        assert all("Source-dependent prose" not in content for content in files)
    await _assert_same_claim(database, claim)


@pytest.mark.parametrize("operation", ["source_read", "manifest"])
async def test_archived_restore_cannot_cross_validated_participant_body_boundary(
    database: _Database, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Existing denied roots remain locked through body/manifest acceptance."""
    claim = await _claim(database, personal=False)
    await _establish_draft(database, claim)
    async with database.manager() as session:
        await AgentSessionRepository().archive(
            session,
            database.corpus.team_source,
            ended_at=datetime.datetime.now(datetime.UTC),
        )
    validated = asyncio.Event()
    continue_acceptance = asyncio.Event()
    reader_pid_queue: asyncio.Queue[int] = asyncio.Queue()
    validation = authority_module.validate_participant_plan
    pause_count = 0

    async def paused_validation(
        session: ReadSession,
        principal: ConsolidationJobPrincipal,
        plan: ConsolidationParticipantPlan,
    ) -> None:
        nonlocal pause_count
        await validation(session, principal, plan)
        if principal == claim.principal and pause_count == 0:
            pause_count += 1
            pid = await session.read_session.scalar(sa.select(sa.func.pg_backend_pid()))
            assert isinstance(pid, int)
            await reader_pid_queue.put(pid)
            validated.set()
            await continue_acceptance.wait()

    monkeypatch.setattr(
        authority_module, "validate_participant_plan", paused_validation
    )

    async def accept() -> None:
        if operation == "source_read":
            await ConsolidationSourceRepository(database.manager).read(
                claim.principal,
                source_session_id=database.corpus.team_source,
                offset=0,
                max_bytes=12000,
            )
        else:
            await ConsolidationExecutionRepository(database.manager).authorize(
                claim.principal
            )

    async def restore() -> None:
        async with database.manager() as session:
            await AgentSessionRepository().restore_tree(
                session,
                root_session_id=database.corpus.team_source,
                session_ids=[database.corpus.team_source],
            )

    accepting = asyncio.create_task(accept())
    restoring: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(3):
            await validated.wait()
            reader_pid = await reader_pid_queue.get()
        restoring = asyncio.create_task(restore())
        async with asyncio.timeout(3):
            while True:
                async with database.manager() as observer:
                    blocked_root_update = await observer.read_session.scalar(
                        sa.text(
                            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                            "WHERE datname = current_database() AND state = 'active' "
                            "AND query LIKE '%UPDATE agent_sessions%' "
                            "AND :reader = ANY(pg_blocking_pids(pid)))"
                        ),
                        {"reader": reader_pid},
                    )
                if blocked_root_update:
                    break
                if restoring.done():
                    await restoring
                    raise AssertionError(
                        "Root restore committed across an unprotected body boundary."
                    )
        assert not restoring.done()
        continue_acceptance.set()
        with pytest.raises(ConsolidationAuthorityError):
            async with asyncio.timeout(3):
                await accepting
        async with asyncio.timeout(3):
            await restoring
        # Restoration permits a fresh source operation, not the old denied
        # operation that already passed its participant snapshot validation.
        fresh = await ConsolidationSourceRepository(database.manager).read(
            claim.principal,
            source_session_id=database.corpus.team_source,
            offset=0,
            max_bytes=12000,
        )
        assert fresh.version.source_session_id == database.corpus.team_source
        await _assert_same_claim(database, claim)
    finally:
        continue_acceptance.set()
        if not accepting.done():
            accepting.cancel()
        if restoring is not None and not restoring.done():
            restoring.cancel()
        tasks = [accepting] if restoring is None else [accepting, restoring]
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_personal_membership_wait_rechecks_exact_grant_before_source_exposure(
    database: _Database,
) -> None:
    claim = await _claim(database, personal=True)
    async with database.manager() as holder:
        await holder.write_session.scalar(
            sa.select(RDBWorkspaceUser)
            .where(
                RDBWorkspaceUser.workspace_id == database.corpus.personal.workspace_id,
                RDBWorkspaceUser.user_id == database.corpus.personal.associated_user_id,
            )
            .with_for_update()
        )
        task = asyncio.create_task(
            ConsolidationSourceRepository(database.manager).read(
                claim.principal,
                source_session_id=database.corpus.personal_source,
                offset=0,
                max_bytes=12000,
            )
        )
        await _wait_for_blocked_backend(database.manager, holder)
        assert not task.done()
    async with asyncio.timeout(3):
        result = await task
    assert result.version.source_session_id == database.corpus.personal_source
    await _assert_same_claim(database, claim)
