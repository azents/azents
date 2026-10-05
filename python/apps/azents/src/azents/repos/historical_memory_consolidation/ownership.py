"""Repository-owned claim, renewal and terminal transactions for private jobs."""

import asyncio
import datetime
import logging
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from uuid6 import uuid7

from azents.core.enums import AgentLifecycleStatus
from azents.core.historical_memory_consolidation import (
    ConsolidationAttemptState,
    ConsolidationJobPrincipal,
    ConsolidationUnitKey,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
    ConsolidationDeadlineError,
    consolidation_job_session,
    consolidation_session,
    database_now,
    install_statement_deadline,
    lock_unit_authority,
    unit_predicate,
)
from azents.repos.historical_memory_consolidation.retry import (
    retry_consolidation_operation,
    retry_rolled_back_operation,
)
from azents.repos.historical_memory_consolidation.work import (
    pending_work_query,
    work_predicate,
)

_LEASE = datetime.timedelta(seconds=120)
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

    session_manager: SessionManager[WriteSession]

    async def validate(self, principal: ConsolidationJobPrincipal) -> None:
        """Observe current admission; actual evidence and draft writes fence again."""
        unit = RDBConsolidationUnit
        attempt = RDBConsolidationAttempt
        key = principal.unit
        grant = (
            sa.select(RDBWorkspaceUser.memory_grant_identity)
            .where(
                RDBWorkspaceUser.workspace_id == key.workspace_id,
                RDBWorkspaceUser.user_id == key.associated_user_id,
            )
            .scalar_subquery()
        )
        async with consolidation_session(self.session_manager) as session:
            now = await database_now(session)
            available = await session.read_session.scalar(
                sa.select(
                    sa.select(unit.id)
                    .join(RDBAgent, RDBAgent.id == unit.agent_id)
                    .join(attempt, attempt.id == unit.active_attempt_id)
                    .where(
                        unit_predicate(key),
                        RDBAgent.workspace_id == key.workspace_id,
                        RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                        RDBAgent.memory_enabled.is_(True),
                        unit.owner_generation == principal.owner_generation,
                        unit.owner_token == principal.owner_token,
                        unit.active_attempt_id == principal.attempt_id,
                        unit.lease_until > now,
                        attempt.unit_id == unit.id,
                        attempt.owner_generation == principal.owner_generation,
                        attempt.owner_token == principal.owner_token,
                        attempt.state == ConsolidationAttemptState.RUNNING,
                        attempt.deadline_at > now,
                        attempt.membership_grant_id.is_not_distinct_from(grant),
                        sa.true()
                        if key.associated_user_id is None
                        else grant.is_not(None),
                    )
                    .exists()
                )
            )
            if not available:
                raise ConsolidationAuthorityError(
                    "Consolidation owner is no longer current."
                )

    async def claim(
        self, key: ConsolidationUnitKey, *, deadline: datetime.datetime
    ) -> ConsolidationClaim | None:
        """Claim only an unowned/expired unit; a duplicate leaves work untouched."""
        seconds = (deadline - datetime.datetime.now(datetime.UTC)).total_seconds()
        if seconds <= 0:
            return None
        timeout = asyncio.timeout(seconds)
        try:
            async with timeout:
                return await self._claim_once(key, deadline=deadline)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            if not timeout.expired():
                raise
            raise ConsolidationDeadlineError(
                "Consolidation claim deadline was exceeded."
            ) from None

    @retry_rolled_back_operation
    async def _claim_once(
        self, key: ConsolidationUnitKey, *, deadline: datetime.datetime
    ) -> ConsolidationClaim | None:
        """One complete rollback-safe claim under the caller's absolute deadline."""
        async with consolidation_session(self.session_manager) as session:
            now = await database_now(session)
            remaining = (deadline - now).total_seconds()
            if remaining <= 0:
                return None
            await install_statement_deadline(session, remaining)
            grant = await lock_unit_authority(session, key)
            await session.write_session.execute(
                insert(RDBConsolidationUnit)
                .values(id=uuid7().hex, **key.model_dump())
                .on_conflict_do_nothing()
            )
            unit = await session.write_session.scalar(
                sa.select(RDBConsolidationUnit)
                .where(unit_predicate(key))
                .with_for_update()
            )
            if unit is None:
                raise RuntimeError("Consolidation unit disappeared during claim.")
            now = await database_now(session)
            if deadline <= now:
                return None
            if unit.lease_until is not None and unit.lease_until > now:
                return None
            if unit.retry_at is not None and unit.retry_at > now:
                return None
            if unit.active_attempt_id is not None:
                previous = await session.write_session.get(
                    RDBConsolidationAttempt, unit.active_attempt_id
                )
                if previous is not None:
                    previous.state = ConsolidationAttemptState.CANCELLED
                    previous.failure_code = None
                    previous.finished_at = now
            upper = unit.pass_upper_sequence
            remaining = upper is not None and await session.write_session.scalar(
                sa.select(
                    pending_work_query(key, grant)
                    .where(RDBConsolidationWork.sequence <= upper)
                    .exists()
                )
            )
            if not remaining:
                upper = await session.write_session.scalar(
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
                deadline_at=deadline,
                pass_upper_sequence=upper,
                membership_grant_id=grant,
            )
            session.write_session.add(attempt)
            await session.write_session.flush()
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

    @retry_consolidation_operation
    async def renew(self, principal: ConsolidationJobPrincipal) -> datetime.datetime:
        """Extend a still-current lease, never revive an expired owner."""
        async with consolidation_job_session(self.session_manager, principal) as job:
            session, owner = job.session, job.owner
            until = min(owner.database_now + _LEASE, owner.attempt.deadline_at)
            owner.unit.lease_until = until
            await session.write_session.flush()
        return until

    @retry_rolled_back_operation
    async def fail(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        failure_code: str | None,
        cancelled: bool,
    ) -> None:
        """Settle the exact owner metadata without reviving expired work authority."""
        if failure_code is not None and (not failure_code or len(failure_code) > 120):
            raise ValueError(
                "Consolidation failure code must contain 1-120 characters."
            )
        async with consolidation_session(self.session_manager) as session:
            unit = await session.write_session.scalar(
                sa.select(RDBConsolidationUnit)
                .where(unit_predicate(principal.unit))
                .with_for_update()
            )
            if (
                unit is None
                or unit.active_attempt_id != principal.attempt_id
                or unit.owner_generation != principal.owner_generation
                or unit.owner_token != principal.owner_token
            ):
                raise ConsolidationAuthorityError(
                    "Consolidation terminal owner is no longer current."
                )
            attempt = await session.write_session.scalar(
                sa.select(RDBConsolidationAttempt)
                .where(
                    RDBConsolidationAttempt.id == principal.attempt_id,
                    RDBConsolidationAttempt.unit_id == unit.id,
                    RDBConsolidationAttempt.owner_generation
                    == principal.owner_generation,
                    RDBConsolidationAttempt.owner_token == principal.owner_token,
                    RDBConsolidationAttempt.state == ConsolidationAttemptState.RUNNING,
                )
                .with_for_update()
            )
            if attempt is None:
                raise ConsolidationAuthorityError(
                    "Consolidation terminal attempt is unavailable."
                )
            now = await database_now(session)
            attempt.state = (
                ConsolidationAttemptState.CANCELLED
                if cancelled
                else ConsolidationAttemptState.FAILED
            )
            attempt.failure_code = failure_code
            attempt.finished_at = now
            unit.owner_token = None
            unit.lease_until = None
            unit.active_attempt_id = None
            unit.failure_count += 1
            unit.no_progress_count += 1
            delay = min(60 * 2 ** min(unit.failure_count - 1, 9), 21600)
            unit.retry_at = now + datetime.timedelta(seconds=delay)
            await session.write_session.flush()
            unit_id = unit.id
            no_progress_count = unit.no_progress_count
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
