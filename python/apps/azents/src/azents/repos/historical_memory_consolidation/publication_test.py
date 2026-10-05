"""Real PostgreSQL frozen publication, exact work choices and fail-closed races."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine
from uuid6 import uuid7

from azents.core.historical_memory import HistoricalMemoryCompletion
from azents.core.historical_memory_consolidation import (
    ConsolidationAttemptState,
    ConsolidationDisposition,
    ConsolidationJobPrincipal,
    ConsolidationWorkState,
)
from azents.core.historical_memory_publication import (
    ConsolidationCoverage,
    ConsolidationWorkDisposition,
    validate_consolidation_overview,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationRevision,
    RDBConsolidationRevisionDependency,
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftConflict,
    ConsolidationDraftRepository,
    DraftFileChange,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.publication import (
    ConsolidationPublicationRepository,
    FrozenConsolidationDraft,
)
from azents.repos.historical_memory_consolidation.work import (
    ConsolidationWorkRepository,
)
from azents.repos.session_lifecycle_finalizer import SessionLifecycleFinalizerRepository
from azents.testing.consolidation import (
    ConsolidationCorpus,
    consolidation_deadline,
    seed_consolidation_corpus,
)


@dataclasses.dataclass(frozen=True)
class _Ready:
    corpus: ConsolidationCorpus
    principal: ConsolidationJobPrincipal
    frozen: FrozenConsolidationDraft
    work_id: str


async def _ready_for_corpus(
    manager: SessionManager[WriteSession],
    corpus: ConsolidationCorpus,
    *,
    empty: bool,
    personal: bool,
) -> _Ready:
    key = corpus.personal if personal else corpus.team
    source_id = corpus.personal_source if personal else corpus.team_source
    owners = ConsolidationOwnershipRepository(manager)
    claim = await owners.claim(key, deadline=consolidation_deadline())
    assert claim is not None
    work = ConsolidationWorkRepository(manager)
    page = await work.page(claim.principal, after_sequence=None, limit=1)
    assert len(page.entries) == 1
    work_id = page.entries[0].work_id
    coverage = ConsolidationCoverage(
        dispositions=(
            ConsolidationWorkDisposition(
                work_id=work_id,
                action=ConsolidationDisposition.OMITTED
                if empty
                else ConsolidationDisposition.CONSIDERED,
                reason="No useful continuation context"
                if empty
                else "Integrated source context",
            ),
        )
    )
    markdown = (
        "## Historical Context\n\n## Source Routes\n"
        if empty
        else (
            "## Historical Context\nObserved source-dependent context.\n\n"
            "## Source Routes\n"
            f"- azents://memory/historical/{key.scope.value}/{source_id}/summary.md"
            " — Source details\n"
        )
    )
    drafts = ConsolidationDraftRepository(manager)
    summary = await drafts.observe(claim.principal, path="summary.md")
    journal = await drafts.observe(claim.principal, path="coverage.json")
    await drafts.mutate(
        claim.principal,
        tool_call_id="author-artifacts",
        request_digest="a" * 64,
        expected_draft_revision_id=summary.draft_revision_id,
        expected_observation_epoch=summary.observation_epoch,
        changes=[
            DraftFileChange("summary.md", summary.file_revision_id, markdown),
            DraftFileChange(
                "coverage.json", journal.file_revision_id, coverage.model_dump_json()
            ),
            DraftFileChange("notes.md", None, "Temporary working notes"),
        ],
    )
    frozen = await ConsolidationPublicationRepository(
        session_manager=manager, read_session_manager=manager
    ).freeze(claim.principal)
    await work.record_coverage(
        claim.principal,
        expected_draft_revision_id=frozen.revision_id,
        coverage=frozen.coverage,
    )
    return _Ready(corpus, claim.principal, frozen, work_id)


async def _ready(
    manager: SessionManager[WriteSession], *, empty: bool, personal: bool
) -> _Ready:
    corpus = await seed_consolidation_corpus(manager)
    return await _ready_for_corpus(
        manager,
        corpus,
        empty=empty,
        personal=personal,
    )


@asynccontextmanager
async def _committed_corpus(
    engine: AsyncEngine,
) -> AsyncIterator[ConsolidationCorpus]:
    """Expose committed fixture rows while guaranteeing scoped cleanup."""
    writes = create_read_write_session_manager(engine)
    corpus = await seed_consolidation_corpus(writes)
    try:
        yield corpus
    finally:
        async with writes() as session:
            for source_id in (corpus.team_source, corpus.personal_source):
                await SessionLifecycleFinalizerRepository().finalize_purged_root_tree(
                    session,
                    root_session_id=source_id,
                    session_ids=[source_id],
                )
            await session.write_session.execute(
                sa.delete(RDBAgentRuntime).where(
                    RDBAgentRuntime.agent_id == corpus.team.agent_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == corpus.team.agent_id)
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspaceUser).where(
                    RDBWorkspaceUser.workspace_id == corpus.team.workspace_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(
                    RDBWorkspace.id == corpus.team.workspace_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBUser).where(
                    RDBUser.id == corpus.personal.associated_user_id
                )
            )


async def _publish(manager: SessionManager[WriteSession], ready: _Ready) -> str:
    overview = validate_consolidation_overview(
        key=ready.principal.unit, markdown=ready.frozen.markdown
    )
    result = await ConsolidationPublicationRepository(
        session_manager=manager, read_session_manager=manager
    ).publish(
        ready.principal,
        expected_draft_revision_id=ready.frozen.revision_id,
        expected_observation_epoch=ready.frozen.observation_epoch,
        overview=overview,
    )
    return result.revision_id


@pytest.mark.parametrize("empty", [False, True])
async def test_atomic_publication_records_exact_coverage_and_durable_uncertain_outcome(
    rdb_session_manager: SessionManager[WriteSession], empty: bool
) -> None:
    ready = await _ready(rdb_session_manager, empty=empty, personal=False)
    async with rdb_session_manager() as session:
        work = await session.read_session.get(RDBConsolidationWork, ready.work_id)
        assert work is not None and work.state is ConsolidationWorkState.CONSIDERED
    revision_id = await _publish(rdb_session_manager, ready)
    result = await ConsolidationPublicationRepository(
        session_manager=rdb_session_manager,
        read_session_manager=rdb_session_manager,
    ).inspect_outcome(ready.principal)
    assert result is not None and result.revision_id == revision_id
    async with rdb_session_manager() as session:
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, ready.principal.attempt_id
        )
        assert (
            attempt is not None and attempt.state is ConsolidationAttemptState.COMPLETED
        )
        unit = await session.read_session.get(RDBConsolidationUnit, attempt.unit_id)
        assert unit is not None and unit.published_revision_id == revision_id
        assert unit.owner_token is unit.active_attempt_id is unit.lease_until is None
        assert unit.pass_upper_sequence is None and unit.no_progress_count == 0
        revision = await session.read_session.get(RDBConsolidationRevision, revision_id)
        assert revision is not None
        assert (revision.rendered_block == "") == empty
        assert len(revision.rendered_block.encode()) <= 10000
        rows = list(
            await session.read_session.scalars(
                sa.select(RDBConsolidationWork).where(
                    RDBConsolidationWork.agent_id == ready.corpus.team.agent_id
                )
            )
        )
        own = next(row for row in rows if row.id == ready.work_id)
        peer = next(row for row in rows if row.id != ready.work_id)
        assert own.state is ConsolidationWorkState.PUBLISHED
        assert own.published_revision_id == revision_id
        assert peer.state is ConsolidationWorkState.PENDING
        dependencies = list(
            await session.read_session.scalars(
                sa.select(RDBConsolidationRevisionDependency).where(
                    RDBConsolidationRevisionDependency.revision_id == revision_id
                )
            )
        )
        assert len(dependencies) == 1
        assert dependencies[0].source_session_id == ready.corpus.team_source
    with pytest.raises(ConsolidationAuthorityError):
        await _publish(rdb_session_manager, ready)
    # The supported acknowledgement-loss path inspects durable completion instead.
    assert (
        await ConsolidationPublicationRepository(
            session_manager=rdb_session_manager,
            read_session_manager=rdb_session_manager,
        ).inspect_outcome(ready.principal)
        == result
    )


async def test_inspect_outcome_bypasses_held_agent_and_grant_locks(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A completed outcome remains observable during eligibility writer locks."""
    del latest_db_schema
    write_manager = create_read_write_session_manager(rdb_engine)
    read_manager = create_read_only_session_manager(rdb_engine)
    async with _committed_corpus(rdb_engine) as corpus:
        ready = await _ready_for_corpus(
            write_manager,
            corpus,
            empty=False,
            personal=True,
        )
        revision_id = await _publish(write_manager, ready)
        lock_acquired = asyncio.Event()
        release_lock = asyncio.Event()

        async def hold_eligibility_locks() -> None:
            async with write_manager() as session:
                agent_id = await session.write_session.scalar(
                    sa.select(RDBAgent.id)
                    .where(
                        RDBAgent.id == ready.principal.unit.agent_id,
                        RDBAgent.workspace_id == ready.principal.unit.workspace_id,
                    )
                    .with_for_update()
                )
                assert agent_id is not None
                grant_id = await session.write_session.scalar(
                    sa.select(RDBWorkspaceUser.id)
                    .where(
                        RDBWorkspaceUser.workspace_id
                        == ready.principal.unit.workspace_id,
                        RDBWorkspaceUser.user_id
                        == ready.principal.unit.associated_user_id,
                    )
                    .with_for_update()
                )
                assert grant_id is not None
                lock_acquired.set()
                await release_lock.wait()

        holder = asyncio.create_task(hold_eligibility_locks())
        try:
            await asyncio.wait_for(lock_acquired.wait(), timeout=5)
            result = await asyncio.wait_for(
                ConsolidationPublicationRepository(
                    session_manager=write_manager,
                    read_session_manager=read_manager,
                ).inspect_outcome(ready.principal),
                timeout=1,
            )
            assert result is not None and result.revision_id == revision_id
        finally:
            release_lock.set()
            await holder


