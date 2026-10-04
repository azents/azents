"""Small finite-pass regressions across publications and late committed work."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from azents.core.historical_memory_consolidation import (
    ConsolidationDisposition,
    ConsolidationWorkState,
)
from azents.core.historical_memory_publication import (
    ConsolidationCoverage,
    ConsolidationWorkDisposition,
    validate_consolidation_overview,
)
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.session import SessionManager
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
from azents.repos.historical_memory_consolidation.recovery import (
    ConsolidationRecoveryRepository,
)
from azents.repos.historical_memory_consolidation.work import (
    ConsolidationWorkRepository,
    work_predicate,
)
from azents.testing.consolidation import (
    create_consolidation_source,
    seed_consolidation_corpus,
)


async def test_finite_pass_spans_four_slices_and_does_not_cover_late_work(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    async with manager() as session:
        for index in range(6):
            await create_consolidation_source(
                session,
                manager=manager,
                key=corpus.team,
                summary="Synthetic finite-pass summary",
                title=f"Synthetic finite-pass source {index}",
            )
    owners = ConsolidationOwnershipRepository(manager)
    work = ConsolidationWorkRepository(manager)
    drafts = ConsolidationDraftRepository(manager)
    publication = ConsolidationPublicationRepository(manager)
    covered: set[str] = set()
    upper: int | None = None
    late_id: str | None = None
    sizes: list[int] = []
    for index in range(4):
        claim = await owners.claim(corpus.team)
        assert claim is not None
        await ConsolidationRecoveryRepository(manager).prepare(claim.principal)
        page = await work.page(claim.principal, after_sequence=None, limit=2)
        assert page.entries
        sizes.append(len(page.entries))
        if upper is None:
            upper = page.pass_upper_sequence
            async with manager() as session:
                late_source = await create_consolidation_source(
                    session,
                    manager=manager,
                    key=corpus.team,
                    summary="Late work remains pending for a separate pass",
                    title="Late source",
                )
                late_id = await session.scalar(
                    sa.select(RDBConsolidationWork.id).where(
                        RDBConsolidationWork.source_session_id == late_source
                    )
                )
                assert late_id is not None
        assert page.pass_upper_sequence == upper
        ids = {entry.work_id for entry in page.entries}
        assert not ids & covered
        assert late_id not in ids
        coverage = ConsolidationCoverage(
            dispositions=tuple(
                ConsolidationWorkDisposition(
                    work_id=entry.work_id,
                    action=ConsolidationDisposition.CONSIDERED,
                    reason="Exact supplied work integrated in this slice",
                )
                for entry in page.entries
            )
        )
        summary = await drafts.observe(claim.principal, path="summary.md")
        journal = await drafts.observe(claim.principal, path="coverage.json")
        markdown = (
            f"## Historical Context\nSynthetic context after slice {index}.\n\n"
            "## Source Routes\n"
            f"- azents://memory/historical/team/{corpus.team_source}/summary.md"
            " — Synthetic details\n"
        )
        await drafts.mutate(
            claim.principal,
            tool_call_id=uuid7().hex,
            request_digest="a" * 64,
            expected_draft_revision_id=summary.draft_revision_id,
            expected_observation_epoch=summary.observation_epoch,
            changes=[
                DraftFileChange("summary.md", summary.file_revision_id, markdown),
                DraftFileChange(
                    "coverage.json",
                    journal.file_revision_id,
                    coverage.model_dump_json(),
                ),
            ],
        )
        frozen = await publication.freeze(claim.principal)
        await work.record_coverage(
            claim.principal,
            expected_draft_revision_id=frozen.revision_id,
            coverage=frozen.coverage,
        )
        await publication.publish(
            claim.principal,
            expected_draft_revision_id=frozen.revision_id,
            expected_observation_epoch=frozen.observation_epoch,
            overview=validate_consolidation_overview(
                key=corpus.team, markdown=frozen.markdown
            ),
        )
        covered.update(ids)
        async with manager() as session:
            late = await session.get(RDBConsolidationWork, late_id)
            assert late is not None and late.state is ConsolidationWorkState.PENDING
            published = set(
                await session.scalars(
                    sa.select(RDBConsolidationWork.id).where(
                        work_predicate(corpus.team),
                        RDBConsolidationWork.state == ConsolidationWorkState.PUBLISHED,
                    )
                )
            )
            assert published == covered
            unit = await session.scalar(
                sa.select(RDBConsolidationUnit).where(
                    RDBConsolidationUnit.agent_id == corpus.team.agent_id
                )
            )
            assert unit is not None
            assert unit.pass_upper_sequence == (None if index == 3 else upper)
    assert sizes == [2, 2, 2, 1]
    assert len(covered) == 7
    next_claim = await owners.claim(corpus.team)
    assert next_claim is not None
    next_page = await work.page(next_claim.principal, after_sequence=None, limit=2)
    assert {entry.work_id for entry in next_page.entries} == {late_id}
    assert upper is not None and next_page.pass_upper_sequence > upper
