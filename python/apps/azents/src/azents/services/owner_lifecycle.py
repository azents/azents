"""Scheduler-owned User Session owner lifecycle coordinator."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated, NamedTuple, Protocol

from fastapi import Depends

from azents.broker.deps import get_broker
from azents.broker.types import SessionStopSignal
from azents.core.enums import (
    AgentSessionProductMode,
    OwnerLifecycleKind,
    OwnerLifecycleStatus,
)
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.repos.owner_lifecycle.data import OwnerLifecycleJob
from azents.repos.owner_lifecycle_operations import OwnerLifecycleOperationsRepository
from azents.services.external_channel.lifecycle import ExternalChannelLifecycleService

_LEASE_DURATION = datetime.timedelta(minutes=15)
_MAX_RETRY_DELAY = datetime.timedelta(minutes=30)
_JOB_LIMIT = 100
_DEADLINE_SAFETY_MARGIN = datetime.timedelta(seconds=30)
logger = logging.getLogger(__name__)


class OwnerLifecycleBrokerProtocol(Protocol):
    """Broker used to deliver stop signals after durable stop requests."""

    async def send_message(self, signal: SessionStopSignal) -> None:
        """Send one stop signal."""
        ...


class OwnerLifecycleCleanupProtocol(Protocol):
    """Post-commit provider effect consumption."""

    async def consume_archive_cleanup(
        self, plans: tuple[ProviderEffectPlan, ...]
    ) -> None:
        """Attempt committed provider cleanup plans."""
        ...


class OwnerLifecycleAdvanceResult(NamedTuple):
    """Outcome flags returned after advancing one lifecycle job."""

    completed: bool
    waiting_purge: bool


@dataclasses.dataclass(frozen=True)
class OwnerLifecycleSummary:
    """Result of one scheduler owner-lifecycle pass."""

    claimed_count: int
    completed_count: int
    retry_scheduled_count: int
    waiting_purge_count: int
    deadline_reached: bool
    limit_reached: bool


@dataclasses.dataclass
class OwnerLifecycleService:
    """Archive/purge User Sessions for membership loss and account deletion."""

    operation_repository: Annotated[OwnerLifecycleOperationsRepository, Depends()]
    external_channel_lifecycle_service: Annotated[
        OwnerLifecycleCleanupProtocol, Depends(ExternalChannelLifecycleService)
    ]
    broker: Annotated[OwnerLifecycleBrokerProtocol, Depends(get_broker)]

    async def process_once(
        self,
        *,
        lease_owner: str,
        deadline: datetime.datetime,
    ) -> OwnerLifecycleSummary:
        """Claim and advance a bounded set of owner-lifecycle jobs."""
        claimed_count = 0
        completed_count = 0
        retry_scheduled_count = 0
        waiting_purge_count = 0
        deadline_reached = False

        for _ in range(_JOB_LIMIT):
            now = datetime.datetime.now(datetime.UTC)
            if now + _DEADLINE_SAFETY_MARGIN >= deadline:
                deadline_reached = True
                break
            job = await self.operation_repository.claim_due(
                now=now,
                lease_owner=lease_owner,
                lease_until=now + _LEASE_DURATION,
            )
            if job is None:
                break
            claimed_count += 1

            try:
                completed, waiting_purge = await self._advance(
                    job=job,
                    lease_owner=lease_owner,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._retry(
                    job=job,
                    lease_owner=lease_owner,
                    error_kind=type(exc).__name__,
                    error_summary=str(exc) or type(exc).__name__,
                )
                retry_scheduled_count += 1
                logger.exception(
                    "Owner lifecycle job failed; retry scheduled",
                    extra={
                        "owner_lifecycle_job_id": job.id,
                        "owner_lifecycle_kind": job.kind.value,
                        "target_user_id": job.user_id,
                        "workspace_id": job.workspace_id,
                        "attempt_count": job.attempt_count,
                    },
                )
                continue

            completed_count += int(completed)
            waiting_purge_count += int(waiting_purge)

        return OwnerLifecycleSummary(
            claimed_count=claimed_count,
            completed_count=completed_count,
            retry_scheduled_count=retry_scheduled_count,
            waiting_purge_count=waiting_purge_count,
            deadline_reached=deadline_reached,
            limit_reached=claimed_count == _JOB_LIMIT,
        )

    async def _advance(
        self,
        *,
        job: OwnerLifecycleJob,
        lease_owner: str,
    ) -> OwnerLifecycleAdvanceResult:
        """Advance one owned owner-lifecycle job."""
        if job.kind is OwnerLifecycleKind.MEMBERSHIP_ARCHIVE:
            return await self._advance_membership_archive(
                job=job,
                lease_owner=lease_owner,
            )
        if job.kind is OwnerLifecycleKind.ACCOUNT_PURGE:
            return await self._advance_account_purge(
                job=job,
                lease_owner=lease_owner,
            )
        raise RuntimeError(f"Unsupported owner lifecycle kind: {job.kind}")

    async def _advance_membership_archive(
        self,
        *,
        job: OwnerLifecycleJob,
        lease_owner: str,
    ) -> OwnerLifecycleAdvanceResult:
        """Archive active User roots after membership loss."""
        if job.workspace_id is None:
            raise RuntimeError("Membership archive job is missing workspace_id")

        roots = await self.operation_repository.membership_roots(
            workspace_id=job.workspace_id, user_id=job.user_id
        )

        if roots:
            await self._set_status(
                job_id=job.id,
                lease_owner=lease_owner,
                status=OwnerLifecycleStatus.RETIRING_SESSIONS,
            )
            waiting_for_active_run = False
            for root in roots:
                if root.product_mode is not AgentSessionProductMode.USER:
                    raise RuntimeError("Owner lifecycle saw a non-User root")
                retired = await self._retire_root_tree(
                    job=job,
                    lease_owner=lease_owner,
                    root_session_id=root.id,
                    immediate_purge=False,
                )
                waiting_for_active_run = waiting_for_active_run or not retired
            if waiting_for_active_run:
                raise RuntimeError("User Session root tree still has active work")

        completed = await self.operation_repository.complete_membership(
            job_id=job.id, lease_owner=lease_owner
        )
        if not completed:
            raise RuntimeError("Owner lifecycle lease was lost before completion")
        return OwnerLifecycleAdvanceResult(completed=True, waiting_purge=False)

    async def _advance_account_purge(
        self,
        *,
        job: OwnerLifecycleJob,
        lease_owner: str,
    ) -> OwnerLifecycleAdvanceResult:
        """Purge all User Sessions and finalize account deletion."""
        roots = await self.operation_repository.account_roots(user_id=job.user_id)

        if roots:
            await self._set_status(
                job_id=job.id,
                lease_owner=lease_owner,
                status=OwnerLifecycleStatus.RETIRING_SESSIONS,
            )
            waiting_for_active_run = False
            for root in roots:
                if root.product_mode is not AgentSessionProductMode.USER:
                    raise RuntimeError("Owner lifecycle saw a non-User root")
                retired = await self._retire_root_tree(
                    job=job,
                    lease_owner=lease_owner,
                    root_session_id=root.id,
                    immediate_purge=True,
                )
                waiting_for_active_run = waiting_for_active_run or not retired
            if waiting_for_active_run:
                raise RuntimeError("User Session root tree still has active work")

        remaining = await self.operation_repository.remaining_user_sessions(
            user_id=job.user_id
        )
        if remaining:
            await self._set_status(
                job_id=job.id,
                lease_owner=lease_owner,
                status=OwnerLifecycleStatus.WAITING_PURGE,
            )
            # Requeue soon so archived purge progress is observed.
            await self._retry(
                job=job,
                lease_owner=lease_owner,
                error_kind="WaitingPurge",
                error_summary="Owned User Session rows remain pending purge",
                delay=datetime.timedelta(minutes=1),
            )
            return OwnerLifecycleAdvanceResult(completed=False, waiting_purge=True)

        await self._set_status(
            job_id=job.id,
            lease_owner=lease_owner,
            status=OwnerLifecycleStatus.FINALIZING,
        )
        await self.operation_repository.finalize_account(
            job=job, lease_owner=lease_owner
        )
        logger.info(
            "Owner lifecycle account purge finalized User deletion",
            extra={
                "owner_lifecycle_job_id": job.id,
                "target_user_id": job.user_id,
            },
        )
        return OwnerLifecycleAdvanceResult(completed=True, waiting_purge=False)

    async def _retire_root_tree(
        self,
        *,
        job: OwnerLifecycleJob,
        lease_owner: str,
        root_session_id: str,
        immediate_purge: bool,
    ) -> bool:
        """Consume effects after the complete atomic User root retirement."""
        result = await self.operation_repository.retire_root_tree(
            job=job,
            lease_owner=lease_owner,
            root_session_id=root_session_id,
            immediate_purge=immediate_purge,
        )
        if result.archived:
            await self.external_channel_lifecycle_service.consume_archive_cleanup(
                result.cleanup_plans
            )
        for session_id in result.stop_session_ids:
            await self.broker.send_message(SessionStopSignal(session_id=session_id))
        return result.retired

    async def _set_status(
        self, *, job_id: str, lease_owner: str, status: OwnerLifecycleStatus
    ) -> None:
        """Persist one owned status transition."""
        owned = await self.operation_repository.set_status(
            job_id=job_id, lease_owner=lease_owner, status=status
        )
        if not owned:
            raise RuntimeError("Owner lifecycle lease was lost")

    async def _retry(
        self,
        *,
        job: OwnerLifecycleJob,
        lease_owner: str,
        error_kind: str,
        error_summary: str,
        delay: datetime.timedelta | None = None,
    ) -> None:
        """Release one owned job into retry wait."""
        now = datetime.datetime.now(datetime.UTC)
        if delay is None:
            # Exponential-ish backoff capped for ordinary failures.
            attempt = max(job.attempt_count, 1)
            seconds = min(
                30 * (2 ** min(attempt - 1, 6)), int(_MAX_RETRY_DELAY.total_seconds())
            )
            delay = datetime.timedelta(seconds=seconds)
        await self.operation_repository.mark_retry(
            job=job,
            lease_owner=lease_owner,
            next_attempt_at=now + delay,
            error_kind=error_kind,
            error_summary=error_summary,
            now=now,
        )
