"""Bounded offline snapshot reset, owner fencing and canonical reconciliation."""

import dataclasses

import sqlalchemy as sa

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionProductMode,
    AgentSessionStatus,
)
from azents.core.historical_memory import HistoricalMemoryCompletion
from azents.core.historical_memory_consolidation import (
    ConsolidationAttemptState,
    ConsolidationScope,
    ConsolidationUnitKey,
    ConsolidationWorkKind,
    ConsolidationWorkState,
    prepared_source_evidence_hash,
)
from azents.core.historical_memory_cutover import (
    MemoryHandoverAction,
    MemoryHandoverPage,
    MemoryHandoverRequest,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationDraft,
    RDBConsolidationEvidence,
    RDBConsolidationMutationReceipt,
    RDBConsolidationRevision,
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityBusyError,
    consolidation_session,
    database_now,
)
from azents.repos.historical_memory_consolidation.enrollment import (
    enroll_source_in_session,
)
from azents.repos.historical_memory_consolidation.retry import (
    retry_rolled_back_operation,
)
from azents.repos.historical_memory_consolidation.work import work_predicate


class MemoryHandoverPageChanged(ConsolidationAuthorityBusyError):
    """An exact page plan changed before its participants were acquired."""


@dataclasses.dataclass(frozen=True)
class MemorySourceHandoverCandidate:
    """Detached lock routing keys, not source permission or publication authority."""

    source_session_id: str
    agent_id: str
    workspace_id: str
    product_mode: AgentSessionProductMode
    associated_user_id: str | None


async def _source_candidates(
    session: WriteSession, *, request: MemoryHandoverRequest, after: str | None
) -> tuple[MemorySourceHandoverCandidate, ...]:
    query = (
        sa.select(
            RDBHistoricalMemorySource.source_session_id,
            RDBAgent.id.label("agent_id"),
            RDBAgentSession.workspace_id,
            RDBAgentSession.product_mode,
            RDBAgentSession.associated_user_id,
        )
        .join(
            RDBAgentSession,
            RDBAgentSession.id == RDBHistoricalMemorySource.source_session_id,
        )
        .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
        .where(
            RDBHistoricalMemorySource.prepared_at.is_not(None),
            RDBAgentSession.product_mode.is_not(None),
        )
        .order_by(RDBHistoricalMemorySource.source_session_id)
        .limit(request.batch_size)
    )
    if after is not None:
        query = query.where(RDBHistoricalMemorySource.source_session_id > after)
    candidates = []
    for row in await session.write_session.execute(query):
        if row.product_mode is None:
            raise RuntimeError("Memory handover source scope is missing.")
        candidates.append(
            MemorySourceHandoverCandidate(
                row.source_session_id,
                row.agent_id,
                row.workspace_id,
                row.product_mode,
                row.associated_user_id,
            )
        )
    return tuple(candidates)


async def _require_snapshots_reset(session: WriteSession) -> None:
    if await session.write_session.scalar(
        sa.select(sa.select(RDBToolkitState.id).where(_snapshot_predicate()).exists())
    ):
        raise ValueError("Memory snapshots must be reset before ownership handover.")


def _snapshot_predicate() -> sa.ColumnElement[bool]:
    return sa.and_(
        RDBToolkitState.toolkit_namespace == "memory",
        RDBToolkitState.state_name == "context_snapshot",
    )


