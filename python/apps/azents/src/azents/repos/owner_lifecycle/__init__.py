"""Owner lifecycle repository."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import OwnerLifecycleKind, OwnerLifecycleStatus
from azents.rdb.models.owner_lifecycle import RDBOwnerLifecycleJob

from .data import OwnerLifecycleJob


class OwnerLifecycleRepository:
    """Repository for durable owner-lifecycle work."""

    async def create_or_get_membership_archive(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        user_id: str,
    ) -> OwnerLifecycleJob:
        """Create or return the durable membership-archive job."""
        result = await session.execute(
            insert(RDBOwnerLifecycleJob)
            .values(
                id=uuid7().hex,
                kind=OwnerLifecycleKind.MEMBERSHIP_ARCHIVE,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            .on_conflict_do_nothing(
                index_elements=["workspace_id", "user_id"],
                index_where=sa.text("kind = 'membership_archive'"),
            )
            .returning(RDBOwnerLifecycleJob)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            rdb = await session.scalar(
                sa.select(RDBOwnerLifecycleJob).where(
                    RDBOwnerLifecycleJob.kind == OwnerLifecycleKind.MEMBERSHIP_ARCHIVE,
                    RDBOwnerLifecycleJob.workspace_id == workspace_id,
                    RDBOwnerLifecycleJob.user_id == user_id,
                )
            )
        if rdb is None:
            raise RuntimeError("Owner lifecycle membership archive job creation failed")
        if rdb.status is OwnerLifecycleStatus.COMPLETED:
            now = datetime.datetime.now(datetime.UTC)
            rdb.status = OwnerLifecycleStatus.PENDING
            rdb.attempt_count = 0
            rdb.lease_owner = None
            rdb.lease_until = None
            rdb.next_attempt_at = None
            rdb.last_error_kind = None
            rdb.last_error_summary = None
            rdb.started_at = None
            rdb.completed_at = None
            rdb.updated_at = now
            await session.flush()
        return self._build(rdb)

    async def create_or_get_account_purge(
        self,
        session: AsyncSession,
        *,
        user_id: str,
    ) -> OwnerLifecycleJob:
        """Create or return the durable account-purge job."""
        result = await session.execute(
            insert(RDBOwnerLifecycleJob)
            .values(
                id=uuid7().hex,
                kind=OwnerLifecycleKind.ACCOUNT_PURGE,
                workspace_id=None,
                user_id=user_id,
            )
            .on_conflict_do_nothing(
                index_elements=["user_id"],
                index_where=sa.text("kind = 'account_purge'"),
            )
            .returning(RDBOwnerLifecycleJob)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            rdb = await session.scalar(
                sa.select(RDBOwnerLifecycleJob).where(
                    RDBOwnerLifecycleJob.kind == OwnerLifecycleKind.ACCOUNT_PURGE,
                    RDBOwnerLifecycleJob.user_id == user_id,
                )
            )
        if rdb is None:
            raise RuntimeError("Owner lifecycle account purge job creation failed")
        await session.flush()
        return self._build(rdb)

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> OwnerLifecycleJob | None:
        """Claim one due owner-lifecycle job with an expired-or-empty lease."""
        claimable_status = sa.or_(
            RDBOwnerLifecycleJob.status.in_(
                (
                    OwnerLifecycleStatus.PENDING,
                    OwnerLifecycleStatus.RETRY_WAIT,
                )
            ),
            sa.and_(
                RDBOwnerLifecycleJob.status.in_(
                    (
                        OwnerLifecycleStatus.RETIRING_SESSIONS,
                        OwnerLifecycleStatus.WAITING_PURGE,
                        OwnerLifecycleStatus.FINALIZING,
                    )
                ),
                RDBOwnerLifecycleJob.lease_until < now,
            ),
        )
        candidate = (
            sa.select(RDBOwnerLifecycleJob.id)
            .where(
                claimable_status,
                sa.or_(
                    RDBOwnerLifecycleJob.next_attempt_at.is_(None),
                    RDBOwnerLifecycleJob.next_attempt_at <= now,
                ),
                sa.or_(
                    RDBOwnerLifecycleJob.lease_until.is_(None),
                    RDBOwnerLifecycleJob.lease_until < now,
                ),
            )
            .order_by(
                RDBOwnerLifecycleJob.created_at,
                RDBOwnerLifecycleJob.id,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
            .scalar_subquery()
        )
        result = await session.execute(
            sa.update(RDBOwnerLifecycleJob)
            .where(RDBOwnerLifecycleJob.id == candidate)
            .values(
                status=sa.case(
                    (
                        RDBOwnerLifecycleJob.status.in_(
                            (
                                OwnerLifecycleStatus.PENDING,
                                OwnerLifecycleStatus.RETRY_WAIT,
                            )
                        ),
                        OwnerLifecycleStatus.RETIRING_SESSIONS,
                    ),
                    else_=RDBOwnerLifecycleJob.status,
                ),
                started_at=sa.func.coalesce(
                    RDBOwnerLifecycleJob.started_at,
                    now,
                ),
                attempt_count=RDBOwnerLifecycleJob.attempt_count + 1,
                lease_owner=lease_owner,
                lease_until=lease_until,
                next_attempt_at=None,
                last_error_kind=None,
                last_error_summary=None,
                updated_at=now,
            )
            .returning(RDBOwnerLifecycleJob)
        )
        rdb = result.scalar_one_or_none()
        return None if rdb is None else self._build(rdb)

    async def set_status(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        status: OwnerLifecycleStatus,
        now: datetime.datetime,
    ) -> bool:
        """Advance an owned job to its current coordinator phase."""
        result = await session.execute(
            sa.update(RDBOwnerLifecycleJob)
            .where(
                RDBOwnerLifecycleJob.id == job_id,
                RDBOwnerLifecycleJob.lease_owner == lease_owner,
            )
            .values(
                status=status,
                updated_at=now,
            )
            .returning(RDBOwnerLifecycleJob.id)
        )
        return result.scalar_one_or_none() is not None

    async def mark_retry(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        next_attempt_at: datetime.datetime,
        error_kind: str,
        error_summary: str,
        now: datetime.datetime,
    ) -> bool:
        """Release an owned job into bounded retry wait."""
        result = await session.execute(
            sa.update(RDBOwnerLifecycleJob)
            .where(
                RDBOwnerLifecycleJob.id == job_id,
                RDBOwnerLifecycleJob.lease_owner == lease_owner,
            )
            .values(
                status=OwnerLifecycleStatus.RETRY_WAIT,
                lease_owner=None,
                lease_until=None,
                next_attempt_at=next_attempt_at,
                last_error_kind=error_kind[:120],
                last_error_summary=error_summary[:500],
                updated_at=now,
            )
            .returning(RDBOwnerLifecycleJob.id)
        )
        return result.scalar_one_or_none() is not None

    async def mark_completed(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        now: datetime.datetime,
    ) -> bool:
        """Mark an owned job completed and release its lease."""
        result = await session.execute(
            sa.update(RDBOwnerLifecycleJob)
            .where(
                RDBOwnerLifecycleJob.id == job_id,
                RDBOwnerLifecycleJob.lease_owner == lease_owner,
            )
            .values(
                status=OwnerLifecycleStatus.COMPLETED,
                lease_owner=None,
                lease_until=None,
                next_attempt_at=None,
                last_error_kind=None,
                last_error_summary=None,
                completed_at=now,
                updated_at=now,
            )
            .returning(RDBOwnerLifecycleJob.id)
        )
        return result.scalar_one_or_none() is not None

    def _build(self, rdb: RDBOwnerLifecycleJob) -> OwnerLifecycleJob:
        """Convert a database row to a domain model."""
        return OwnerLifecycleJob(
            id=rdb.id,
            kind=rdb.kind,
            user_id=rdb.user_id,
            workspace_id=rdb.workspace_id,
            status=rdb.status,
            attempt_count=rdb.attempt_count,
            lease_owner=rdb.lease_owner,
            lease_until=rdb.lease_until,
            next_attempt_at=rdb.next_attempt_at,
            last_error_kind=rdb.last_error_kind,
            last_error_summary=rdb.last_error_summary,
            started_at=rdb.started_at,
            completed_at=rdb.completed_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
