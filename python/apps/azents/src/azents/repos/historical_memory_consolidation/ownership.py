"""Repository-owned claim, renewal and terminal transactions for private jobs."""

import datetime
import logging
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from azents.core.historical_memory_consolidation import (
    ConsolidationAttemptState,
    ConsolidationJobPrincipal,
    ConsolidationUnitKey,
)
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.session import SessionManager
from azents.repos.historical_memory_consolidation.authority import (
    consolidation_job_session,
    consolidation_session,
    database_now,
    lock_unit_authority,
    require_commit_owner,
    unit_predicate,
)
from azents.repos.historical_memory_consolidation.work import (
    pending_work_query,
    work_predicate,
)

_LEASE = datetime.timedelta(seconds=120)
_ATTEMPT = datetime.timedelta(minutes=10)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConsolidationClaim:
    """Committed owner identity and stable finite-pass admission boundary."""

    unit_id: str
    principal: ConsolidationJobPrincipal
    pass_upper_sequence: int
    deadline_at: datetime.datetime


@dataclass(frozen=True)
class ConsolidationOwnershipRepository:
    """Keep ownership independent of process-local locks, Redis and Sessions."""

    session_manager: SessionManager[AsyncSession]

    async def validate(self, principal: ConsolidationJobPrincipal) -> None:
        """Finish an admission transaction without leaking a live DB handle."""
        async with consolidation_job_session(self.session_manager, principal) as job:
            await require_commit_owner(job.session, job.owner)

    async def claim(self, key: ConsolidationUnitKey) -> ConsolidationClaim | None:
        """Claim only an unowned/expired unit; a duplicate leaves work untouched."""
        async with consolidation_session(self.session_manager) as session:
            grant = await lock_unit_authority(session, key)
            await session.execute(
                insert(RDBConsolidationUnit)
                .values(id=uuid7().hex, **key.model_dump())
                .on_conflict_do_nothing()
            )
            unit = await session.scalar(
                sa.select(RDBConsolidationUnit)
                .where(unit_predicate(key))
                .with_for_update()
            )
            if unit is None:
                raise RuntimeError("Consolidation unit disappeared during claim.")
            now = await database_now(session)
            if unit.lease_until is not None and unit.lease_until > now:
                return None
            if unit.retry_at is not None and unit.retry_at > now:
                return None
            if unit.active_attempt_id is not None:
                previous = await session.get(
                    RDBConsolidationAttempt, unit.active_attempt_id
                )
                if previous is not None:
                    previous.state = ConsolidationAttemptState.CANCELLED
                    previous.failure_code = "lease_expired"
                    previous.finished_at = now
            upper = unit.pass_upper_sequence
            remaining = upper is not None and await session.scalar(
                sa.select(
                    pending_work_query(key, grant)
                    .where(RDBConsolidationWork.sequence <= upper)
                    .exists()
                )
            )
            if not remaining:
                upper = await session.scalar(
                    sa.select(
                        sa.func.coalesce(sa.func.max(RDBConsolidationWork.sequence), 0)
                    ).where(work_predicate(key))
                )
            if not isinstance(upper, int):
                raise TypeError("Consolidation sequence boundary is not an integer.")
            unit.pass_upper_sequence = upper
            attempt_id = uuid7().hex
            token = uuid7().hex
            unit.owner_generation += 1
            unit.owner_token = token
            unit.lease_until = now + _LEASE
            unit.active_attempt_id = attempt_id
            attempt = RDBConsolidationAttempt(
                id=attempt_id,
                unit_id=unit.id,
                owner_generation=unit.owner_generation,
                owner_token=token,
                deadline_at=now + _ATTEMPT,
                pass_upper_sequence=upper,
                membership_grant_id=grant,
            )
            session.add(attempt)
            await session.flush()
            claim = ConsolidationClaim(
                unit_id=unit.id,
                principal=ConsolidationJobPrincipal(
                    unit=key,
                    attempt_id=attempt_id,
                    owner_generation=unit.owner_generation,
                    owner_token=token,
                ),
                pass_upper_sequence=upper,
                deadline_at=attempt.deadline_at,
            )
        return claim

    async def renew(self, principal: ConsolidationJobPrincipal) -> datetime.datetime:
        """Extend a still-current lease, never revive an expired owner."""
        async with consolidation_job_session(self.session_manager, principal) as job:
            session, owner = job.session, job.owner
            until = min(owner.database_now + _LEASE, owner.attempt.deadline_at)
            owner.unit.lease_until = until
            await session.flush()
        return until

    async def fail(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        failure_code: str,
        cancelled: bool,
    ) -> None:
        """Finish current work without publishing or acknowledging source coverage."""
        if not failure_code or len(failure_code) > 120:
            raise ValueError(
                "Consolidation failure code must contain 1-120 characters."
            )
        async with consolidation_job_session(self.session_manager, principal) as job:
            session, owner = job.session, job.owner
            await require_commit_owner(session, owner)
            owner.attempt.state = (
                ConsolidationAttemptState.CANCELLED
                if cancelled
                else ConsolidationAttemptState.FAILED
            )
            owner.attempt.failure_code = failure_code
            owner.attempt.finished_at = owner.database_now
            owner.unit.owner_token = None
            owner.unit.lease_until = None
            owner.unit.active_attempt_id = None
            owner.unit.failure_count += 1
            owner.unit.no_progress_count += 1
            delay = min(60 * 2 ** min(owner.unit.failure_count - 1, 9), 21600)
            owner.unit.retry_at = owner.database_now + datetime.timedelta(seconds=delay)
            await session.flush()
            unit_id = owner.unit.id
            no_progress_count = owner.unit.no_progress_count
        if no_progress_count >= 3:
            logger.warning(
                "Historical consolidation attempts made no completed coverage progress",
                extra={
                    "agent_id": principal.unit.agent_id,
                    "workspace_id": principal.unit.workspace_id,
                    "consolidation_unit_id": unit_id,
                    "consolidation_attempt_id": principal.attempt_id,
                    "no_progress_count": no_progress_count,
                },
            )
