"""Freeze artifacts and atomically publish validated bytes and exact progress."""

import datetime
import logging
from dataclasses import dataclass

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from azents.core.historical_memory_budget import ConsolidationBudgetExceeded
from azents.core.historical_memory_consolidation import (
    ConsolidationAttemptState,
    ConsolidationJobPrincipal,
    ConsolidationWorkState,
)
from azents.core.historical_memory_publication import (
    ConsolidationCoverage,
    ConsolidationOutputError,
    ValidatedConsolidationOverview,
    validate_consolidation_overview,
)
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationDraft,
    RDBConsolidationDraftDependency,
    RDBConsolidationDraftFile,
    RDBConsolidationEvidence,
    RDBConsolidationRevision,
    RDBConsolidationRevisionDependency,
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.session import SessionManager
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
    consolidation_job_session,
    consolidation_session,
    database_now,
    lock_unit_authority,
    require_commit_owner,
    unit_predicate,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftConflict,
    check_draft_influence,
)
from azents.repos.historical_memory_consolidation.operations import (
    finish_consolidation_model_operation,
)
from azents.repos.historical_memory_consolidation.work import (
    pending_work_query,
    work_predicate,
)
from azents.repos.model_candidate_health import ModelCandidateHealthRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FrozenConsolidationDraft:
    """Authoritative artifact identity after the host has quiesced its execution."""

    revision_id: str
    observation_epoch: int
    markdown: str
    coverage: ConsolidationCoverage


@dataclass(frozen=True)
class ConsolidationPublicationOutcome:
    """Durable original completion identity, not a claim of current read authority."""

    revision_id: str


def decode_coverage(content: str | None) -> ConsolidationCoverage:
    if content is None:
        return ConsolidationCoverage(dispositions=())
    try:
        return ConsolidationCoverage.model_validate_json(content)
    except ValidationError:
        raise ConsolidationOutputError(
            "Consolidation coverage artifact is invalid."
        ) from None


async def copy_published_dependencies(
    session: AsyncSession,
    *,
    revision_id: str,
    draft_id: str,
    attempt_id: str,
) -> None:
    """Keep the full influencing union independently of source/work/attempt cleanup."""
    inherited = sa.select(
        RDBConsolidationDraftDependency.source_session_id,
        RDBConsolidationDraftDependency.summary_generation,
        RDBConsolidationDraftDependency.evidence_hash,
        RDBConsolidationDraftDependency.availability_generation,
        RDBConsolidationDraftDependency.membership_grant_id,
    ).where(RDBConsolidationDraftDependency.draft_id == draft_id)
    exposed = sa.select(
        RDBConsolidationEvidence.source_session_id,
        RDBConsolidationEvidence.summary_generation,
        RDBConsolidationEvidence.evidence_hash,
        RDBConsolidationEvidence.availability_generation,
        RDBConsolidationEvidence.membership_grant_id,
    ).where(RDBConsolidationEvidence.attempt_id == attempt_id)
    influence = inherited.union(exposed).subquery()
    await session.execute(
        insert(RDBConsolidationRevisionDependency).from_select(
            [
                "id",
                "revision_id",
                "source_session_id",
                "summary_generation",
                "evidence_hash",
                "availability_generation",
                "membership_grant_id",
            ],
            sa.select(
                sa.func.replace(sa.cast(sa.func.gen_random_uuid(), sa.Text), "-", ""),
                sa.literal(revision_id),
                influence.c.source_session_id,
                influence.c.summary_generation,
                influence.c.evidence_hash,
                influence.c.availability_generation,
                influence.c.membership_grant_id,
            ),
        )
    )


