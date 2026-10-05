"""Discover and prelock complete participants before serializing the unit.

The operation plan is not authority. Exact owner/grant admission and complete
current influence checks still run after the waits under unit serialization.
"""

from dataclasses import dataclass
from typing import assert_never

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationDraft,
    RDBConsolidationDraftDependency,
    RDBConsolidationEvidence,
    RDBConsolidationRevisionDependency,
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.historical_memory_consolidation.participant_types import (
    ConsolidationParticipantRequest,
    ConsolidationPlanChangedError,
    DraftParticipants,
    SourceInventoryParticipants,
    SourceReadParticipants,
    WorkPageParticipants,
)


@dataclass(frozen=True)
class ParticipantAnchor:
    """Detached exact mutation anchors, not a permission or ownership grant."""

    unit_id: str
    attempt_id: str
    owner_generation: int
    owner_token: str
    observation_epoch: int
    pass_upper_sequence: int
    membership_grant_id: str | None
    published_revision_id: str | None
    draft_id: str | None
    draft_revision_id: str | None
    draft_invalidated: bool | None


@dataclass(frozen=True)
class ConsolidationParticipantPlan:
    anchor: ParticipantAnchor
    request: ConsolidationParticipantRequest
    candidates: tuple[tuple[str, str], ...]
    source_ids: tuple[str, ...]
    locked_root_ids: frozenset[str]
    locked_source_ids: frozenset[str]

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(identity for identity, _source in self.candidates)


def _anchor_query(
    principal: ConsolidationJobPrincipal,
) -> sa.Select[
    tuple[RDBConsolidationUnit, RDBConsolidationAttempt, RDBConsolidationDraft]
]:
    unit = RDBConsolidationUnit
    attempt = RDBConsolidationAttempt
    return (
        sa.select(unit, attempt, RDBConsolidationDraft)
        .join(attempt, attempt.id == unit.active_attempt_id)
        .outerjoin(RDBConsolidationDraft, RDBConsolidationDraft.unit_id == unit.id)
        .where(
            unit.agent_id == principal.unit.agent_id,
            unit.workspace_id == principal.unit.workspace_id,
            unit.scope == principal.unit.scope,
            unit.associated_user_id.is_not_distinct_from(
                principal.unit.associated_user_id
            ),
            unit.active_attempt_id == principal.attempt_id,
            unit.owner_generation == principal.owner_generation,
            unit.owner_token == principal.owner_token,
            attempt.unit_id == unit.id,
            attempt.owner_generation == principal.owner_generation,
            attempt.owner_token == principal.owner_token,
        )
        .execution_options(populate_existing=True)
    )


async def observe_participant_anchor(
    session: ReadSession, principal: ConsolidationJobPrincipal
) -> ParticipantAnchor:
    row = (await session.read_session.execute(_anchor_query(principal))).one_or_none()
    if row is None:
        raise ConsolidationPlanChangedError("Consolidation participant owner changed.")
    unit, attempt, draft = row
    return ParticipantAnchor(
        unit.id,
        attempt.id,
        unit.owner_generation,
        attempt.owner_token,
        attempt.observation_epoch,
        attempt.pass_upper_sequence,
        attempt.membership_grant_id,
        unit.published_revision_id,
        None if draft is None else draft.id,
        None if draft is None else draft.revision_id,
        None if draft is None else draft.invalidated,
    )


def _anchor_guard(
    principal: ConsolidationJobPrincipal, anchor: ParticipantAnchor
) -> sa.ColumnElement[bool]:
    draft = RDBConsolidationDraft
    return (
        _anchor_query(principal)
        .with_only_columns(RDBConsolidationUnit.id)
        .where(
            RDBConsolidationUnit.id == anchor.unit_id,
            RDBConsolidationAttempt.observation_epoch == anchor.observation_epoch,
            RDBConsolidationAttempt.pass_upper_sequence == anchor.pass_upper_sequence,
            RDBConsolidationAttempt.membership_grant_id.is_not_distinct_from(
                anchor.membership_grant_id
            ),
            RDBConsolidationUnit.published_revision_id.is_not_distinct_from(
                anchor.published_revision_id
            ),
            draft.id.is_not_distinct_from(anchor.draft_id),
            draft.revision_id.is_not_distinct_from(anchor.draft_revision_id),
            draft.invalidated.is_not_distinct_from(anchor.draft_invalidated),
        )
        .exists()
    )