@dataclasses.dataclass(frozen=True)
class MemoryHandoverRepository:
    """Requires operator-owned quiescence; never controls live infrastructure."""

    session_manager: SessionManager[WriteSession]

    @retry_rolled_back_operation
    async def reset_snapshots(
        self,
        *,
        request: MemoryHandoverRequest,
        after: str | None,
    ) -> MemoryHandoverPage:
        request.validate()
        async with consolidation_session(self.session_manager) as session:
            query = sa.select(RDBToolkitState.id).where(_snapshot_predicate())
            if after is not None:
                query = query.where(RDBToolkitState.id > after)
            ids = list(
                await session.write_session.scalars(
                    query.order_by(RDBToolkitState.id).limit(request.batch_size)
                )
            )
            if ids:
                await session.write_session.execute(
                    sa.delete(RDBToolkitState).where(RDBToolkitState.id.in_(ids))
                )
        return MemoryHandoverPage(len(ids), ids[-1] if ids else None)

    @retry_rolled_back_operation
    async def fence_units(
        self,
        *,
        request: MemoryHandoverRequest,
        after: str | None,
    ) -> MemoryHandoverPage:
        request.validate()
        async with consolidation_session(self.session_manager) as session:
            await _require_snapshots_reset(session)
            query = sa.select(RDBConsolidationUnit)
            if after is not None:
                query = query.where(RDBConsolidationUnit.id > after)
            units = list(
                await session.write_session.scalars(
                    query.order_by(RDBConsolidationUnit.id)
                    .limit(request.batch_size)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            # A wait is not proof of failed quiescence. Check the actual existing
            # precondition again after waiting, before accepting any mutation.
            await _require_snapshots_reset(session)
            now = await database_now(session)
            for unit in units:
                key = ConsolidationUnitKey(
                    agent_id=unit.agent_id,
                    workspace_id=unit.workspace_id,
                    scope=unit.scope,
                    associated_user_id=unit.associated_user_id,
                )
                attempts = sa.select(RDBConsolidationAttempt.id).where(
                    RDBConsolidationAttempt.unit_id == unit.id
                )
                await session.write_session.execute(
                    sa.update(RDBConsolidationAttempt)
                    .where(
                        RDBConsolidationAttempt.unit_id == unit.id,
                        RDBConsolidationAttempt.state
                        == ConsolidationAttemptState.RUNNING,
                    )
                    .values(
                        state=ConsolidationAttemptState.CANCELLED,
                        failure_code=None,
                        finished_at=now,
                    )
                )
                unit.owner_generation += 1
                unit.active_attempt_id = None
                unit.owner_token = None
                unit.lease_until = None
                unit.pass_upper_sequence = None
                unit.retry_at = None
                unit.no_progress_count = 0
                if request.action is MemoryHandoverAction.REACTIVATE:
                    # Old application code cannot attest to denial continuity.
                    # Discard the entire derived graph, even when hashes match.
                    unit.published_revision_id = None
                    await session.write_session.execute(
                        sa.update(RDBConsolidationWork)
                        .where(work_predicate(key))
                        .values(
                            state=ConsolidationWorkState.SUPERSEDED,
                            considered_draft_id=None,
                            considered_draft_revision_id=None,
                            disposition=None,
                            consideration_reason=None,
                            presented_attempt_id=None,
                            published_revision_id=None,
                        )
                    )
                    await session.write_session.execute(
                        sa.delete(RDBConsolidationDraft).where(
                            RDBConsolidationDraft.unit_id == unit.id
                        )
                    )
                    await session.write_session.execute(
                        sa.delete(RDBConsolidationEvidence).where(
                            RDBConsolidationEvidence.attempt_id.in_(attempts)
                        )
                    )
                    await session.write_session.execute(
                        sa.delete(RDBConsolidationMutationReceipt).where(
                            RDBConsolidationMutationReceipt.attempt_id.in_(attempts)
                        )
                    )
                    await session.write_session.execute(
                        sa.delete(RDBConsolidationRevision).where(
                            RDBConsolidationRevision.unit_id == unit.id
                        )
                    )
                await session.write_session.flush()
        return MemoryHandoverPage(len(units), units[-1].id if units else None)

    @retry_rolled_back_operation
    async def reconcile_sources(
        self,
        *,
        request: MemoryHandoverRequest,
        after: str | None,
    ) -> MemoryHandoverPage:
        request.validate()
        if request.action is MemoryHandoverAction.ROLLBACK:
            raise ValueError("Rollback leaves additive consolidation storage inert.")
        async with consolidation_session(self.session_manager) as session:
            candidates = await _source_candidates(session, request=request, after=after)
            ids = [candidate.source_session_id for candidate in candidates]
            agents = {
                agent.id: agent
                for agent in await session.write_session.scalars(
                    sa.select(RDBAgent)
                    .where(
                        RDBAgent.id.in_(
                            {candidate.agent_id for candidate in candidates}
                        )
                    )
                    .order_by(RDBAgent.id)
                    .with_for_update(key_share=True)
                    .execution_options(populate_existing=True)
                )
            }
            membership_keys = sorted(
                {
                    (candidate.workspace_id, candidate.associated_user_id)
                    for candidate in candidates
                    if candidate.product_mode is AgentSessionProductMode.USER
                    and candidate.associated_user_id is not None
                }
            )
            grants: dict[tuple[str, str], str] = {}
            for workspace_id, user_id in membership_keys:
                grant = await session.write_session.scalar(
                    sa.select(RDBWorkspaceUser.memory_grant_identity)
                    .where(
                        RDBWorkspaceUser.workspace_id == workspace_id,
                        RDBWorkspaceUser.user_id == user_id,
                    )
                    .with_for_update()
                )
                if grant is not None:
                    grants[(workspace_id, user_id)] = grant
            roots = {
                root.id: root
                for root in await session.write_session.scalars(
                    sa.select(RDBAgentSession)
                    .where(RDBAgentSession.id.in_(ids))
                    .order_by(RDBAgentSession.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            }
            sources = {
                source.source_session_id: source
                for source in await session.write_session.scalars(
                    sa.select(RDBHistoricalMemorySource)
                    .where(RDBHistoricalMemorySource.source_session_id.in_(ids))
                    .order_by(RDBHistoricalMemorySource.source_session_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            }
            current = await _source_candidates(session, request=request, after=after)
            if current != candidates:
                raise MemoryHandoverPageChanged(
                    "Memory handover candidate page changed."
                )
            for candidate in current:
                source = sources[candidate.source_session_id]
                root = roots[candidate.source_session_id]
                agent = agents[candidate.agent_id]
                if (
                    source.prepared_at is None
                    or source.completed_source_activity_at is None
                    or source.completed_source_tail_event_id is None
                ):
                    raise ValueError(
                        "Prepared canonical source metadata is incomplete."
                    )
                completion = HistoricalMemoryCompletion(
                    source_activity_at=source.completed_source_activity_at,
                    source_tail_event_id=source.completed_source_tail_event_id,
                    prepared_at=source.prepared_at,
                    source_title_snapshot=source.source_title_snapshot,
                    summary=source.summary,
                )
                current_hash = prepared_source_evidence_hash(completion)
                if (
                    current_hash != source.evidence_hash
                    or source.summary_generation < 1
                ):
                    source.summary_generation += 1
                    source.evidence_hash = current_hash
                if (
                    root.status is not AgentSessionStatus.ACTIVE
                    or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
                    or not agent.memory_enabled
                ):
                    continue
                grant = None
                if root.product_mode is AgentSessionProductMode.USER:
                    grant = (
                        grants.get((root.workspace_id, root.associated_user_id))
                        if root.associated_user_id is not None
                        else None
                    )
                    if grant is None:
                        continue
                await enroll_source_in_session(
                    session,
                    source=source,
                    root=root,
                    kind=ConsolidationWorkKind.PREPARED,
                )
                if request.action is MemoryHandoverAction.REACTIVATE:
                    # Reuse an identical existing metadata enrollment idempotently.
                    # No prior draft, revision or receipt remains to supply input.
                    await session.write_session.execute(
                        sa.update(RDBConsolidationWork)
                        .where(
                            RDBConsolidationWork.agent_id == root.agent_id,
                            RDBConsolidationWork.workspace_id == root.workspace_id,
                            RDBConsolidationWork.scope
                            == (
                                ConsolidationScope.TEAM
                                if root.product_mode is AgentSessionProductMode.TEAM
                                else ConsolidationScope.USER
                            ),
                            RDBConsolidationWork.associated_user_id.is_not_distinct_from(
                                root.associated_user_id
                            ),
                            RDBConsolidationWork.source_session_id
                            == source.source_session_id,
                            RDBConsolidationWork.summary_generation
                            == source.summary_generation,
                            RDBConsolidationWork.evidence_hash == current_hash,
                            RDBConsolidationWork.availability_generation
                            == source.availability_generation,
                            RDBConsolidationWork.membership_grant_id.is_not_distinct_from(
                                grant
                            ),
                            RDBConsolidationWork.kind == ConsolidationWorkKind.PREPARED,
                        )
                        .values(state=ConsolidationWorkState.PENDING)
                    )
            await session.write_session.flush()
        return MemoryHandoverPage(
            len(current), current[-1].source_session_id if current else None
        )