@dataclass(frozen=True)
class ConsolidationPublicationRepository:
    """The sole publication authority; no model tool submits a publication payload."""

    session_manager: SessionManager[AsyncSession]

    async def freeze(
        self, principal: ConsolidationJobPrincipal
    ) -> FrozenConsolidationDraft:
        async with consolidation_job_session(self.session_manager, principal) as job:
            session, owner = job.session, job.owner
            draft = await session.scalar(
                sa.select(RDBConsolidationDraft).where(
                    RDBConsolidationDraft.unit_id == owner.unit.id
                )
            )
            if draft is None:
                raise ConsolidationOutputError(
                    "Consolidation overview artifact is missing."
                )
            await check_draft_influence(
                session, principal=principal, owner=owner, draft=draft
            )
            files = {
                file.path: file.content
                for file in await session.scalars(
                    sa.select(RDBConsolidationDraftFile).where(
                        RDBConsolidationDraftFile.draft_id == draft.id
                    )
                )
            }
            if "summary.md" not in files:
                raise ConsolidationOutputError(
                    "Consolidation overview artifact is missing."
                )
            result = FrozenConsolidationDraft(
                draft.revision_id,
                owner.attempt.observation_epoch,
                files["summary.md"],
                decode_coverage(files.get("coverage.json")),
            )
            await require_commit_owner(session, owner)
        return result

    async def inspect_outcome(
        self, principal: ConsolidationJobPrincipal
    ) -> ConsolidationPublicationOutcome | None:
        """Resolve an uncertain result from durable completion, without republishing."""
        async with consolidation_session(self.session_manager) as session:
            grant = await lock_unit_authority(session, principal.unit)
            unit = await session.scalar(
                sa.select(RDBConsolidationUnit).where(unit_predicate(principal.unit))
            )
            attempt = await session.get(RDBConsolidationAttempt, principal.attempt_id)
            if (
                unit is None
                or attempt is None
                or attempt.unit_id != unit.id
                or attempt.owner_generation != principal.owner_generation
                or attempt.owner_token != principal.owner_token
                or attempt.membership_grant_id != grant
            ):
                raise ConsolidationAuthorityError(
                    "Consolidation outcome is unavailable."
                )
            if attempt.state is not ConsolidationAttemptState.COMPLETED:
                return None
            if attempt.completed_revision_id is None:
                raise ConsolidationAuthorityError(
                    "Consolidation completion is unavailable."
                )
            revision = await session.get(
                RDBConsolidationRevision, attempt.completed_revision_id
            )
            if (
                revision is None
                or revision.unit_id != unit.id
                or revision.attempt_id != attempt.id
            ):
                raise ConsolidationAuthorityError(
                    "Consolidation completion is unavailable."
                )
            result = ConsolidationPublicationOutcome(revision.id)
        return result

    async def publish(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        expected_draft_revision_id: str,
        expected_observation_epoch: int,
        overview: ValidatedConsolidationOverview,
    ) -> ConsolidationPublicationOutcome:
        async with consolidation_job_session(self.session_manager, principal) as job:
            session, owner = job.session, job.owner
            if owner.attempt.failure_code == "token_budget_exceeded":
                raise ConsolidationBudgetExceeded(
                    "Consolidation hard budget cannot produce publication."
                )
            draft = await session.scalar(
                sa.select(RDBConsolidationDraft).where(
                    RDBConsolidationDraft.unit_id == owner.unit.id
                )
            )
            if (
                draft is None
                or draft.revision_id != expected_draft_revision_id
                or owner.attempt.observation_epoch != expected_observation_epoch
            ):
                raise ConsolidationDraftConflict(
                    "Consolidation publication freeze is stale."
                )
            await check_draft_influence(
                session, principal=principal, owner=owner, draft=draft
            )
            files = {
                file.path: file.content
                for file in await session.scalars(
                    sa.select(RDBConsolidationDraftFile).where(
                        RDBConsolidationDraftFile.draft_id == draft.id
                    )
                )
            }
            if "summary.md" not in files:
                raise ConsolidationOutputError(
                    "Consolidation overview artifact is missing."
                )
            actual = validate_consolidation_overview(
                key=principal.unit, markdown=files["summary.md"]
            )
            if actual != overview:
                raise ConsolidationDraftConflict(
                    "Consolidation authored bytes do not match the freeze."
                )
            coverage = decode_coverage(files.get("coverage.json"))
            rows = {
                row.id: row
                for row in await session.scalars(
                    sa.select(RDBConsolidationWork)
                    .where(
                        work_predicate(principal.unit),
                        RDBConsolidationWork.id.in_(
                            tuple(item.work_id for item in coverage.dispositions)
                        ),
                        RDBConsolidationWork.state == ConsolidationWorkState.CONSIDERED,
                        RDBConsolidationWork.considered_draft_id == draft.id,
                        RDBConsolidationWork.considered_draft_revision_id
                        == draft.revision_id,
                    )
                    .with_for_update()
                )
            }
            if set(rows) != {item.work_id for item in coverage.dispositions}:
                raise ConsolidationDraftConflict(
                    "Consolidation coverage must bind the frozen draft."
                )
            for item in coverage.dispositions:
                if (
                    rows[item.work_id].disposition != item.action
                    or rows[item.work_id].consideration_reason != item.reason
                ):
                    raise ConsolidationDraftConflict(
                        "Consolidation disposition does not match its artifact."
                    )
            route_ids = {route.source_session_id for route in actual.routes}
            inherited_ids = sa.select(
                RDBConsolidationDraftDependency.source_session_id
            ).where(RDBConsolidationDraftDependency.draft_id == draft.id)
            exposed_ids = sa.select(RDBConsolidationEvidence.source_session_id).where(
                RDBConsolidationEvidence.attempt_id == principal.attempt_id
            )
            route_influence = inherited_ids.union(exposed_ids).subquery()
            available_route_ids = set(
                await session.scalars(
                    sa.select(route_influence.c.source_session_id).where(
                        route_influence.c.source_session_id.in_(route_ids)
                    )
                )
            )
            if not route_ids <= available_route_ids:
                raise ConsolidationOutputError(
                    "Consolidation source route lacks captured evidence."
                )
            revision_id = uuid7().hex
            revision = RDBConsolidationRevision(
                id=revision_id,
                unit_id=owner.unit.id,
                attempt_id=principal.attempt_id,
                markdown=actual.markdown,
                rendered_block=actual.rendered_block,
            )
            session.add(revision)
            await session.flush()
            await copy_published_dependencies(
                session,
                revision_id=revision_id,
                draft_id=draft.id,
                attempt_id=principal.attempt_id,
            )
            for row in rows.values():
                row.state = ConsolidationWorkState.PUBLISHED
                row.published_revision_id = revision_id
            await session.flush()
            remaining = await session.scalar(
                sa.select(
                    pending_work_query(
                        principal.unit, owner.attempt.membership_grant_id
                    )
                    .where(
                        RDBConsolidationWork.sequence
                        <= owner.attempt.pass_upper_sequence
                    )
                    .exists()
                )
            )
            if not remaining:
                owner.unit.pass_upper_sequence = None
            now = await database_now(session)
            await require_commit_owner(session, owner)
            await finish_consolidation_model_operation(
                session,
                owner=owner,
                health_repository=ModelCandidateHealthRepository(self.session_manager),
            )
            await require_commit_owner(session, owner)
            owner.attempt.state = ConsolidationAttemptState.COMPLETED
            owner.attempt.finished_at = now
            owner.attempt.completed_revision_id = revision_id
            owner.unit.published_revision_id = revision_id
            owner.unit.owner_token = None
            owner.unit.lease_until = None
            owner.unit.active_attempt_id = None
            owner.unit.failure_count = 0
            owner.unit.no_progress_count = (
                0 if rows else owner.unit.no_progress_count + 1
            )
            owner.unit.retry_at = None
            if owner.unit.no_progress_count >= 3:
                delay = min(60 * 2 ** min(owner.unit.no_progress_count - 3, 9), 21600)
                owner.unit.retry_at = now + datetime.timedelta(seconds=delay)
            await session.flush()
            outcome = ConsolidationPublicationOutcome(revision_id)
            no_progress_count = owner.unit.no_progress_count
            unit_id = owner.unit.id
        if no_progress_count >= 3:
            logger.warning(
                "Historical consolidation completed without useful work progress",
                extra={
                    "agent_id": principal.unit.agent_id,
                    "workspace_id": principal.unit.workspace_id,
                    "consolidation_unit_id": unit_id,
                    "consolidation_attempt_id": principal.attempt_id,
                    "no_progress_count": no_progress_count,
                },
            )
        return outcome