async def _candidate_rows(
    session: ReadSession,
    principal: ConsolidationJobPrincipal,
    anchor: ParticipantAnchor,
    request: ConsolidationParticipantRequest,
) -> tuple[tuple[str, str], ...]:
    match request:
        case DraftParticipants():
            return ()
        case SourceReadParticipants(source_session_id=source_id):
            return ((source_id, source_id),)
        case SourceInventoryParticipants():
            # Deferred imports break the source/authority composition cycle;
            # these are the exact existing eligibility/pagination predicates.
            from azents.repos.historical_memory_consolidation.sources import (  # noqa: PLC0415
                source_predicate,
            )  # noqa: PLC0415

            query = (
                sa.select(RDBHistoricalMemorySource.source_session_id)
                .join(
                    RDBAgentSession,
                    RDBAgentSession.id == RDBHistoricalMemorySource.source_session_id,
                )
                .where(
                    source_predicate(principal.unit),
                    RDBHistoricalMemorySource.prepared_at.is_not(None),
                    RDBHistoricalMemorySource.summary_generation > 0,
                    RDBHistoricalMemorySource.evidence_hash.is_not(None),
                )
                .order_by(RDBHistoricalMemorySource.source_session_id)
                .limit(request.limit + 1)
            )
            if request.after is not None:
                query = query.where(
                    RDBHistoricalMemorySource.source_session_id > request.after
                )
            prefix = request.source_id_prefix
            if prefix is not None:
                query = query.where(
                    RDBHistoricalMemorySource.source_session_id == prefix
                    if len(prefix) == 32
                    else RDBHistoricalMemorySource.source_session_id.startswith(prefix)
                )
            return tuple(
                (source_id, source_id)
                for source_id in await session.read_session.scalars(query)
            )
        case WorkPageParticipants():
            from azents.repos.historical_memory_consolidation.work import (  # noqa: PLC0415
                pending_work_query,
            )  # noqa: PLC0415

            query = (
                pending_work_query(principal.unit, anchor.membership_grant_id)
                .with_only_columns(
                    RDBConsolidationWork.id, RDBConsolidationWork.source_session_id
                )
                .where(RDBConsolidationWork.sequence <= anchor.pass_upper_sequence)
            )
            if request.after_sequence is not None:
                query = query.where(
                    RDBConsolidationWork.sequence > request.after_sequence
                )
            rows = await session.read_session.execute(
                query.order_by(RDBConsolidationWork.sequence).limit(request.limit + 1)
            )
            return tuple((row.id, row.source_session_id) for row in rows)
        case _:
            assert_never(request)


def _planned_sources(
    principal: ConsolidationJobPrincipal,
    anchor: ParticipantAnchor,
    request: ConsolidationParticipantRequest,
    candidates: tuple[tuple[str, str], ...],
) -> sa.Select[tuple[str]]:
    if isinstance(request, DraftParticipants):
        selects = [
            sa.select(RDBConsolidationDraftDependency.source_session_id).where(
                RDBConsolidationDraftDependency.draft_id == anchor.draft_id
            ),
            sa.select(RDBConsolidationEvidence.source_session_id).where(
                RDBConsolidationEvidence.attempt_id == anchor.attempt_id
            ),
        ]
        if request.recovery or anchor.draft_id is None:
            selects.append(
                sa.select(RDBConsolidationRevisionDependency.source_session_id).where(
                    RDBConsolidationRevisionDependency.revision_id
                    == anchor.published_revision_id
                )
            )
        influence = sa.union_all(*selects).subquery("planned_complete_influence")
        return (
            sa.select(influence.c.source_session_id)
            .distinct()
            .where(_anchor_guard(principal, anchor))
        )
    # Exposed candidate pages are already bounded by the existing page+lookahead.
    source_ids = sorted({source for _identity, source in candidates})
    if not source_ids:
        return sa.select(sa.literal("").label("source_session_id")).where(sa.false())
    return (
        sa.union(
            *(
                sa.select(sa.literal(source_id).label("source_session_id"))
                for source_id in source_ids
            )
        )
        .subquery("planned_exposure_sources")
        .select()
        .where(_anchor_guard(principal, anchor))
    )


def _root_rows(
    principal: ConsolidationJobPrincipal, source_ids: sa.Select[tuple[str]]
) -> sa.Select[tuple[str]]:
    from azents.repos.historical_memory_consolidation.sources import (  # noqa: PLC0415
        source_identity_predicate,
    )

    return sa.select(RDBAgentSession.id).where(
        RDBAgentSession.id.in_(source_ids), source_identity_predicate(principal.unit)
    )


