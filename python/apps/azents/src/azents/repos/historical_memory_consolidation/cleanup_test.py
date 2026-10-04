"""Real PostgreSQL expiry, active-owner protection and immutable manifest retention."""

import datetime
from dataclasses import dataclass

import sqlalchemy as sa

from azents.core.historical_memory_consolidation import (
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
    RDBConsolidationDraft,
    RDBConsolidationRevision,
    RDBConsolidationRevisionDependency,
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.historical_memory_consolidation.cleanup import (
    ConsolidationCleanupRepository,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
    DraftFileChange,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.publication import (
    ConsolidationPublicationRepository,
)
from azents.repos.historical_memory_consolidation.work import (
    ConsolidationWorkRepository,
)
from azents.testing.consolidation import (
    consolidation_deadline,
    create_consolidation_source,
    seed_consolidation_corpus,
)


@dataclass(frozen=True)
class _Ready:
    principal: ConsolidationJobPrincipal
    unit_id: str
    source_id: str
    work_id: str


async def _ready(
    manager: SessionManager[WriteSession], *, extra_source: bool
) -> _Ready:
    corpus = await seed_consolidation_corpus(manager)
    if extra_source:
        async with manager() as session:
            await create_consolidation_source(
                session,
                manager=manager,
                key=corpus.team,
                summary="Another permitted source",
                title="Pending continuation",
            )
    claim = await ConsolidationOwnershipRepository(manager).claim(
        corpus.team, deadline=consolidation_deadline()
    )
    assert claim is not None
    page = await ConsolidationWorkRepository(manager).page(
        claim.principal, after_sequence=None, limit=50
    )
    work_id = page.entries[0].work_id
    draft = ConsolidationDraftRepository(manager)
    observation = await draft.observe(claim.principal, path="summary.md")
    markdown = (
        "## Historical Context\nSource-dependent context.\n\n## Source Routes\n"
        + f"- azents://memory/historical/team/{corpus.team_source}/summary.md "
        "— Scoped source\n"
    )
    coverage = ConsolidationCoverage(
        dispositions=(
            ConsolidationWorkDisposition(
                work_id=work_id,
                action=ConsolidationDisposition.CONSIDERED,
                reason="Integrated source",
            ),
        )
    )
    await draft.mutate(
        claim.principal,
        tool_call_id="author",
        request_digest="a" * 64,
        expected_draft_revision_id=observation.draft_revision_id,
        expected_observation_epoch=observation.observation_epoch,
        changes=[
            DraftFileChange("summary.md", None, markdown),
            DraftFileChange("coverage.json", None, coverage.model_dump_json()),
        ],
    )
    frozen = await ConsolidationPublicationRepository(manager).freeze(claim.principal)
    await ConsolidationWorkRepository(manager).record_coverage(
        claim.principal,
        expected_draft_revision_id=frozen.revision_id,
        coverage=frozen.coverage,
    )
    return _Ready(claim.principal, claim.unit_id, corpus.team_source, work_id)


async def _age(manager: SessionManager[WriteSession], ready: _Ready) -> None:
    async with manager() as session:
        await session.write_session.execute(
            sa.update(RDBConsolidationDraft)
            .where(RDBConsolidationDraft.unit_id == ready.unit_id)
            .values(
                last_progress_at=datetime.datetime.now(datetime.UTC)
                - datetime.timedelta(hours=25)
            )
        )


async def test_live_owner_protects_even_expired_draft_and_receipts(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    ready = await _ready(rdb_session_manager, extra_source=False)
    await _age(rdb_session_manager, ready)
    result = await ConsolidationCleanupRepository(rdb_session_manager).sweep(limit=50)
    assert result.units == result.drafts == result.expired_owners == 0
    assert (
        await ConsolidationDraftRepository(rdb_session_manager).observe(
            ready.principal, path="summary.md"
        )
    ).content is not None


async def test_expired_inactive_draft_resets_unpublished_choices_not_sources(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    ready = await _ready(rdb_session_manager, extra_source=False)
    await ConsolidationOwnershipRepository(rdb_session_manager).fail(
        ready.principal, failure_code="synthetic_failed", cancelled=False
    )
    await _age(rdb_session_manager, ready)
    cleanup = ConsolidationCleanupRepository(rdb_session_manager)
    result = await cleanup.sweep(limit=50)
    assert result.drafts == 1 and result.expired_owners == 0
    assert (await cleanup.sweep(limit=50)).units == 0
    async with rdb_session_manager() as session:
        work = await session.read_session.get(RDBConsolidationWork, ready.work_id)
        assert work is not None and work.state is ConsolidationWorkState.PENDING
        assert (
            work.considered_draft_id
            is work.considered_draft_revision_id
            is work.disposition
            is None
        )
        assert (
            await session.read_session.scalar(
                sa.select(RDBConsolidationDraft.id).where(
                    RDBConsolidationDraft.unit_id == ready.unit_id
                )
            )
            is None
        )


async def test_recent_failed_work_is_recoverable_not_terminal_body_archive(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    ready = await _ready(rdb_session_manager, extra_source=False)
    await ConsolidationOwnershipRepository(rdb_session_manager).fail(
        ready.principal, failure_code="synthetic_failed", cancelled=False
    )
    result = await ConsolidationCleanupRepository(rdb_session_manager).sweep(limit=50)
    assert result.drafts == 0
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(RDBConsolidationDraft.id).where(
                    RDBConsolidationDraft.unit_id == ready.unit_id
                )
            )
            is not None
        )


async def test_completed_private_payload_cleanup_keeps_published_bytes_and_manifest(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    ready = await _ready(rdb_session_manager, extra_source=False)
    publication = ConsolidationPublicationRepository(rdb_session_manager)
    frozen = await publication.freeze(ready.principal)
    outcome = await publication.publish(
        ready.principal,
        expected_draft_revision_id=frozen.revision_id,
        expected_observation_epoch=frozen.observation_epoch,
        overview=validate_consolidation_overview(
            key=ready.principal.unit, markdown=frozen.markdown
        ),
    )
    assert (
        await ConsolidationCleanupRepository(rdb_session_manager).sweep(limit=50)
    ).drafts == 1
    assert await publication.inspect_outcome(ready.principal) == outcome
    async with rdb_session_manager() as session:
        revision = await session.read_session.get(
            RDBConsolidationRevision, outcome.revision_id
        )
        assert revision is not None and revision.markdown == frozen.markdown
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBConsolidationRevisionDependency)
                .where(
                    RDBConsolidationRevisionDependency.revision_id
                    == outcome.revision_id
                )
            )
            == 1
        )


async def test_denied_draft_is_removed_as_whole_even_before_24_hours(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    ready = await _ready(rdb_session_manager, extra_source=False)
    await ConsolidationOwnershipRepository(rdb_session_manager).fail(
        ready.principal, failure_code="synthetic_failed", cancelled=False
    )
    async with rdb_session_manager() as session:
        await AgentSessionRepository().archive(
            session, ready.source_id, ended_at=datetime.datetime.now(datetime.UTC)
        )
    assert (
        await ConsolidationCleanupRepository(rdb_session_manager).sweep(limit=50)
    ).drafts == 1
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(RDBConsolidationDraft.id).where(
                    RDBConsolidationDraft.unit_id == ready.unit_id
                )
            )
            is None
        )
        unit = await session.read_session.get(RDBConsolidationUnit, ready.unit_id)
        assert unit is not None and unit.published_revision_id is None


