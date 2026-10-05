"""Immediate successful workspace retirement, continuation and atomic rollback."""

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

import azents.repos.historical_memory_consolidation.publication as publication_module
from azents.core.historical_memory_consolidation import (
    ConsolidationAttemptState,
    ConsolidationDisposition,
    ConsolidationWorkState,
)
from azents.core.historical_memory_publication import (
    ConsolidationCoverage,
    ConsolidationWorkDisposition,
)
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationDraft,
    RDBConsolidationDraftDependency,
    RDBConsolidationDraftFile,
    RDBConsolidationEvidence,
    RDBConsolidationMutationReceipt,
    RDBConsolidationRevision,
    RDBConsolidationRevisionDependency,
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.historical_memory_consolidation.authority import (
    LockedConsolidationOwner,
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
from azents.repos.historical_memory_consolidation.publication_test import (
    _committed_corpus,
    _publish,
    _Ready,
    _ready_for_corpus,
)
from azents.repos.historical_memory_consolidation.recovery import (
    ConsolidationRecoveryRepository,
)
from azents.repos.historical_memory_consolidation.work import (
    ConsolidationWorkRepository,
)
from azents.testing.consolidation import (
    consolidation_deadline,
    create_consolidation_source,
    seed_consolidation_corpus,
)


async def test_immediate_next_slice_starts_clean_from_published_bytes_and_manifest(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """No periodic sweep is needed between productive slices of the same pass."""
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    async with manager() as session:
        await create_consolidation_source(
            session,
            manager=manager,
            key=corpus.team,
            summary="Remaining source context",
            title="Remaining source",
        )
    ready = await _ready_for_corpus(manager, corpus, empty=False, personal=False)
    work = ConsolidationWorkRepository(manager)
    page = await work.page(ready.principal, after_sequence=None, limit=50)
    remaining = next(entry for entry in page.entries if entry.work_id != ready.work_id)
    # An unfinished choice omitted from this slice's frozen coverage must not be
    # completed implicitly when its workspace is retired.
    choice = ConsolidationCoverage(
        dispositions=(
            ConsolidationWorkDisposition(
                work_id=remaining.work_id,
                action=ConsolidationDisposition.CONSIDERED,
                reason="Unpublished partial choice",
            ),
        )
    )
    await work.record_coverage(
        ready.principal,
        expected_draft_revision_id=ready.frozen.revision_id,
        coverage=choice,
    )
    # The second work page changed the observation epoch after the first freeze.
    frozen_first = await ConsolidationPublicationRepository(
        session_manager=manager, read_session_manager=manager
    ).freeze(ready.principal)
    ready = _Ready(corpus, ready.principal, frozen_first, ready.work_id)
    revision_id = await _publish(manager, ready)
    async with manager() as session:
        for model in (
            RDBConsolidationDraft,
            RDBConsolidationDraftFile,
            RDBConsolidationDraftDependency,
            RDBConsolidationEvidence,
            RDBConsolidationMutationReceipt,
        ):
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count()).select_from(model)
                )
                == 0
            )
    owners = ConsolidationOwnershipRepository(manager)
    second = await owners.claim(corpus.team, deadline=consolidation_deadline())
    assert second is not None
    assert second.pass_upper_sequence == page.pass_upper_sequence
    checkpoint = await ConsolidationRecoveryRepository(manager).prepare(
        second.principal
    )
    assert checkpoint.published_available and not checkpoint.rebuilt
    assert checkpoint.draft_revision_id != ready.frozen.revision_id
    drafts = ConsolidationDraftRepository(manager)
    files = await drafts.inventory(second.principal)
    assert [file.path for file in files] == ["summary.md"]
    assert files[0].observation.content == ready.frozen.markdown
    journal = await drafts.observe(second.principal, path="coverage.json")
    assert journal.content is None and journal.file_revision_id is None
    async with manager() as session:
        pending = await session.read_session.get(
            RDBConsolidationWork, remaining.work_id
        )
        assert pending is not None and pending.state is ConsolidationWorkState.PENDING
        assert (
            pending.considered_draft_id
            is pending.considered_draft_revision_id
            is pending.presented_attempt_id
            is pending.disposition
            is pending.consideration_reason
            is None
        )
        draft = await session.read_session.scalar(
            sa.select(RDBConsolidationDraft).where(
                RDBConsolidationDraft.unit_id == second.unit_id,
            )
        )
        assert draft is not None and draft.base_revision_id == revision_id
        inherited = set(
            await session.read_session.scalars(
                sa.select(RDBConsolidationDraftDependency.source_session_id).where(
                    RDBConsolidationDraftDependency.draft_id == draft.id,
                )
            )
        )
        published = set(
            await session.read_session.scalars(
                sa.select(RDBConsolidationRevisionDependency.source_session_id).where(
                    RDBConsolidationRevisionDependency.revision_id == revision_id,
                )
            )
        )
        assert inherited == published and len(inherited) == 2
    next_page = await work.page(second.principal, after_sequence=None, limit=50)
    assert [entry.work_id for entry in next_page.entries] == [remaining.work_id]
    summary = await drafts.observe(second.principal, path="summary.md")
    await drafts.mutate(
        second.principal,
        tool_call_id="next-slice-coverage",
        request_digest="b" * 64,
        expected_draft_revision_id=summary.draft_revision_id,
        expected_observation_epoch=summary.observation_epoch,
        changes=[DraftFileChange("coverage.json", None, choice.model_dump_json())],
    )
    frozen = await ConsolidationPublicationRepository(
        session_manager=manager,
        read_session_manager=manager,
    ).freeze(second.principal)
    await work.record_coverage(
        second.principal,
        expected_draft_revision_id=frozen.revision_id,
        coverage=frozen.coverage,
    )
    next_revision = await _publish(
        manager, _Ready(corpus, second.principal, frozen, remaining.work_id)
    )
    assert next_revision != revision_id
    async with manager() as session:
        unit = await session.read_session.get(RDBConsolidationUnit, second.unit_id)
        assert unit is not None and unit.pass_upper_sequence is None
        assert unit.published_revision_id == next_revision
        assert unit.failure_count == unit.no_progress_count == 0
        assert (
            await session.read_session.scalar(
                sa.select(RDBConsolidationDraft.id).where(
                    RDBConsolidationDraft.unit_id == unit.id,
                )
            )
            is None
        )


