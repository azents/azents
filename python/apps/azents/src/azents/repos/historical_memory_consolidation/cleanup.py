"""Fenced private-payload cleanup that preserves published dependency evidence."""

import datetime
from dataclasses import dataclass

import sqlalchemy as sa

from azents.core.enums import AgentSessionProductMode, AgentSessionStatus
from azents.core.historical_memory_consolidation import (
    ConsolidationAttemptState,
    ConsolidationScope,
    ConsolidationWorkState,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationDraft,
    RDBConsolidationDraftDependency,
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
    consolidation_session,
    database_now,
)


@dataclass(frozen=True)
class ConsolidationCleanupSummary:
    units: int
    drafts: int
    expired_owners: int


def _denied_draft_dependency(
    unit: type[RDBConsolidationUnit],
) -> sa.ColumnElement[bool]:
    dependency = RDBConsolidationDraftDependency
    root = RDBAgentSession
    source = RDBHistoricalMemorySource
    granted = (
        sa.select(RDBWorkspaceUser.user_id)
        .where(
            RDBWorkspaceUser.workspace_id == unit.workspace_id,
            RDBWorkspaceUser.user_id == unit.associated_user_id,
            RDBWorkspaceUser.memory_grant_identity == dependency.membership_grant_id,
        )
        .correlate(unit, dependency)
        .exists()
    )
    source_allowed = sa.and_(
        root.id.is_not(None),
        source.source_session_id.is_not(None),
        root.agent_id == unit.agent_id,
        root.workspace_id == unit.workspace_id,
        root.status == AgentSessionStatus.ACTIVE,
        source.availability_generation == dependency.availability_generation,
        sa.or_(
            sa.and_(
                unit.scope == ConsolidationScope.TEAM,
                root.product_mode == AgentSessionProductMode.TEAM,
                dependency.membership_grant_id.is_(None),
            ),
            sa.and_(
                unit.scope == ConsolidationScope.USER,
                root.product_mode == AgentSessionProductMode.USER,
                root.associated_user_id == unit.associated_user_id,
                granted,
            ),
        ),
    )
    # Treat SQL UNKNOWN as denial, including deleted roots/sources/grants.
    return (
        sa.select(dependency.id)
        .outerjoin(root, root.id == dependency.source_session_id)
        .outerjoin(source, source.source_session_id == dependency.source_session_id)
        .where(
            dependency.draft_id == RDBConsolidationDraft.id,
            source_allowed.is_not(True),
        )
        .correlate(unit, RDBConsolidationDraft)
        .exists()
    )


