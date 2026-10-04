"""Real PostgreSQL frozen publication, exact work choices and fail-closed races."""

import dataclasses
import datetime

import pytest
import sqlalchemy as sa
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
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationRevision,
    RDBConsolidationRevisionDependency,
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
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


async def _ready(manager: SessionManager[WriteSession], *, empty: bool) -> _Ready:
    corpus = await seed_consolidation_corpus(manager)
    owners = ConsolidationOwnershipRepository(manager)
    claim = await owners.claim(corpus.team, deadline=consolidation_deadline())
    assert claim is not None
    work = ConsolidationWorkRepository(manager)
    page = await work.page(claim.principal, after_sequence=None, limit=50)
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
            f"- azents://memory/historical/team/{corpus.team_source}/summary.md"
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
        ],
    )
    frozen = await ConsolidationPublicationRepository(manager).freeze(claim.principal)
    await work.record_coverage(
        claim.principal,
        expected_draft_revision_id=frozen.revision_id,
        coverage=frozen.coverage,
    )
    return _Ready(corpus, claim.principal, frozen, work_id)


async def _publish(manager: SessionManager[WriteSession], ready: _Ready) -> str:
    overview = validate_consolidation_overview(
        key=ready.principal.unit, markdown=ready.frozen.markdown
    )
    result = await ConsolidationPublicationRepository(manager).publish(
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
    ready = await _ready(rdb_session_manager, empty=empty)
    async with rdb_session_manager() as session:
        work = await session.read_session.get(RDBConsolidationWork, ready.work_id)
        assert work is not None and work.state is ConsolidationWorkState.CONSIDERED
    revision_id = await _publish(rdb_session_manager, ready)
    result = await ConsolidationPublicationRepository(
        rdb_session_manager
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
        await ConsolidationPublicationRepository(rdb_session_manager).inspect_outcome(
            ready.principal
        )
        == result
    )


async def test_content_change_after_legitimate_read_publishes_old_work_only(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    ready = await _ready(rdb_session_manager, empty=False)
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
    ready = await _ready(rdb_session_manager, empty=False)
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
    ready = await _ready(rdb_session_manager, empty=False)
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
    ready = await _ready(rdb_session_manager, empty=False)
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