async def test_content_change_after_legitimate_read_publishes_old_work_only(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    ready = await _ready(rdb_session_manager, empty=False, personal=False)
    now = datetime.datetime.now(datetime.UTC)
    await HistoricalMemoryRepository(rdb_session_manager).publish_completed(
        source_session_id=ready.corpus.team_source,
        completion=HistoricalMemoryCompletion(
            source_activity_at=now,
            source_tail_event_id=uuid7().hex,
            prepared_at=now,
            source_title_snapshot="Changed source",
            summary="New generation remains pending",
        ),
    )
    await _publish(rdb_session_manager, ready)
    owners = ConsolidationOwnershipRepository(rdb_session_manager)
    next_claim = await owners.claim(
        ready.corpus.team, deadline=consolidation_deadline()
    )
    assert next_claim is not None
    page = await ConsolidationWorkRepository(rdb_session_manager).page(
        next_claim.principal, after_sequence=None, limit=50
    )
    assert len(page.entries) == 1 and page.entries[0].version.summary_generation == 2
    assert page.entries[0].work_id != ready.work_id
    async with rdb_session_manager() as session:
        next_work = await session.read_session.get(
            RDBConsolidationWork, page.entries[0].work_id
        )
        assert (
            next_work is not None and next_work.state is ConsolidationWorkState.PENDING
        )


async def test_archive_restore_between_freeze_and_publication_cannot_rehabilitate_bytes(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    ready = await _ready(rdb_session_manager, empty=False, personal=False)
    async with rdb_session_manager() as session:
        sessions = AgentSessionRepository()
        await sessions.archive(
            session,
            ready.corpus.team_source,
            ended_at=datetime.datetime.now(datetime.UTC),
        )
        await sessions.restore_tree(
            session,
            root_session_id=ready.corpus.team_source,
            session_ids=[ready.corpus.team_source],
        )
    with pytest.raises(ConsolidationAuthorityError):
        await _publish(rdb_session_manager, ready)
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count()).select_from(RDBConsolidationRevision)
            )
            == 0
        )
        row = await session.read_session.get(RDBConsolidationWork, ready.work_id)
        assert row is not None and row.state is ConsolidationWorkState.CONSIDERED