@pytest.mark.parametrize("cancel", [False, True])
async def test_publication_cleanup_rolls_back_with_failed_or_cancelled_commit(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    """The workspace is not lost if acceptance aborts after staged cleanup."""
    manager = create_read_write_session_manager(rdb_engine)
    async with _committed_corpus(rdb_engine) as corpus:
        ready = await _ready_for_corpus(manager, corpus, empty=False, personal=False)

        async def abort_after_cleanup(
            session: WriteSession, owner: LockedConsolidationOwner
        ) -> None:
            await session.write_session.flush()
            assert (
                await session.read_session.scalar(
                    sa.select(RDBConsolidationDraft.id).where(
                        RDBConsolidationDraft.unit_id == owner.unit.id,
                    )
                )
                is None
            )
            if cancel:
                raise asyncio.CancelledError("cancel-after-staged-cleanup")
            raise RuntimeError("abort-after-staged-cleanup")

        with monkeypatch.context() as patch:
            patch.setattr(
                publication_module, "require_commit_owner", abort_after_cleanup
            )
            with pytest.raises(
                asyncio.CancelledError if cancel else RuntimeError,
                match="after-staged-cleanup",
            ):
                await _publish(manager, ready)
        async with manager() as session:
            attempt = await session.read_session.get(
                RDBConsolidationAttempt, ready.principal.attempt_id
            )
            assert (
                attempt is not None
                and attempt.state is ConsolidationAttemptState.RUNNING
            )
            draft = await session.read_session.scalar(
                sa.select(RDBConsolidationDraft).where(
                    RDBConsolidationDraft.unit_id == attempt.unit_id,
                )
            )
            assert draft is not None and draft.revision_id == ready.frozen.revision_id
            files = set(
                await session.read_session.scalars(
                    sa.select(RDBConsolidationDraftFile.path).where(
                        RDBConsolidationDraftFile.draft_id == draft.id,
                    )
                )
            )
            assert files == {"summary.md", "coverage.json", "notes.md"}
            row = await session.read_session.get(RDBConsolidationWork, ready.work_id)
            assert row is not None and row.state is ConsolidationWorkState.CONSIDERED
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBConsolidationRevision)
                    .where(
                        RDBConsolidationRevision.attempt_id == attempt.id,
                    )
                )
                == 0
            )
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBConsolidationMutationReceipt)
                    .where(
                        RDBConsolidationMutationReceipt.attempt_id == attempt.id,
                    )
                )
                == 1
            )
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBConsolidationEvidence)
                    .where(
                        RDBConsolidationEvidence.attempt_id == attempt.id,
                    )
                )
                == 1
            )
        # Preserved files still publish once when the original fault is gone.
        await _publish(manager, ready)
