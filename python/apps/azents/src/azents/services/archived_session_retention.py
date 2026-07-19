"""Archived-session retention settings and recalculation service."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.archived_session_retention.data import (
    ArchivedSessionRetentionApplication,
    RetentionApplicationScope,
    RetentionImpactPreview,
    SystemFileLifecycleSettings,
)

_RECALCULATION_BATCH_LIMIT = 100
_RECALCULATION_LEASE = datetime.timedelta(minutes=2)
_RECALCULATION_MAX_RETRY_DELAY = datetime.timedelta(minutes=30)
_RECALCULATION_ERROR_SUMMARY = "Existing archive retention recalculation batch failed."


class RetentionRevisionConflict(Exception):
    """Expected settings revision does not match current state."""


class RetentionApplicationInProgress(Exception):
    """An existing-archive recalculation is already active."""


class RetentionApplicationLeaseLost(Exception):
    """A recalculation worker no longer owns the durable application lease."""


@dataclasses.dataclass(frozen=True)
class RetentionSettingsUpdateResult:
    """Result of updating archive-retention settings."""

    settings: SystemFileLifecycleSettings
    application: ArchivedSessionRetentionApplication | None


@dataclasses.dataclass(frozen=True)
class RetentionRecalculationSummary:
    """One scheduler recalculation pass summary."""

    claimed: bool
    application_id: str | None
    affected_count: int
    immediately_eligible_count: int
    cancelled_count: int
    scheduled_count: int
    skipped_count: int
    completed: bool


@dataclasses.dataclass
class ArchivedSessionRetentionService:
    """Coordinate retention settings and durable existing-archive application."""

    repository: Annotated[
        ArchivedSessionRetentionRepository,
        Depends(ArchivedSessionRetentionRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def get_settings(self) -> SystemFileLifecycleSettings:
        """Return current instance-wide file lifecycle settings."""
        async with self.session_manager() as session:
            return await self.repository.get_settings(session)

    async def preview(self, retention_days: int | None) -> RetentionImpactPreview:
        """Preview applying retention to existing archives."""
        self._validate_retention_days(retention_days)
        async with self.session_manager() as session:
            return await self.repository.preview(
                session,
                retention_days=retention_days,
                now=datetime.datetime.now(datetime.UTC),
            )

    async def update_settings(
        self,
        *,
        expected_revision: int,
        retention_days: int | None,
        application_scope: RetentionApplicationScope,
        user_id: str,
    ) -> RetentionSettingsUpdateResult:
        """Update settings and optionally enqueue existing-archive recalculation."""
        self._validate_retention_days(retention_days)
        async with self.session_manager() as session:
            current = await self.repository.lock_settings(session)
            active = await self.repository.get_active_application(session)
            if active is not None:
                raise RetentionApplicationInProgress(active.id)
            if current.revision != expected_revision:
                raise RetentionRevisionConflict(expected_revision)
            updated = await self.repository.update_settings(
                session,
                expected_revision=expected_revision,
                retention_days=retention_days,
                updated_by_user_id=user_id,
            )
            if updated is None:
                raise RetentionRevisionConflict(expected_revision)
            application = None
            if application_scope == "recalculate_existing":
                application = await self.repository.create_application(
                    session,
                    target_revision=updated.revision,
                    target_retention_days=retention_days,
                    requested_by_user_id=user_id,
                )
            return RetentionSettingsUpdateResult(
                settings=updated,
                application=application,
            )

    async def recalculate_once(
        self,
        *,
        lease_owner: str,
    ) -> RetentionRecalculationSummary:
        """Apply one bounded existing-archive recalculation batch."""
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            application = await self.repository.claim_application(
                session,
                now=now,
                lease_owner=lease_owner,
                lease_until=now + _RECALCULATION_LEASE,
            )
        if application is None:
            return RetentionRecalculationSummary(
                claimed=False,
                application_id=None,
                affected_count=0,
                immediately_eligible_count=0,
                cancelled_count=0,
                scheduled_count=0,
                skipped_count=0,
                completed=False,
            )
        try:
            async with self.session_manager() as session:
                batch = await self.repository.apply_next_batch(
                    session,
                    application=application,
                    now=now,
                    limit=_RECALCULATION_BATCH_LIMIT,
                )
                completed = batch.scanned_count < _RECALCULATION_BATCH_LIMIT
                advanced = await self.repository.advance_application(
                    session,
                    application_id=application.id,
                    lease_owner=lease_owner,
                    batch=batch,
                    completed=completed,
                    now=now,
                )
                if not advanced:
                    raise RetentionApplicationLeaseLost(application.id)
        except Exception as error:
            retry_delay = self._retry_delay(application.attempt_count)
            async with self.session_manager() as session:
                await self.repository.mark_application_retry(
                    session,
                    application_id=application.id,
                    next_attempt_at=now + retry_delay,
                    error_kind=type(error).__name__,
                    error_summary=_RECALCULATION_ERROR_SUMMARY,
                    now=now,
                )
            raise
        return RetentionRecalculationSummary(
            claimed=True,
            application_id=application.id,
            affected_count=batch.affected_count,
            immediately_eligible_count=batch.immediately_eligible_count,
            cancelled_count=batch.cancelled_count,
            scheduled_count=batch.scheduled_count,
            skipped_count=batch.skipped_count,
            completed=completed,
        )

    @staticmethod
    def _validate_retention_days(retention_days: int | None) -> None:
        if retention_days is not None and (
            isinstance(retention_days, bool) or retention_days < 0
        ):
            raise ValueError("Archive retention days must be a non-negative integer")

    @staticmethod
    def _retry_delay(attempt_count: int) -> datetime.timedelta:
        delay_minutes = min(2 ** max(attempt_count - 1, 0), 30)
        delay = datetime.timedelta(minutes=delay_minutes)
        return min(delay, _RECALCULATION_MAX_RETRY_DELAY)