async def test_journal_never_accepts_peer_or_unpresented_work_and_cas_is_frozen(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    ready = await _ready(rdb_session_manager, empty=False, personal=False)
    async with rdb_session_manager() as session:
        peer_id = await session.read_session.scalar(
            sa.select(RDBConsolidationWork.id).where(
                RDBConsolidationWork.associated_user_id
                == ready.corpus.personal.associated_user_id
            )
        )
        assert peer_id is not None
    forged = ConsolidationCoverage(
        dispositions=(
            ConsolidationWorkDisposition(
                work_id=peer_id,
                action=ConsolidationDisposition.CONSIDERED,
                reason="Forged peer choice",
            ),
        )
    )
    with pytest.raises(ConsolidationAuthorityError):
        await ConsolidationWorkRepository(rdb_session_manager).record_coverage(
            ready.principal,
            expected_draft_revision_id=ready.frozen.revision_id,
            coverage=forged,
        )
    drafts = ConsolidationDraftRepository(rdb_session_manager)
    summary = await drafts.observe(ready.principal, path="summary.md")
    await drafts.mutate(
        ready.principal,
        tool_call_id="later-write",
        request_digest="b" * 64,
        expected_draft_revision_id=summary.draft_revision_id,
        expected_observation_epoch=summary.observation_epoch,
        changes=[
            DraftFileChange(
                "summary.md", summary.file_revision_id, ready.frozen.markdown + "\n"
            )
        ],
    )
    with pytest.raises(ConsolidationDraftConflict, match="stale"):
        await _publish(rdb_session_manager, ready)
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count()).select_from(RDBConsolidationRevision)
            )
            == 0
        )


async def test_ordinary_source_read_is_not_implicit_work_presentation_or_disposition(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    ready = await _ready(rdb_session_manager, empty=False, personal=False)
    async with rdb_session_manager() as session:
        row = await session.read_session.get(RDBConsolidationWork, ready.work_id)
        assert row is not None
        row.state = ConsolidationWorkState.PENDING
        row.presented_attempt_id = None
        row.considered_draft_id = None
        row.considered_draft_revision_id = None
    with pytest.raises(ConsolidationAuthorityError, match="presented"):
        await ConsolidationWorkRepository(rdb_session_manager).record_coverage(
            ready.principal,
            expected_draft_revision_id=ready.frozen.revision_id,
            coverage=ready.frozen.coverage,
        )
    with pytest.raises(ConsolidationDraftConflict, match="coverage"):
        await _publish(rdb_session_manager, ready)