async def test_completed_slice_cleanup_preserves_its_unfinished_finite_pass(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    ready = await _ready(rdb_session_manager, extra_source=True)
    publication = ConsolidationPublicationRepository(rdb_session_manager)
    frozen = await publication.freeze(ready.principal)
    await publication.publish(
        ready.principal,
        expected_draft_revision_id=frozen.revision_id,
        expected_observation_epoch=frozen.observation_epoch,
        overview=validate_consolidation_overview(
            key=ready.principal.unit, markdown=frozen.markdown
        ),
    )
    async with rdb_session_manager() as session:
        unit = await session.read_session.get(RDBConsolidationUnit, ready.unit_id)
        assert unit is not None and unit.pass_upper_sequence is not None
        upper = unit.pass_upper_sequence
    assert (
        await ConsolidationCleanupRepository(rdb_session_manager).sweep(limit=50)
    ).drafts == 1
    async with rdb_session_manager() as session:
        unit = await session.read_session.get(RDBConsolidationUnit, ready.unit_id)
        assert unit is not None and unit.pass_upper_sequence == upper
        pending = await session.read_session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBConsolidationWork)
            .where(
                RDBConsolidationWork.agent_id == ready.principal.unit.agent_id,
                RDBConsolidationWork.scope == ready.principal.unit.scope,
                RDBConsolidationWork.state == ConsolidationWorkState.PENDING,
                RDBConsolidationWork.sequence <= upper,
            )
        )
        assert pending == 1
