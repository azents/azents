"""Finite exact work pages and draft-bound choices, never scalar coverage watermarks."""

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.historical_memory_consolidation import (
    ConsolidationJobPrincipal,
    ConsolidationSourceVersion,
    ConsolidationUnitKey,
    ConsolidationWorkKind,
    ConsolidationWorkState,
)
from azents.core.historical_memory_publication import ConsolidationCoverage
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationDraft,
    RDBConsolidationDraftDependency,
    RDBConsolidationEvidence,
    RDBConsolidationWork,
)
from azents.rdb.session import SessionManager
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
    consolidation_job_session,
    require_commit_owner,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftConflict,
    check_draft_influence,
)
from azents.repos.historical_memory_consolidation.sources import (
    lock_source,
    record_evidence,
    source_predicate,
)


@dataclass(frozen=True)
class ConsolidationWorkEntry:
    """Only one exact corpus's currently supplied work and evidence identity."""

    work_id: str
    sequence: int
    kind: ConsolidationWorkKind
    version: ConsolidationSourceVersion
    title: str | None


@dataclass(frozen=True)
class ConsolidationWorkPage:
    """A bounded finite-pass page with no assumption about later commit ordering."""

    entries: tuple[ConsolidationWorkEntry, ...]
    next_after_sequence: int | None
    pass_upper_sequence: int
    observation_epoch: int


def work_predicate(key: ConsolidationUnitKey) -> sa.ColumnElement[bool]:
    return sa.and_(
        RDBConsolidationWork.agent_id == key.agent_id,
        RDBConsolidationWork.workspace_id == key.workspace_id,
        RDBConsolidationWork.scope == key.scope,
        RDBConsolidationWork.associated_user_id.is_not_distinct_from(
            key.associated_user_id
        ),
    )


def pending_work_query(
    key: ConsolidationUnitKey, grant: str | None
) -> sa.Select[tuple[RDBConsolidationWork]]:
    """Current eligible work, including recoverable choices but no denied body."""
    return (
        sa.select(RDBConsolidationWork)
        .join(
            RDBAgentSession,
            RDBAgentSession.id == RDBConsolidationWork.source_session_id,
        )
        .join(
            RDBHistoricalMemorySource,
            RDBHistoricalMemorySource.source_session_id == RDBAgentSession.id,
        )
        .where(
            work_predicate(key),
            source_predicate(key),
            RDBConsolidationWork.state.in_(
                [ConsolidationWorkState.PENDING, ConsolidationWorkState.CONSIDERED]
            ),
            RDBConsolidationWork.kind != ConsolidationWorkKind.REMOVED,
            RDBHistoricalMemorySource.prepared_at.is_not(None),
            RDBHistoricalMemorySource.summary_generation > 0,
            RDBHistoricalMemorySource.summary_generation
            == RDBConsolidationWork.summary_generation,
            RDBHistoricalMemorySource.evidence_hash
            == RDBConsolidationWork.evidence_hash,
            RDBHistoricalMemorySource.availability_generation
            == RDBConsolidationWork.availability_generation,
            RDBConsolidationWork.membership_grant_id.is_not_distinct_from(grant),
        )
    )


def captured_work_version(
    receipt: type[RDBConsolidationEvidence] | type[RDBConsolidationDraftDependency],
) -> sa.ColumnElement[bool]:
    return sa.and_(
        receipt.source_session_id == RDBConsolidationWork.source_session_id,
        receipt.summary_generation == RDBConsolidationWork.summary_generation,
        receipt.evidence_hash == RDBConsolidationWork.evidence_hash,
        receipt.availability_generation == RDBConsolidationWork.availability_generation,
        receipt.membership_grant_id.is_not_distinct_from(
            RDBConsolidationWork.membership_grant_id
        ),
    )