def _source_rows(
    principal: ConsolidationJobPrincipal, source_ids: sa.Select[tuple[str]]
) -> sa.Select[tuple[str]]:
    from azents.repos.historical_memory_consolidation.sources import (  # noqa: PLC0415
        source_identity_predicate,
    )

    return (
        sa.select(RDBHistoricalMemorySource.source_session_id)
        .join(
            RDBAgentSession,
            RDBAgentSession.id == RDBHistoricalMemorySource.source_session_id,
        )
        .where(
            RDBHistoricalMemorySource.source_session_id.in_(source_ids),
            source_identity_predicate(principal.unit),
        )
    )


async def _exact_source_ids(
    session: ReadSession, query: sa.Select[tuple[str]]
) -> tuple[str, ...]:
    """Capture routing UUIDs only; full version/body validation stays server-side."""
    ids = query.subquery("complete_participant_ids")
    return tuple(
        await session.read_session.scalars(
            sa.select(ids.c.source_session_id)
            .distinct()
            .order_by(ids.c.source_session_id)
        )
    )


def _frozen_source_ids(
    principal: ConsolidationJobPrincipal,
    anchor: ParticipantAnchor,
    source_ids: tuple[str, ...],
) -> sa.Select[tuple[str]]:
    """Lock an exact uncapped ID array, not a moving discovery relation."""
    return sa.select(
        sa.func.unnest(sa.literal(list(source_ids), type_=ARRAY(sa.Text()))).label(
            "source_session_id"
        )
    ).where(_anchor_guard(principal, anchor))


async def prelock_participants(
    session: WriteSession,
    principal: ConsolidationJobPrincipal,
    request: ConsolidationParticipantRequest,
) -> ConsolidationParticipantPlan:
    anchor = await observe_participant_anchor(session, principal)
    candidates = await _candidate_rows(session, principal, anchor, request)
    source_ids = await _exact_source_ids(
        session, _planned_sources(principal, anchor, request, candidates)
    )
    ids = _frozen_source_ids(principal, anchor, source_ids)
    # Missing/denied rows are NOT a plan race. Lock every still-existing row,
    # then let current authority/manifest checks perform normal denial/recovery.
    roots = (
        _root_rows(principal, ids)
        .order_by(RDBAgentSession.id)
        .with_for_update(read=True)
        .subquery()
    )
    root_ids = frozenset(await session.write_session.scalars(sa.select(roots.c.id)))
    sources = (
        _source_rows(principal, ids)
        .order_by(RDBHistoricalMemorySource.source_session_id)
        .with_for_update(read=True, of=RDBHistoricalMemorySource)
        .subquery()
    )
    source_ids_locked = frozenset(
        await session.write_session.scalars(sa.select(sources.c.source_session_id))
    )
    return ConsolidationParticipantPlan(
        anchor, request, candidates, source_ids, root_ids, source_ids_locked
    )


async def validate_participant_plan(
    session: ReadSession,
    principal: ConsolidationJobPrincipal,
    plan: ConsolidationParticipantPlan,
) -> None:
    current = await observe_participant_anchor(session, principal)
    if current != plan.anchor:
        raise ConsolidationPlanChangedError("Consolidation influence anchors changed.")
    candidates = await _candidate_rows(session, principal, current, plan.request)
    if candidates != plan.candidates:
        raise ConsolidationPlanChangedError(
            "Consolidation exposure candidates changed."
        )
    # Source membership is anchored by immutable revision dependencies, draft
    # revision/presence and the monotonically advanced exposure epoch. Both lock
    # queries use that same guard; changes release all locks and replan. Current
    # source permission/version checks still run independently after admission.
    ids = _planned_sources(principal, current, plan.request, candidates)
    actual = await _exact_source_ids(session, ids)
    if actual != plan.source_ids:
        raise ConsolidationPlanChangedError("Consolidation complete influence changed.")
    # Missing/denied members stay a normal authority/recovery result. Only
    # eligibility movement that would require a new, unlocked participant
    # triggers replanning; stable denial must not become a perpetual retry.
    roots = frozenset(await session.read_session.scalars(_root_rows(principal, ids)))
    sources = frozenset(
        await session.read_session.scalars(_source_rows(principal, ids))
    )
    if roots != plan.locked_root_ids or sources != plan.locked_source_ids:
        raise ConsolidationPlanChangedError(
            "Consolidation participant eligibility changed."
        )
