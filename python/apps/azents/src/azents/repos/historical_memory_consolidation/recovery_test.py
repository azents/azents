"""Clean-start admission, publication initialization and atomic workspace reset."""

import asyncio
import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

import azents.repos.historical_memory_consolidation.recovery as recovery_module
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
    RDBConsolidationDraft,
    RDBConsolidationDraftDependency,
    RDBConsolidationEvidence,
    RDBConsolidationMutationReceipt,
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.agent_session import AgentSessionRepository
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


@pytest.mark.parametrize("personal", [False, True])
async def test_start_seeds_publication_and_processes_only_current_work(
    rdb_session_manager: SessionManager[WriteSession],
    personal: bool,
) -> None:
    """Residual files/old coverage cannot determine a successor's work receipt."""
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    key = corpus.personal if personal else corpus.team
    ready = await _ready_for_corpus(manager, corpus, empty=False, personal=personal)
    published_id = await _publish(manager, ready)
    async with manager() as session:
        await create_consolidation_source(
            session,
            manager=manager,
            key=key,
            summary="New current source",
            title="Current source",
        )
    owners = ConsolidationOwnershipRepository(manager)
    claim = await owners.claim(key, deadline=consolidation_deadline())
    assert claim is not None
    drafts = ConsolidationDraftRepository(manager)
    summary = await drafts.observe(claim.principal, path="summary.md")
    stale_coverage = ConsolidationCoverage(
        dispositions=(
            ConsolidationWorkDisposition(
                work_id=ready.work_id,
                action=ConsolidationDisposition.CONSIDERED,
                reason="Old completed receipt",
            ),
        )
    )
    await drafts.mutate(
        claim.principal,
        tool_call_id="residual-workspace",
        request_digest="b" * 64,
        expected_draft_revision_id=summary.draft_revision_id,
        expected_observation_epoch=summary.observation_epoch,
        changes=[
            DraftFileChange(
                "summary.md", summary.file_revision_id, "Unfinished workspace prose"
            ),
            DraftFileChange("coverage.json", None, stale_coverage.model_dump_json()),
            DraftFileChange("notes.md", None, "Private unfinished note"),
        ],
    )
    work = ConsolidationWorkRepository(manager)
    page = await work.page(claim.principal, after_sequence=None, limit=50)
    assert len(page.entries) == 1
    item = page.entries[0]
    coverage = ConsolidationCoverage(
        dispositions=(
            ConsolidationWorkDisposition(
                work_id=item.work_id,
                action=ConsolidationDisposition.CONSIDERED,
                reason="Current supplied source",
            ),
        )
    )
    current = await drafts.observe(claim.principal, path="summary.md")
    await work.record_coverage(
        claim.principal,
        expected_draft_revision_id=current.draft_revision_id,
        coverage=coverage,
    )
    checkpoint = await ConsolidationRecoveryRepository(manager).prepare(claim.principal)
    assert checkpoint.rebuilt and checkpoint.published_available
    files = await drafts.inventory(claim.principal)
    assert [f.path for f in files] == ["summary.md"]
    assert files[0].observation.content == ready.frozen.markdown
    assert files[0].observation.draft_revision_id != current.draft_revision_id
    assert checkpoint.observation_epoch > current.observation_epoch
    async with manager() as session:
        row = await session.read_session.get(RDBConsolidationWork, item.work_id)
        assert row is not None and row.state is ConsolidationWorkState.PENDING
        assert (
            row.considered_draft_id
            is row.presented_attempt_id
            is row.disposition
            is None
        )
        published_work = await session.read_session.get(
            RDBConsolidationWork, ready.work_id
        )
        assert (
            published_work is not None
            and published_work.state is ConsolidationWorkState.PUBLISHED
        )
        for model in (RDBConsolidationEvidence, RDBConsolidationMutationReceipt):
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(model)
                    .where(model.attempt_id == claim.principal.attempt_id)
                )
                == 0
            )
        draft = await session.read_session.scalar(
            sa.select(RDBConsolidationDraft).where(
                RDBConsolidationDraft.unit_id == claim.unit_id
            )
        )
        assert draft is not None and draft.base_revision_id == published_id
        inherited = set(
            await session.read_session.scalars(
                sa.select(RDBConsolidationDraftDependency.source_session_id).where(
                    RDBConsolidationDraftDependency.draft_id == draft.id
                )
            )
        )
        assert inherited == {corpus.personal_source if personal else corpus.team_source}
    next_page = await work.page(claim.principal, after_sequence=None, limit=50)
    assert [e.work_id for e in next_page.entries] == [item.work_id]
    observation = await drafts.observe(claim.principal, path="coverage.json")
    await drafts.mutate(
        claim.principal,
        tool_call_id="current-coverage",
        request_digest="c" * 64,
        expected_draft_revision_id=observation.draft_revision_id,
        expected_observation_epoch=observation.observation_epoch,
        changes=[
            DraftFileChange(
                "coverage.json",
                observation.file_revision_id,
                coverage.model_dump_json(),
            )
        ],
    )
    publication = ConsolidationPublicationRepository(
        session_manager=manager, read_session_manager=manager
    )
    frozen = await publication.freeze(claim.principal)
    await work.record_coverage(
        claim.principal,
        expected_draft_revision_id=frozen.revision_id,
        coverage=frozen.coverage,
    )
    outcome = await publication.publish(
        claim.principal,
        expected_draft_revision_id=frozen.revision_id,
        expected_observation_epoch=frozen.observation_epoch,
        overview=validate_consolidation_overview(key=key, markdown=frozen.markdown),
    )
    assert outcome.revision_id != published_id
    async with manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(RDBConsolidationDraft.id).where(
                    RDBConsolidationDraft.unit_id == claim.unit_id
                )
            )
            is None
        )
        row = await session.read_session.get(RDBConsolidationWork, item.work_id)
        assert row is not None and row.state is ConsolidationWorkState.PUBLISHED


