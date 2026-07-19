"""Archived-session retention repositories."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionStatus,
    ArchivedSessionPurgeStatus,
    ArchivedSessionRetentionApplicationStatus,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.archived_session_retention import (
    RDBArchivedSessionPurgeJob,
    RDBArchivedSessionRetentionApplication,
    RDBSystemFileLifecycleSetting,
)

from .data import (
    ArchivedSessionPurgeJob,
    ArchivedSessionRetentionApplication,
    RetentionBatchResult,
    RetentionImpactPreview,
    SystemFileLifecycleSettings,
)

_ACTIVE_APPLICATION_STATUSES = (
    ArchivedSessionRetentionApplicationStatus.PENDING,
    ArchivedSessionRetentionApplicationStatus.RUNNING,
    ArchivedSessionRetentionApplicationStatus.RETRY_WAIT,
)


class ArchivedSessionRetentionRepository:
    """Persistence operations for archive retention settings and work."""

    async def get_settings(self, session: AsyncSession) -> SystemFileLifecycleSettings:
        """Fetch the singleton settings row."""
        row = await session.get(RDBSystemFileLifecycleSetting, 1)
        if row is None:
            raise RuntimeError("System file lifecycle settings are not initialized")
        return self._build_settings(row)

    async def lock_settings(self, session: AsyncSession) -> SystemFileLifecycleSettings:
        """Lock and fetch the singleton settings row."""
        row = await session.scalar(
            sa.select(RDBSystemFileLifecycleSetting)
            .where(RDBSystemFileLifecycleSetting.id == 1)
            .with_for_update()
        )
        if row is None:
            raise RuntimeError("System file lifecycle settings are not initialized")
        return self._build_settings(row)

    async def update_settings(
        self,
        session: AsyncSession,
        *,
        expected_revision: int,
        retention_days: int | None,
        updated_by_user_id: str,
    ) -> SystemFileLifecycleSettings | None:
        """Update settings when the optimistic revision matches."""
        result = await session.execute(
            sa.update(RDBSystemFileLifecycleSetting)
            .where(
                RDBSystemFileLifecycleSetting.id == 1,
                RDBSystemFileLifecycleSetting.revision == expected_revision,
            )
            .values(
                archived_session_retention_days=retention_days,
                revision=RDBSystemFileLifecycleSetting.revision + 1,
                updated_by_user_id=updated_by_user_id,
                updated_at=sa.func.now(),
            )
            .returning(RDBSystemFileLifecycleSetting)
        )
        row = result.scalar_one_or_none()
        return None if row is None else self._build_settings(row)

    async def schedule_purge_job(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
        eligible_at: datetime.datetime,
        policy_revision: int,
        now: datetime.datetime,
    ) -> None:
        """Create or reactivate unstarted purge work for an archived root."""
        values = {
            "eligible_at": eligible_at,
            "policy_revision": policy_revision,
            "status": ArchivedSessionPurgeStatus.PENDING,
            "fencing_started_at": None,
            "attempt_count": 0,
            "lease_owner": None,
            "lease_until": None,
            "next_attempt_at": None,
            "last_error_kind": None,
            "last_error_summary": None,
            "started_at": None,
            "last_attempt_at": None,
            "cancelled_at": None,
            "completed_at": None,
            "updated_at": now,
        }
        await session.execute(
            insert(RDBArchivedSessionPurgeJob)
            .values(
                id=uuid7().hex,
                root_session_id=root_session_id,
                **values,
            )
            .on_conflict_do_update(
                constraint="uq_archived_session_purge_jobs_root_session_id",
                set_=values,
                where=RDBArchivedSessionPurgeJob.fencing_started_at.is_(None),
            )
        )

    async def cancel_unstarted_purge_job(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
        now: datetime.datetime,
    ) -> bool:
        """Cancel purge work only before its irreversible fence."""
        result = await session.execute(
            sa.update(RDBArchivedSessionPurgeJob)
            .where(
                RDBArchivedSessionPurgeJob.root_session_id == root_session_id,
                RDBArchivedSessionPurgeJob.fencing_started_at.is_(None),
            )
            .values(
                status=ArchivedSessionPurgeStatus.CANCELLED,
                cancelled_at=now,
                lease_owner=None,
                lease_until=None,
                next_attempt_at=None,
                updated_at=now,
            )
            .returning(RDBArchivedSessionPurgeJob.id)
        )
        return result.scalar_one_or_none() is not None

    async def cancel_invalid_unstarted_purge_jobs(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        limit: int,
    ) -> int:
        """Cancel bounded unstarted jobs whose root schedule no longer matches."""
        valid_root_schedule = sa.exists(
            sa.select(RDBAgentSession.id).where(
                RDBAgentSession.id == RDBArchivedSessionPurgeJob.root_session_id,
                RDBAgentSession.status == AgentSessionStatus.ARCHIVED,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.purge_after.is_not(None),
                RDBAgentSession.purge_after == RDBArchivedSessionPurgeJob.eligible_at,
                RDBAgentSession.archive_policy_revision
                == RDBArchivedSessionPurgeJob.policy_revision,
            )
        )
        candidates = (
            sa.select(RDBArchivedSessionPurgeJob.id)
            .where(
                RDBArchivedSessionPurgeJob.status.in_(
                    (
                        ArchivedSessionPurgeStatus.PENDING,
                        ArchivedSessionPurgeStatus.RETRY_WAIT,
                    )
                ),
                RDBArchivedSessionPurgeJob.fencing_started_at.is_(None),
                ~valid_root_schedule,
            )
            .order_by(RDBArchivedSessionPurgeJob.updated_at)
            .limit(limit)
        )
        result = await session.execute(
            sa.update(RDBArchivedSessionPurgeJob)
            .where(RDBArchivedSessionPurgeJob.id.in_(candidates))
            .values(
                status=ArchivedSessionPurgeStatus.CANCELLED,
                cancelled_at=now,
                lease_owner=None,
                lease_until=None,
                next_attempt_at=None,
                last_error_kind="InvalidRootSchedule",
                last_error_summary=(
                    "Archived root schedule no longer matches this purge job."
                ),
                updated_at=now,
            )
            .returning(RDBArchivedSessionPurgeJob.id)
        )
        return len(result.scalars().all())

    async def purge_fencing_started(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
    ) -> bool:
        """Return whether irreversible purge fencing has started."""
        started = await session.scalar(
            sa.select(RDBArchivedSessionPurgeJob.fencing_started_at)
            .where(RDBArchivedSessionPurgeJob.root_session_id == root_session_id)
            .with_for_update()
        )
        return started is not None

    async def preview(
        self,
        session: AsyncSession,
        *,
        retention_days: int | None,
        now: datetime.datetime,
    ) -> RetentionImpactPreview:
        """Count existing archive effects without changing state."""
        started_job = sa.exists(
            sa.select(RDBArchivedSessionPurgeJob.id).where(
                RDBArchivedSessionPurgeJob.root_session_id == RDBAgentSession.id,
                RDBArchivedSessionPurgeJob.fencing_started_at.is_not(None),
            )
        )
        base = sa.and_(
            RDBAgentSession.status == AgentSessionStatus.ARCHIVED,
            RDBAgentSession.session_kind == AgentSessionKind.ROOT,
            RDBAgentSession.archived_at.is_not(None),
        )
        candidate = sa.and_(base, ~started_job)
        affected = (
            await session.scalar(
                sa.select(sa.func.count()).select_from(RDBAgentSession).where(candidate)
            )
            or 0
        )
        excluded = (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBAgentSession)
                .where(base, started_job)
            )
            or 0
        )
        immediately = 0
        scheduled = 0
        cancelled = 0
        if retention_days is None:
            cancelled = (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBAgentSession)
                    .where(candidate, RDBAgentSession.purge_after.is_not(None))
                )
                or 0
            )
        else:
            archived_at = sa.cast(
                RDBAgentSession.archived_at,
                sa.DateTime(timezone=True),
            )
            cutoff = now - datetime.timedelta(days=retention_days)
            immediately = (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBAgentSession)
                    .where(candidate, archived_at <= cutoff)
                )
                or 0
            )
            scheduled = affected
        return RetentionImpactPreview(
            affected_count=affected,
            immediately_eligible_count=immediately,
            cancelled_count=cancelled,
            scheduled_count=scheduled,
            excluded_count=excluded,
        )

    async def get_active_application(
        self, session: AsyncSession
    ) -> ArchivedSessionRetentionApplication | None:
        """Fetch the oldest unfinished recalculation application."""
        row = await session.scalar(
            sa.select(RDBArchivedSessionRetentionApplication)
            .where(
                RDBArchivedSessionRetentionApplication.status.in_(
                    _ACTIVE_APPLICATION_STATUSES
                )
            )
            .order_by(RDBArchivedSessionRetentionApplication.created_at)
            .limit(1)
        )
        return None if row is None else self._build_application(row)

    async def create_application(
        self,
        session: AsyncSession,
        *,
        target_revision: int,
        target_retention_days: int | None,
        requested_by_user_id: str,
    ) -> ArchivedSessionRetentionApplication:
        """Create durable recalculation work."""
        row = RDBArchivedSessionRetentionApplication(
            target_revision=target_revision,
            target_retention_days=target_retention_days,
            requested_by_user_id=requested_by_user_id,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return self._build_application(row)

    async def claim_application(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> ArchivedSessionRetentionApplication | None:
        """Claim one due or expired-lease recalculation application."""
        claimable_status = sa.or_(
            RDBArchivedSessionRetentionApplication.status.in_(
                (
                    ArchivedSessionRetentionApplicationStatus.PENDING,
                    ArchivedSessionRetentionApplicationStatus.RETRY_WAIT,
                )
            ),
            sa.and_(
                RDBArchivedSessionRetentionApplication.status
                == ArchivedSessionRetentionApplicationStatus.RUNNING,
                RDBArchivedSessionRetentionApplication.lease_until < now,
            ),
        )
        candidate = (
            sa.select(RDBArchivedSessionRetentionApplication.id)
            .where(
                claimable_status,
                sa.or_(
                    RDBArchivedSessionRetentionApplication.next_attempt_at.is_(None),
                    RDBArchivedSessionRetentionApplication.next_attempt_at <= now,
                ),
                sa.or_(
                    RDBArchivedSessionRetentionApplication.lease_until.is_(None),
                    RDBArchivedSessionRetentionApplication.lease_until < now,
                ),
            )
            .order_by(RDBArchivedSessionRetentionApplication.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
            .scalar_subquery()
        )
        result = await session.execute(
            sa.update(RDBArchivedSessionRetentionApplication)
            .where(RDBArchivedSessionRetentionApplication.id == candidate)
            .values(
                status=ArchivedSessionRetentionApplicationStatus.RUNNING,
                started_at=sa.func.coalesce(
                    RDBArchivedSessionRetentionApplication.started_at, now
                ),
                attempt_count=(
                    RDBArchivedSessionRetentionApplication.attempt_count + 1
                ),
                lease_owner=lease_owner,
                lease_until=lease_until,
                next_attempt_at=None,
                last_error_kind=None,
                last_error_summary=None,
                updated_at=now,
            )
            .returning(RDBArchivedSessionRetentionApplication)
        )
        row = result.scalar_one_or_none()
        return None if row is None else self._build_application(row)

    async def apply_next_batch(
        self,
        session: AsyncSession,
        *,
        application: ArchivedSessionRetentionApplication,
        now: datetime.datetime,
        limit: int,
    ) -> RetentionBatchResult:
        """Apply one bounded root batch and return progress counters."""
        query = sa.select(RDBAgentSession).where(
            RDBAgentSession.status == AgentSessionStatus.ARCHIVED,
            RDBAgentSession.session_kind == AgentSessionKind.ROOT,
            RDBAgentSession.archived_at.is_not(None),
            sa.or_(
                RDBAgentSession.archive_policy_revision.is_(None),
                RDBAgentSession.archive_policy_revision < application.target_revision,
            ),
        )
        if application.cursor_session_id is not None:
            query = query.where(RDBAgentSession.id > application.cursor_session_id)
        rows = list(
            (
                await session.execute(
                    query.order_by(RDBAgentSession.id).with_for_update().limit(limit)
                )
            ).scalars()
        )
        affected = 0
        immediately = 0
        cancelled = 0
        scheduled = 0
        skipped = 0
        cursor = None
        for row in rows:
            cursor = row.id
            job = await session.scalar(
                sa.select(RDBArchivedSessionPurgeJob)
                .where(RDBArchivedSessionPurgeJob.root_session_id == row.id)
                .with_for_update()
            )
            if job is not None and job.fencing_started_at is not None:
                skipped += 1
                continue
            archived_at = row.archived_at
            if archived_at is None:
                skipped += 1
                continue
            deadline = (
                None
                if application.target_retention_days is None
                else archived_at
                + datetime.timedelta(days=application.target_retention_days)
            )
            row.purge_after = deadline
            row.archive_policy_revision = application.target_revision
            row.archive_retention_days_snapshot = application.target_retention_days
            affected += 1
            if deadline is None:
                if job is not None:
                    job.status = ArchivedSessionPurgeStatus.CANCELLED
                    job.cancelled_at = now
                    job.lease_owner = None
                    job.lease_until = None
                    job.next_attempt_at = None
                    job.updated_at = now
                    cancelled += 1
                continue
            if deadline <= now:
                immediately += 1
            scheduled += 1
            insert_values = {
                "id": uuid7().hex,
                "root_session_id": row.id,
                "eligible_at": deadline,
                "policy_revision": application.target_revision,
                "status": ArchivedSessionPurgeStatus.PENDING,
                "fencing_started_at": None,
                "attempt_count": 0,
                "lease_owner": None,
                "lease_until": None,
                "next_attempt_at": None,
                "last_error_kind": None,
                "last_error_summary": None,
                "started_at": None,
                "last_attempt_at": None,
                "cancelled_at": None,
                "completed_at": None,
                "updated_at": now,
            }
            update_values = {
                key: value
                for key, value in insert_values.items()
                if key not in {"id", "root_session_id"}
            }
            await session.execute(
                insert(RDBArchivedSessionPurgeJob)
                .values(**insert_values)
                .on_conflict_do_update(
                    constraint="uq_archived_session_purge_jobs_root_session_id",
                    set_=update_values,
                    where=RDBArchivedSessionPurgeJob.fencing_started_at.is_(None),
                )
            )
        return RetentionBatchResult(
            scanned_count=len(rows),
            affected_count=affected,
            immediately_eligible_count=immediately,
            cancelled_count=cancelled,
            scheduled_count=scheduled,
            skipped_count=skipped,
            cursor_session_id=cursor,
        )

    async def advance_application(
        self,
        session: AsyncSession,
        *,
        application_id: str,
        lease_owner: str,
        batch: RetentionBatchResult,
        completed: bool,
        now: datetime.datetime,
    ) -> bool:
        """Persist one recalculation batch result and release its lease."""
        values: dict[str, object] = {
            "cursor_session_id": batch.cursor_session_id,
            "affected_count": (
                RDBArchivedSessionRetentionApplication.affected_count
                + batch.affected_count
            ),
            "immediately_eligible_count": (
                RDBArchivedSessionRetentionApplication.immediately_eligible_count
                + batch.immediately_eligible_count
            ),
            "cancelled_count": (
                RDBArchivedSessionRetentionApplication.cancelled_count
                + batch.cancelled_count
            ),
            "scheduled_count": (
                RDBArchivedSessionRetentionApplication.scheduled_count
                + batch.scheduled_count
            ),
            "skipped_count": (
                RDBArchivedSessionRetentionApplication.skipped_count
                + batch.skipped_count
            ),
            "lease_owner": None,
            "lease_until": None,
            "next_attempt_at": None,
            "last_error_kind": None,
            "last_error_summary": None,
            "updated_at": now,
        }
        if completed:
            values.update(
                status=ArchivedSessionRetentionApplicationStatus.COMPLETED,
                completed_at=now,
            )
        else:
            values.update(status=ArchivedSessionRetentionApplicationStatus.PENDING)
        result = await session.execute(
            sa.update(RDBArchivedSessionRetentionApplication)
            .where(
                RDBArchivedSessionRetentionApplication.id == application_id,
                RDBArchivedSessionRetentionApplication.status
                == ArchivedSessionRetentionApplicationStatus.RUNNING,
                RDBArchivedSessionRetentionApplication.lease_owner == lease_owner,
            )
            .values(**values)
            .returning(RDBArchivedSessionRetentionApplication.id)
        )
        return result.scalar_one_or_none() is not None

    async def mark_application_retry(
        self,
        session: AsyncSession,
        *,
        application_id: str,
        next_attempt_at: datetime.datetime,
        error_kind: str,
        error_summary: str,
        now: datetime.datetime,
    ) -> None:
        """Release a failed application lease into bounded retry wait."""
        await session.execute(
            sa.update(RDBArchivedSessionRetentionApplication)
            .where(
                RDBArchivedSessionRetentionApplication.id == application_id,
                RDBArchivedSessionRetentionApplication.status
                == ArchivedSessionRetentionApplicationStatus.RUNNING,
            )
            .values(
                status=ArchivedSessionRetentionApplicationStatus.RETRY_WAIT,
                lease_owner=None,
                lease_until=None,
                next_attempt_at=next_attempt_at,
                last_error_kind=error_kind[:120],
                last_error_summary=error_summary[:500],
                updated_at=now,
            )
        )

    async def claim_due_purge_job(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> ArchivedSessionPurgeJob | None:
        """Claim one due purge job and cross the irreversible fence."""
        claimable = sa.or_(
            RDBArchivedSessionPurgeJob.status.in_(
                (
                    ArchivedSessionPurgeStatus.PENDING,
                    ArchivedSessionPurgeStatus.RETRY_WAIT,
                )
            ),
            sa.and_(
                RDBArchivedSessionPurgeJob.status.in_(
                    (
                        ArchivedSessionPurgeStatus.FENCING,
                        ArchivedSessionPurgeStatus.CLEANING,
                    )
                ),
                RDBArchivedSessionPurgeJob.lease_until < now,
            ),
        )
        valid_root = sa.exists(
            sa.select(RDBAgentSession.id).where(
                RDBAgentSession.id == RDBArchivedSessionPurgeJob.root_session_id,
                RDBAgentSession.status == AgentSessionStatus.ARCHIVED,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.purge_after.is_not(None),
                RDBAgentSession.purge_after == RDBArchivedSessionPurgeJob.eligible_at,
                RDBAgentSession.purge_after <= now,
                RDBAgentSession.archive_policy_revision
                == RDBArchivedSessionPurgeJob.policy_revision,
            )
        )
        candidate = (
            sa.select(RDBArchivedSessionPurgeJob.id)
            .where(
                claimable,
                valid_root,
                RDBArchivedSessionPurgeJob.eligible_at <= now,
                sa.or_(
                    RDBArchivedSessionPurgeJob.next_attempt_at.is_(None),
                    RDBArchivedSessionPurgeJob.next_attempt_at <= now,
                ),
                sa.or_(
                    RDBArchivedSessionPurgeJob.lease_until.is_(None),
                    RDBArchivedSessionPurgeJob.lease_until < now,
                ),
            )
            .order_by(
                RDBArchivedSessionPurgeJob.eligible_at,
                RDBArchivedSessionPurgeJob.id,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
            .scalar_subquery()
        )
        result = await session.execute(
            sa.update(RDBArchivedSessionPurgeJob)
            .where(RDBArchivedSessionPurgeJob.id == candidate)
            .values(
                status=ArchivedSessionPurgeStatus.FENCING,
                fencing_started_at=sa.func.coalesce(
                    RDBArchivedSessionPurgeJob.fencing_started_at,
                    now,
                ),
                started_at=sa.func.coalesce(
                    RDBArchivedSessionPurgeJob.started_at,
                    now,
                ),
                last_attempt_at=now,
                attempt_count=RDBArchivedSessionPurgeJob.attempt_count + 1,
                lease_owner=lease_owner,
                lease_until=lease_until,
                next_attempt_at=None,
                last_error_kind=None,
                last_error_summary=None,
                updated_at=now,
            )
            .returning(RDBArchivedSessionPurgeJob)
        )
        row = result.scalar_one_or_none()
        return None if row is None else self._build_job(row)

    async def mark_purge_cleaning(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        model_file_count: int,
        artifact_count: int,
        exchange_file_count: int,
        worktree_count: int,
        now: datetime.datetime,
    ) -> bool:
        """Persist cleanup scope and enter the cleaning phase."""
        result = await session.execute(
            sa.update(RDBArchivedSessionPurgeJob)
            .where(
                RDBArchivedSessionPurgeJob.id == job_id,
                RDBArchivedSessionPurgeJob.lease_owner == lease_owner,
            )
            .values(
                status=ArchivedSessionPurgeStatus.CLEANING,
                model_file_count=model_file_count,
                artifact_count=artifact_count,
                exchange_file_count=exchange_file_count,
                worktree_count=worktree_count,
                updated_at=now,
            )
            .returning(RDBArchivedSessionPurgeJob.id)
        )
        return result.scalar_one_or_none() is not None

    async def mark_purge_retry(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        next_attempt_at: datetime.datetime,
        error_kind: str,
        error_summary: str,
        now: datetime.datetime,
    ) -> None:
        """Release a purge lease into bounded retry wait."""
        await session.execute(
            sa.update(RDBArchivedSessionPurgeJob)
            .where(
                RDBArchivedSessionPurgeJob.id == job_id,
                RDBArchivedSessionPurgeJob.lease_owner == lease_owner,
            )
            .values(
                status=ArchivedSessionPurgeStatus.RETRY_WAIT,
                lease_owner=None,
                lease_until=None,
                next_attempt_at=next_attempt_at,
                last_error_kind=error_kind[:120],
                last_error_summary=error_summary[:500],
                updated_at=now,
            )
        )

    async def complete_purge_job(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        now: datetime.datetime,
    ) -> bool:
        """Complete a content-free purge tombstone and release its lease."""
        result = await session.execute(
            sa.update(RDBArchivedSessionPurgeJob)
            .where(
                RDBArchivedSessionPurgeJob.id == job_id,
                RDBArchivedSessionPurgeJob.lease_owner == lease_owner,
            )
            .values(
                status=ArchivedSessionPurgeStatus.COMPLETED,
                lease_owner=None,
                lease_until=None,
                next_attempt_at=None,
                last_error_kind=None,
                last_error_summary=None,
                completed_at=now,
                updated_at=now,
            )
            .returning(RDBArchivedSessionPurgeJob.id)
        )
        return result.scalar_one_or_none() is not None

    def _build_settings(
        self, row: RDBSystemFileLifecycleSetting
    ) -> SystemFileLifecycleSettings:
        return SystemFileLifecycleSettings(
            archived_session_retention_days=row.archived_session_retention_days,
            revision=row.revision,
            updated_by_user_id=row.updated_by_user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _build_application(
        self, row: RDBArchivedSessionRetentionApplication
    ) -> ArchivedSessionRetentionApplication:
        return ArchivedSessionRetentionApplication.model_validate(
            row,
            from_attributes=True,
        )

    def _build_job(self, row: RDBArchivedSessionPurgeJob) -> ArchivedSessionPurgeJob:
        return ArchivedSessionPurgeJob.model_validate(row, from_attributes=True)
