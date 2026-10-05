"""Reauthorize retained work and rebuild whole contaminated private units cleanly."""

from dataclasses import dataclass

import sqlalchemy as sa

from azents.core.historical_memory_consolidation import (
    ConsolidationJobPrincipal,
    ConsolidationWorkState,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationDraft,
    RDBConsolidationEvidence,
    RDBConsolidationMutationReceipt,
    RDBConsolidationRevision,
    RDBConsolidationRevisionDependency,
    RDBConsolidationWork,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityBusyError,
    ConsolidationAuthorityError,
    ConsolidationDeadlineError,
    consolidation_job_session,
    require_commit_owner,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
    check_dependency_manifest,
    check_draft_influence,
)
from azents.repos.historical_memory_consolidation.participant_types import (
    DraftParticipants,
)
from azents.repos.historical_memory_consolidation.retry import (
    retry_consolidation_operation,
)
from azents.repos.historical_memory_consolidation.sources import source_predicate
from azents.repos.historical_memory_consolidation.work import work_predicate


@dataclass(frozen=True)
class ConsolidationRecoveryCheckpoint:
    """A rebuild requires a new RAM-only conversation and observation ledger."""

    draft_revision_id: str
    observation_epoch: int
    rebuilt: bool
    published_available: bool


@dataclass(frozen=True)
class ConsolidationRecoveryRepository:
    """Keep permitted drafts and rebuild denied prose as a whole."""

    session_manager: SessionManager[WriteSession]

    @retry_consolidation_operation
    async def prepare(
        self, principal: ConsolidationJobPrincipal
    ) -> ConsolidationRecoveryCheckpoint:
        async with consolidation_job_session(
            self.session_manager,
            principal,
            participants=DraftParticipants(recovery=True),
        ) as job:
            session, owner = job.session, job.owner
            if owner.participants is None:
                raise RuntimeError("Consolidation recovery participants are missing.")
            published_available = owner.unit.published_revision_id is not None
            if owner.unit.published_revision_id is not None:
                revision = await session.write_session.get(
                    RDBConsolidationRevision, owner.unit.published_revision_id
                )
                if revision is None or revision.unit_id != owner.unit.id:
                    published_available = False
                else:
                    manifest = (
                        sa.select(
                            RDBConsolidationRevisionDependency.source_session_id,
                            RDBConsolidationRevisionDependency.summary_generation,
                            RDBConsolidationRevisionDependency.evidence_hash,
                            RDBConsolidationRevisionDependency.availability_generation,
                            RDBConsolidationRevisionDependency.membership_grant_id,
                        )
                        .where(
                            RDBConsolidationRevisionDependency.revision_id
                            == revision.id
                        )
                        .subquery("complete_revision_influence")
                    )
                    try:
                        await check_dependency_manifest(
                            session,
                            key=principal.unit,
                            membership_grant_id=owner.attempt.membership_grant_id,
                            influence=manifest,
                            participants=owner.participants,
                        )
                    except ConsolidationAuthorityBusyError, ConsolidationDeadlineError:
                        raise
                    except ConsolidationAuthorityError:
                        published_available = False
            draft = await session.write_session.scalar(
                sa.select(RDBConsolidationDraft).where(
                    RDBConsolidationDraft.unit_id == owner.unit.id
                )
            )
            draft_valid = draft is not None
            if draft is not None:
                try:
                    await check_draft_influence(
                        session, principal=principal, owner=owner, draft=draft
                    )
                except ConsolidationAuthorityBusyError, ConsolidationDeadlineError:
                    raise
                except ConsolidationAuthorityError:
                    draft_valid = False
            rebuilt = draft is not None and not draft_valid
            publication_lost = (
                owner.unit.published_revision_id is not None and not published_available
            )
            if publication_lost:
                owner.unit.published_revision_id = None
            if rebuilt:
                assert draft is not None
                await session.write_session.execute(
                    sa.update(RDBConsolidationWork)
                    .where(
                        work_predicate(principal.unit),
                        RDBConsolidationWork.state == ConsolidationWorkState.CONSIDERED,
                        RDBConsolidationWork.considered_draft_id == draft.id,
                    )
                    .values(
                        state=ConsolidationWorkState.PENDING,
                        considered_draft_id=None,
                        considered_draft_revision_id=None,
                        disposition=None,
                        consideration_reason=None,
                        presented_attempt_id=None,
                    )
                )
                await session.write_session.execute(
                    sa.delete(RDBConsolidationDraft).where(
                        RDBConsolidationDraft.id == draft.id
                    )
                )
                await session.write_session.execute(
                    sa.delete(RDBConsolidationEvidence).where(
                        RDBConsolidationEvidence.attempt_id == principal.attempt_id
                    )
                )
                await session.write_session.execute(
                    sa.delete(RDBConsolidationMutationReceipt).where(
                        RDBConsolidationMutationReceipt.attempt_id
                        == principal.attempt_id
                    )
                )
                owner.attempt.observation_epoch += 1
                draft = None
            if publication_lost:
                # Rebuild the permitted remainder even if its prior exact work was
                # already covered by a now-denied overview. Missing/denied work is
                # not spuriously acknowledged or supplied to the new model.
                current = (
                    sa.select(RDBConsolidationWork.id)
                    .join(
                        RDBAgentSession,
                        RDBAgentSession.id == RDBConsolidationWork.source_session_id,
                    )
                    .join(
                        RDBHistoricalMemorySource,
                        RDBHistoricalMemorySource.source_session_id
                        == RDBAgentSession.id,
                    )
                    .where(
                        work_predicate(principal.unit),
                        source_predicate(principal.unit),
                        RDBConsolidationWork.state == ConsolidationWorkState.PUBLISHED,
                        RDBConsolidationWork.summary_generation
                        == RDBHistoricalMemorySource.summary_generation,
                        RDBConsolidationWork.evidence_hash
                        == RDBHistoricalMemorySource.evidence_hash,
                        RDBConsolidationWork.availability_generation
                        == RDBHistoricalMemorySource.availability_generation,
                        RDBConsolidationWork.membership_grant_id.is_not_distinct_from(
                            owner.attempt.membership_grant_id
                        ),
                    )
                )
                await session.write_session.execute(
                    sa.update(RDBConsolidationWork)
                    .where(RDBConsolidationWork.id.in_(current))
                    .values(
                        state=ConsolidationWorkState.PENDING,
                        considered_draft_id=None,
                        considered_draft_revision_id=None,
                        disposition=None,
                        consideration_reason=None,
                        presented_attempt_id=None,
                    )
                )
                owner.unit.pass_upper_sequence = None
            if draft is None:
                draft = await ConsolidationDraftRepository(self.session_manager)._draft(
                    session, owner
                )
            await require_commit_owner(session, owner)
            result = ConsolidationRecoveryCheckpoint(
                draft.revision_id,
                owner.attempt.observation_epoch,
                rebuilt or publication_lost,
                published_available,
            )
        return result
