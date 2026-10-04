"""Disposable PostgreSQL forward, rollback and old-code reactivation rehearsals."""

import datetime

import pytest
import sqlalchemy as sa
from uuid6 import uuid7

from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.core.historical_memory import HistoricalMemoryCompletion
from azents.core.historical_memory_cutover import (
    MemoryHandoverAction,
    MemoryHandoverRequest,
)
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationDraft,
    RDBConsolidationEvidence,
    RDBConsolidationMutationReceipt,
    RDBConsolidationRevision,
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.models.memory import RDBAgentMemory
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
)
from azents.repos.historical_memory_consolidation.cutover import (
    MemoryHandoverRepository,
)
from azents.repos.historical_memory_consolidation.discovery import (
    ConsolidationDiscoveryRepository,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import MemoryCreate, MemoryScope
from azents.repos.memory_context_snapshot import MemoryContextSnapshotRepository
from azents.repos.message import MessageRepository
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.services.historical_memory.context_snapshot import (
    MemoryContextSnapshotService,
)
from azents.services.historical_memory.cutover import MemoryHandoverService
from azents.testing.consolidated_context import publish_context_overview
from azents.testing.consolidation import (
    consolidation_deadline,
    seed_consolidation_corpus,
)


def _service(manager: SessionManager[WriteSession]) -> MemoryContextSnapshotService:
    return MemoryContextSnapshotService(
        MemoryContextSnapshotRepository(
            HistoricalMemoryRepository(manager),
            MemoryRepository(),
            MessageRepository(),
            ToolkitStateRepository(),
            manager,
        )
    )


async def test_forward_backfills_prepared_sources_without_stage1_wait_or_body_changes(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    async with manager() as session:
        await session.write_session.execute(sa.delete(RDBConsolidationWork))
        await session.write_session.execute(
            sa.update(RDBHistoricalMemorySource).values(
                summary_generation=0, evidence_hash=None
            )
        )
        sources_before = list(
            (
                await session.write_session.execute(
                    sa.select(
                        RDBHistoricalMemorySource.source_session_id,
                        RDBHistoricalMemorySource.summary,
                        RDBHistoricalMemorySource.prepared_at,
                    )
                )
            ).all()
        )
        session.write_session.add(
            RDBToolkitState(
                agent_id=corpus.team.agent_id,
                session_id=corpus.team_source,
                toolkit_namespace="memory",
                state_name="context_snapshot",
                schema_version=1,
                state_json={"schema_version": 1, "old_body": "Old automatic context"},
            )
        )
    result = await MemoryHandoverService(manager).handover(
        MemoryHandoverRequest(MemoryHandoverAction.FORWARD, True, 1)
    )
    assert result.snapshots_reset == 1 and result.sources_reconciled == 2
    due = await ConsolidationDiscoveryRepository(manager).list_due(
        agent_id=corpus.team.agent_id, limit=10
    )
    assert set(due) == {corpus.team, corpus.personal}
    async with manager() as session:
        assert (
            list(
                (
                    await session.write_session.execute(
                        sa.select(
                            RDBHistoricalMemorySource.source_session_id,
                            RDBHistoricalMemorySource.summary,
                            RDBHistoricalMemorySource.prepared_at,
                        )
                    )
                ).all()
            )
            == sources_before
        )
        assert (
            await session.write_session.scalar(
                sa.select(sa.func.count()).select_from(RDBToolkitState)
            )
            == 0
        )
        count = await session.write_session.scalar(
            sa.select(sa.func.count()).select_from(RDBConsolidationWork)
        )
    again = await MemoryHandoverService(manager).handover(
        MemoryHandoverRequest(MemoryHandoverAction.FORWARD, True, 1)
    )
    assert again.snapshots_reset == 0
    async with manager() as session:
        assert (
            await session.write_session.scalar(
                sa.select(sa.func.count()).select_from(RDBConsolidationWork)
            )
            == count
        )
        assert all(
            source.summary_generation == 1
            for source in await session.write_session.scalars(
                sa.select(RDBHistoricalMemorySource)
            )
        )


async def test_explicit_rollback_and_reactivation_preserve_root_child_runs_and_saved(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    old_revisions = []
    for key, source in [
        (corpus.team, corpus.team_source),
        (corpus.personal, corpus.personal_source),
    ]:
        old_revisions.append(
            await publish_context_overview(
                manager,
                key=key,
                markdown=(
                    "## Historical Context\nPre-rollback derived bytes\n\n"
                    "## Source Routes\n"
                    f"- azents://memory/historical/{key.scope.value}/{source}/summary.md"
                    " — Details\n"
                ),
            )
        )
    async with manager() as session:
        saved = await MemoryRepository().create(
            session,
            agent_id=corpus.team.agent_id,
            user_id=None,
            create=MemoryCreate(
                scope=MemoryScope.AGENT,
                type="project",
                name="Saved survives handover",
                description="Independent knowledge",
                content="Unchanged canonical Saved body",
            ),
        )
        repository = AgentSessionRepository()
        root = await repository.get_session_agent_by_session_id(
            session, corpus.personal_source
        )
        assert root is not None
        child = await repository.create_child_session_agent(
            session,
            parent_session_agent_id=root.id,
            name="child",
            agent_type="default",
            title="Interrupted child",
            last_task_message=None,
        )
        run_ids = []
        for source in (corpus.personal_source, child.agent_session_id):
            run = RDBAgentRun(
                session_id=source,
                scheduled_task_cycle_id=None,
                run_index=1,
                parent_agent_run_id=None,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                requested_enabled_execution_options=[],
                phase=AgentRunPhase.WAITING_FOR_MODEL,
                status=AgentRunStatus.INTERRUPTED,
            )
            session.write_session.add(run)
            event = RDBEvent(
                session_id=source,
                kind=EventKind.COMPACTION_SUMMARY,
                payload={"compaction_id": uuid7().hex, "content": "Retained history"},
            )
            session.write_session.add(event)
            await session.write_session.flush()
            run_ids.append(run.id)
        events_before = list(
            (
                await session.write_session.execute(
                    sa.select(
                        RDBEvent.id, RDBEvent.session_id, RDBEvent.payload
                    ).order_by(RDBEvent.id)
                )
            ).all()
        )
    snapshot_service = _service(manager)
    assert await snapshot_service.refresh_snapshot(
        session_id=corpus.personal_source,
        after_compaction=False,
    )
    now = datetime.datetime.now(datetime.UTC)
    await HistoricalMemoryRepository(manager).publish_completed(
        source_session_id=corpus.team_source,
        completion=HistoricalMemoryCompletion(
            source_activity_at=now,
            source_tail_event_id=uuid7().hex,
            prepared_at=now,
            source_title_snapshot="Pending before handover",
            summary="Pending current source",
        ),
    )
    claim = await ConsolidationOwnershipRepository(manager).claim(
        corpus.team, deadline=consolidation_deadline()
    )
    assert claim is not None
    await ConsolidationDraftRepository(manager).observe(
        claim.principal, path="summary.md"
    )
    rollback = await MemoryHandoverService(manager).handover(
        MemoryHandoverRequest(MemoryHandoverAction.ROLLBACK, True, 1)
    )
    assert rollback.snapshots_reset == 1 and rollback.units_fenced == 2
    assert rollback.sources_reconciled == 0
    with pytest.raises(ConsolidationAuthorityError):
        await ConsolidationDraftRepository(manager).observe(
            claim.principal, path="summary.md"
        )
    async with manager() as session:
        for identity in old_revisions:
            assert (
                await session.write_session.get(RDBConsolidationRevision, identity)
                is not None
            )
        changed = await session.write_session.get(
            RDBHistoricalMemorySource, corpus.team_source
        )
        personal = await session.write_session.get(
            RDBHistoricalMemorySource, corpus.personal_source
        )
        assert changed is not None and personal is not None
        # Emulate the previous application: no new generation/outbox maintenance.
        changed.summary = "Canonical body written by old application"
        original_generation = changed.summary_generation
        unchanged_personal_generation = personal.summary_generation
        original_personal_hash = personal.evidence_hash
        session.write_session.add(
            RDBToolkitState(
                agent_id=corpus.team.agent_id,
                session_id=corpus.personal_source,
                toolkit_namespace="memory",
                state_name="context_snapshot",
                schema_version=1,
                state_json={
                    "schema_version": 1,
                    "old_body": "Previous-version snapshot",
                },
            )
        )
    reactivated = await MemoryHandoverService(manager).handover(
        MemoryHandoverRequest(MemoryHandoverAction.REACTIVATE, True, 1)
    )
    assert reactivated.snapshots_reset == 1 and reactivated.sources_reconciled == 2
    async with manager() as session:
        for table in (
            RDBConsolidationRevision,
            RDBConsolidationDraft,
            RDBConsolidationEvidence,
            RDBConsolidationMutationReceipt,
        ):
            assert (
                await session.write_session.scalar(
                    sa.select(sa.func.count()).select_from(table)
                )
                == 0
            )
        assert all(
            unit.published_revision_id is None
            for unit in await session.write_session.scalars(
                sa.select(RDBConsolidationUnit)
            )
        )
        changed = await session.write_session.get(
            RDBHistoricalMemorySource, corpus.team_source
        )
        personal = await session.write_session.get(
            RDBHistoricalMemorySource, corpus.personal_source
        )
        assert changed is not None and personal is not None
        assert changed.summary == "Canonical body written by old application"
        assert changed.summary_generation == original_generation + 1
        assert personal.summary_generation == unchanged_personal_generation
        assert personal.evidence_hash == original_personal_hash
        assert await session.write_session.get(RDBAgentMemory, saved.id) is not None
        assert (
            list(
                (
                    await session.write_session.execute(
                        sa.select(
                            RDBEvent.id, RDBEvent.session_id, RDBEvent.payload
                        ).order_by(RDBEvent.id)
                    )
                ).all()
            )
            == events_before
        )
        for identity in run_ids:
            run = await session.write_session.get(RDBAgentRun, identity)
            assert run is not None and run.status is AgentRunStatus.INTERRUPTED
            assert run.phase is AgentRunPhase.WAITING_FOR_MODEL
    due = await ConsolidationDiscoveryRepository(manager).list_due(
        agent_id=corpus.team.agent_id, limit=10
    )
    assert set(due) == {corpus.team, corpus.personal}
    assert (
        await snapshot_service.prompt_for_turn(session_id=corpus.personal_source) == ""
    )
    assert await snapshot_service.refresh_snapshot(
        session_id=corpus.personal_source,
        after_compaction=False,
    )
    prompt = await snapshot_service.prompt_for_turn(session_id=corpus.personal_source)
    assert (
        "Saved survives handover" in prompt
        and "Pre-rollback derived bytes" not in prompt
    )
    assert "Canonical body written by old application" not in prompt


@pytest.mark.parametrize("action", list(MemoryHandoverAction))
async def test_handover_refuses_unconfirmed_execution_quiescence(
    rdb_session_manager: SessionManager[WriteSession],
    action: MemoryHandoverAction,
) -> None:
    with pytest.raises(ValueError, match="quiesced"):
        await MemoryHandoverService(rdb_session_manager).handover(
            MemoryHandoverRequest(action, False, 1)
        )


async def test_unit_handover_cannot_run_before_snapshot_reset(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    assert await _service(manager).refresh_snapshot(
        session_id=corpus.team_source, after_compaction=False
    )
    with pytest.raises(ValueError, match="reset"):
        await MemoryHandoverRepository(manager).fence_units(
            request=MemoryHandoverRequest(MemoryHandoverAction.REACTIVATE, True, 1),
            after=None,
        )