@pytest.mark.parametrize("cancelled", [False, True])
async def test_retry_start_requeues_unpublished_choices_and_isolates_peer(
    rdb_session_manager: SessionManager[WriteSession],
    cancelled: bool,
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    owners = ConsolidationOwnershipRepository(manager)
    first = await owners.claim(corpus.team, deadline=consolidation_deadline())
    peer = await owners.claim(corpus.personal, deadline=consolidation_deadline())
    assert first is not None and peer is not None
    drafts = ConsolidationDraftRepository(manager)
    work = ConsolidationWorkRepository(manager)
    for claim in (first, peer):
        page = await work.page(claim.principal, after_sequence=None, limit=50)
        observed = await drafts.observe(claim.principal, path="summary.md")
        change = await drafts.mutate(
            claim.principal,
            tool_call_id="unfinished",
            request_digest="d" * 64,
            expected_draft_revision_id=observed.draft_revision_id,
            expected_observation_epoch=observed.observation_epoch,
            changes=[
                DraftFileChange(
                    "summary.md", observed.file_revision_id, "Unfinished private work"
                )
            ],
        )
        await work.record_coverage(
            claim.principal,
            expected_draft_revision_id=change.draft_revision_id,
            coverage=ConsolidationCoverage(
                dispositions=(
                    ConsolidationWorkDisposition(
                        work_id=page.entries[0].work_id,
                        action=ConsolidationDisposition.CONSIDERED,
                        reason="Unpublished choice",
                    ),
                )
            ),
        )
    await owners.fail(first.principal, failure_code=None, cancelled=cancelled)
    async with manager() as session:
        await session.write_session.execute(
            sa.update(RDBConsolidationUnit)
            .where(RDBConsolidationUnit.id == first.unit_id)
            .values(retry_at=sa.func.clock_timestamp() - datetime.timedelta(seconds=1))
        )
    second = await owners.claim(corpus.team, deadline=consolidation_deadline())
    assert second is not None
    checkpoint = await ConsolidationRecoveryRepository(manager).prepare(
        second.principal
    )
    assert checkpoint.rebuilt and not checkpoint.published_available
    observed = await drafts.observe(second.principal, path="summary.md")
    assert observed.content is None
    assert (
        await drafts.observe(peer.principal, path="summary.md")
    ).content == "Unfinished private work"
    page = await work.page(second.principal, after_sequence=None, limit=50)
    assert len(page.entries) == 1
    async with manager() as session:
        for model in (RDBConsolidationEvidence, RDBConsolidationMutationReceipt):
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(model)
                    .where(model.attempt_id == first.principal.attempt_id)
                )
                == 0
            )
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(model)
                    .where(model.attempt_id == peer.principal.attempt_id)
                )
                == 1
            )


@pytest.mark.parametrize("cancel", [False, True])
async def test_start_cleanup_rollback_keeps_workspace_and_choices(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    manager = create_read_write_session_manager(rdb_engine)
    async with _committed_corpus(rdb_engine) as corpus:
        ready = await _ready_for_corpus(manager, corpus, empty=False, personal=False)

        async def abort(session: WriteSession, owner: LockedConsolidationOwner) -> None:
            await session.write_session.flush()
            if cancel:
                raise asyncio.CancelledError("startup rollback")
            raise RuntimeError("startup rollback")

        with monkeypatch.context() as patch:
            patch.setattr(recovery_module, "require_commit_owner", abort)
            with pytest.raises(
                asyncio.CancelledError if cancel else RuntimeError,
                match="startup rollback",
            ):
                await ConsolidationRecoveryRepository(manager).prepare(ready.principal)
        observation = await ConsolidationDraftRepository(manager).observe(
            ready.principal, path="summary.md"
        )
        assert observation.content == ready.frozen.markdown
        assert observation.draft_revision_id == ready.frozen.revision_id
        async with manager() as session:
            row = await session.read_session.get(RDBConsolidationWork, ready.work_id)
            assert row is not None and row.state is ConsolidationWorkState.CONSIDERED
        checkpoint = await ConsolidationRecoveryRepository(manager).prepare(
            ready.principal
        )
        assert checkpoint.rebuilt
        page = await ConsolidationWorkRepository(manager).page(
            ready.principal, after_sequence=None, limit=50
        )
        assert [entry.work_id for entry in page.entries] == [ready.work_id]


async def test_start_excludes_denied_publication_and_reselects_permitted_work(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    ready = await _ready_for_corpus(manager, corpus, empty=False, personal=False)
    await _publish(manager, ready)
    async with manager() as session:
        await create_consolidation_source(
            session,
            manager=manager,
            key=corpus.team,
            summary="Permitted later source",
            title="Current",
        )
        await AgentSessionRepository().archive(
            session, corpus.team_source, ended_at=datetime.datetime.now(datetime.UTC)
        )
    claim = await ConsolidationOwnershipRepository(manager).claim(
        corpus.team, deadline=consolidation_deadline()
    )
    assert claim is not None
    checkpoint = await ConsolidationRecoveryRepository(manager).prepare(claim.principal)
    assert not checkpoint.published_available
    assert (
        await ConsolidationDraftRepository(manager).observe(
            claim.principal, path="summary.md"
        )
    ).content is None
    page = await ConsolidationWorkRepository(manager).page(
        claim.principal, after_sequence=None, limit=50
    )
    assert (
        len(page.entries) == 1
        and page.entries[0].version.source_session_id != corpus.team_source
    )