@dataclass(frozen=True)
class ConsolidationCleanupRepository:
    """System cleanup only deletes private data; it never grants model authority."""

    session_manager: SessionManager[WriteSession]

    async def collect_revisions(self, *, limit: int) -> int:
        """Delete only non-current bytes with no retained automatic reference."""
        if not 1 <= limit <= 100:
            raise ValueError("Consolidation collection batch bounds are invalid.")
        revision = RDBConsolidationRevision
        current = (
            sa.select(RDBConsolidationUnit.id)
            .where(RDBConsolidationUnit.published_revision_id == revision.id)
            .correlate(revision)
            .exists()
        )
        referenced = (
            sa.select(RDBToolkitState.id)
            .where(
                RDBToolkitState.toolkit_namespace == "memory",
                RDBToolkitState.state_name == "context_snapshot",
                RDBToolkitState.state_json["historical_entries"].contains(
                    sa.func.jsonb_build_array(
                        sa.func.jsonb_build_object("revision_id", revision.id)
                    )
                ),
            )
            .correlate(revision)
            .exists()
        )
        async with consolidation_session(self.session_manager) as session:
            await session.write_session.execute(
                sa.select(sa.func.set_config("statement_timeout", "2000", True))
            )
            candidates = list(
                await session.write_session.scalars(
                    sa.select(revision)
                    .where(~current, ~referenced)
                    .order_by(revision.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            # Recheck in a fresh READ COMMITTED statement after locking bytes.
            # A snapshot reference may have committed just before this lock.
            removable = set(
                await session.write_session.scalars(
                    sa.select(revision.id).where(
                        revision.id.in_([row.id for row in candidates]),
                        ~current,
                        ~referenced,
                    )
                )
            )
            for row in candidates:
                if row.id in removable:
                    await session.write_session.delete(row)
        return len(removable)

    async def sweep(self, *, limit: int) -> ConsolidationCleanupSummary:
        if not 1 <= limit <= 100:
            raise ValueError("Consolidation cleanup batch bounds are invalid.")
        async with consolidation_session(self.session_manager) as session:
            now = await database_now(session)
            expired_before = now - datetime.timedelta(hours=24)
            unit = RDBConsolidationUnit
            latest_state = (
                sa.select(RDBConsolidationAttempt.state)
                .where(RDBConsolidationAttempt.unit_id == unit.id)
                .order_by(RDBConsolidationAttempt.owner_generation.desc())
                .limit(1)
                .correlate(unit)
                .scalar_subquery()
            )
            eligible_draft = (
                sa.select(RDBConsolidationDraft.id)
                .where(
                    RDBConsolidationDraft.unit_id == unit.id,
                    sa.or_(
                        RDBConsolidationDraft.last_progress_at <= expired_before,
                        RDBConsolidationDraft.invalidated.is_(True),
                        latest_state == ConsolidationAttemptState.COMPLETED,
                        _denied_draft_dependency(unit),
                    ),
                )
                .correlate(unit)
                .exists()
            )
            terminal_attempt = (
                sa.select(RDBConsolidationAttempt.id)
                .where(
                    RDBConsolidationAttempt.unit_id == unit.id,
                    RDBConsolidationAttempt.state != ConsolidationAttemptState.RUNNING,
                )
                .correlate(unit)
            )
            private_receipt = (
                sa.select(RDBConsolidationMutationReceipt.tool_call_id)
                .where(RDBConsolidationMutationReceipt.attempt_id.in_(terminal_attempt))
                .correlate(unit)
                .exists()
            )
            private_evidence = (
                sa.select(RDBConsolidationEvidence.id)
                .where(RDBConsolidationEvidence.attempt_id.in_(terminal_attempt))
                .correlate(unit)
                .exists()
            )
            candidates = list(
                await session.write_session.scalars(
                    sa.select(unit)
                    .where(
                        sa.or_(unit.lease_until.is_(None), unit.lease_until <= now),
                        sa.or_(
                            eligible_draft,
                            private_receipt,
                            private_evidence,
                            unit.active_attempt_id.is_not(None),
                        ),
                    )
                    .order_by(unit.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            drafts_removed = 0
            owners_expired = 0
            for current in candidates:
                # Recheck time after acquiring ownership locks. A live owner is
                # protected even when its retained payload is cleanup-eligible.
                checked_at = await database_now(session)
                if current.lease_until is not None and current.lease_until > checked_at:
                    continue
                if current.active_attempt_id is not None:
                    attempt = await session.write_session.get(
                        RDBConsolidationAttempt, current.active_attempt_id
                    )
                    if (
                        attempt is not None
                        and attempt.state is ConsolidationAttemptState.RUNNING
                    ):
                        attempt.state = ConsolidationAttemptState.CANCELLED
                        attempt.failure_code = "lease_expired"
                        attempt.finished_at = checked_at
                    current.active_attempt_id = None
                    current.owner_token = None
                    current.lease_until = None
                    owners_expired += 1
                await session.write_session.flush()
                draft = await session.write_session.scalar(
                    sa.select(RDBConsolidationDraft)
                    .where(
                        RDBConsolidationDraft.unit_id == current.id,
                        sa.or_(
                            RDBConsolidationDraft.last_progress_at <= expired_before,
                            RDBConsolidationDraft.invalidated.is_(True),
                            latest_state == ConsolidationAttemptState.COMPLETED,
                            _denied_draft_dependency(unit),
                        ),
                    )
                    .join(unit, unit.id == RDBConsolidationDraft.unit_id)
                )
                if draft is not None:
                    await session.write_session.execute(
                        sa.update(RDBConsolidationWork)
                        .where(
                            RDBConsolidationWork.considered_draft_id == draft.id,
                            RDBConsolidationWork.state
                            == ConsolidationWorkState.CONSIDERED,
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
                    await session.write_session.delete(draft)
                    latest = await session.write_session.scalar(
                        sa.select(RDBConsolidationAttempt.state)
                        .where(RDBConsolidationAttempt.unit_id == current.id)
                        .order_by(RDBConsolidationAttempt.owner_generation.desc())
                        .limit(1)
                    )
                    if latest is not ConsolidationAttemptState.COMPLETED:
                        current.pass_upper_sequence = None
                    drafts_removed += 1
                old_attempts = sa.select(RDBConsolidationAttempt.id).where(
                    RDBConsolidationAttempt.unit_id == current.id,
                    RDBConsolidationAttempt.state != ConsolidationAttemptState.RUNNING,
                )
                await session.write_session.execute(
                    sa.delete(RDBConsolidationMutationReceipt).where(
                        RDBConsolidationMutationReceipt.attempt_id.in_(old_attempts)
                    )
                )
                await session.write_session.execute(
                    sa.delete(RDBConsolidationEvidence).where(
                        RDBConsolidationEvidence.attempt_id.in_(old_attempts)
                    )
                )
            result = ConsolidationCleanupSummary(
                len(candidates), drafts_removed, owners_expired
            )
        return result