@dataclass(frozen=True)
class ConsolidationWorkRepository:
    """Present exact IDs before delivery and journal choices under the owner fence."""

    session_manager: SessionManager[AsyncSession]

    async def retire_obsolete_pending(
        self, principal: ConsolidationJobPrincipal
    ) -> int:
        """Supersede unavailable old metadata without acknowledging model coverage."""
        async with consolidation_job_session(self.session_manager, principal) as job:
            current = pending_work_query(
                principal.unit, job.owner.attempt.membership_grant_id
            ).with_only_columns(RDBConsolidationWork.id)
            retired = (
                sa.update(RDBConsolidationWork)
                .where(
                    work_predicate(principal.unit),
                    RDBConsolidationWork.state == ConsolidationWorkState.PENDING,
                    RDBConsolidationWork.id.not_in(current),
                )
                .values(state=ConsolidationWorkState.SUPERSEDED)
                .returning(RDBConsolidationWork.id)
                .cte("retired_consolidation_metadata")
            )
            count = await job.session.scalar(
                sa.select(sa.func.count()).select_from(retired)
            )
            if not isinstance(count, int):
                raise TypeError("Consolidation retirement count is invalid.")
            await require_commit_owner(job.session, job.owner)
        return count

    async def page(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        after_sequence: int | None,
        limit: int,
    ) -> ConsolidationWorkPage:
        if not 1 <= limit <= 50 or (after_sequence is not None and after_sequence < 0):
            raise ValueError("Consolidation work page bounds are invalid.")
        async with consolidation_job_session(self.session_manager, principal) as job:
            session, owner = job.session, job.owner
            query = pending_work_query(
                principal.unit, owner.attempt.membership_grant_id
            ).where(RDBConsolidationWork.sequence <= owner.attempt.pass_upper_sequence)
            if after_sequence is not None:
                query = query.where(RDBConsolidationWork.sequence > after_sequence)
            rows = list(
                await session.scalars(
                    query.order_by(RDBConsolidationWork.sequence).limit(limit + 1)
                )
            )
            entries: list[ConsolidationWorkEntry] = []
            for row in rows[:limit]:
                source = await lock_source(
                    session, key=principal.unit, source_session_id=row.source_session_id
                )
                if (
                    source.summary_generation != row.summary_generation
                    or source.evidence_hash != row.evidence_hash
                    or source.availability_generation != row.availability_generation
                    or source.evidence_hash is None
                ):
                    raise ConsolidationDraftConflict(
                        "Consolidation work evidence changed before delivery."
                    )
                version = ConsolidationSourceVersion(
                    source_session_id=row.source_session_id,
                    summary_generation=row.summary_generation,
                    evidence_hash=source.evidence_hash,
                    availability_generation=row.availability_generation,
                    membership_grant_id=row.membership_grant_id,
                )
                await record_evidence(session, owner=owner, version=version)
                row.presented_attempt_id = principal.attempt_id
                title = source.source_title_snapshot
                entries.append(
                    ConsolidationWorkEntry(
                        row.id,
                        row.sequence,
                        row.kind,
                        version,
                        None
                        if title is None
                        else title.encode("utf-8")[:512].decode(
                            "utf-8", errors="ignore"
                        ),
                    )
                )
            result = ConsolidationWorkPage(
                tuple(entries),
                rows[limit - 1].sequence if len(rows) > limit else None,
                owner.attempt.pass_upper_sequence,
                owner.attempt.observation_epoch,
            )
            await require_commit_owner(session, owner)
        return result

    async def record_coverage(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        expected_draft_revision_id: str,
        coverage: ConsolidationCoverage,
    ) -> tuple[str, ...]:
        """Save explicit choices only; publication alone promotes them to coverage."""
        async with consolidation_job_session(self.session_manager, principal) as job:
            session, owner = job.session, job.owner
            draft = await session.scalar(
                sa.select(RDBConsolidationDraft).where(
                    RDBConsolidationDraft.unit_id == owner.unit.id
                )
            )
            if draft is None or draft.revision_id != expected_draft_revision_id:
                raise ConsolidationDraftConflict(
                    "Consolidation disposition draft is stale."
                )
            await check_draft_influence(
                session, principal=principal, owner=owner, draft=draft
            )
            ids = tuple(item.work_id for item in coverage.dispositions)
            rows = {
                row.id: row
                for row in await session.scalars(
                    sa.select(RDBConsolidationWork)
                    .where(
                        work_predicate(principal.unit), RDBConsolidationWork.id.in_(ids)
                    )
                    .with_for_update()
                )
            }
            if set(rows) != set(ids):
                raise ConsolidationAuthorityError("Consolidation work is unavailable.")
            exposed = (
                sa.select(1)
                .where(
                    RDBConsolidationEvidence.attempt_id == principal.attempt_id,
                    captured_work_version(RDBConsolidationEvidence),
                )
                .exists()
            )
            inherited = (
                sa.select(1)
                .where(
                    RDBConsolidationDraftDependency.draft_id == draft.id,
                    captured_work_version(RDBConsolidationDraftDependency),
                )
                .exists()
            )
            captured = set(
                await session.scalars(
                    sa.select(RDBConsolidationWork.id).where(
                        RDBConsolidationWork.id.in_(ids), sa.or_(exposed, inherited)
                    )
                )
            )
            if captured != set(ids):
                raise ConsolidationAuthorityError(
                    "Consolidation work evidence is unavailable."
                )
            for item in coverage.dispositions:
                row = rows[item.work_id]
                recovered = (
                    row.state is ConsolidationWorkState.CONSIDERED
                    and row.considered_draft_id == draft.id
                )
                if (
                    row.sequence > owner.attempt.pass_upper_sequence
                    or row.state
                    not in {
                        ConsolidationWorkState.PENDING,
                        ConsolidationWorkState.CONSIDERED,
                    }
                    or (
                        row.presented_attempt_id != principal.attempt_id
                        and not recovered
                    )
                ):
                    raise ConsolidationAuthorityError(
                        "Consolidation work was not presented."
                    )
                row.state = ConsolidationWorkState.CONSIDERED
                row.considered_draft_id = draft.id
                row.considered_draft_revision_id = draft.revision_id
                row.disposition = item.action
                row.consideration_reason = item.reason
            await require_commit_owner(session, owner)
        return ids
