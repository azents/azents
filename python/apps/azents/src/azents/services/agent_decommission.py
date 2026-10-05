"""Scheduler-owned Agent decommission coordinator."""

import asyncio
import dataclasses
import datetime
import logging
from collections.abc import Sequence
from typing import Annotated, Protocol

from azcommon.infra.s3.service import S3Service
from fastapi import Depends

from azents.broker.deps import get_broker
from azents.broker.types import SessionStopSignal
from azents.core.config import Config, require_workspace_s3_bucket
from azents.core.deps import get_config
from azents.core.enums import AgentDecommissionStatus, AgentSessionStatus
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.core.s3.deps import get_s3_service
from azents.repos.agent_decommission.data import AgentDecommissionJob
from azents.repos.agent_decommission_operations import (
    AgentDecommissionOperationsRepository,
)
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.services.external_channel.lifecycle import ExternalChannelLifecycleService
from azents.services.uploads.handlers.avatar import AvatarUploadHandler

_LEASE_DURATION = datetime.timedelta(minutes=15)
_MAX_RETRY_DELAY = datetime.timedelta(minutes=30)
_JOB_LIMIT = 100
_DEADLINE_SAFETY_MARGIN = datetime.timedelta(seconds=30)
logger = logging.getLogger(__name__)


class AgentDecommissionBrokerProtocol(Protocol):
    """Post-commit stop signaling consumed by root retirement."""

    async def send_message(self, signal: SessionStopSignal) -> None:
        """Notify one Session runner to stop."""
        ...


class AgentDecommissionRuntimeServiceProtocol(Protocol):
    """Terminal Runtime deletion request operation."""

    async def request_terminal_delete_for_agent(self, agent_id: str) -> object | None:
        """Request idempotent terminal deletion for an Agent Runtime."""
        ...


class AgentDecommissionCleanupProtocol(Protocol):
    """Post-commit provider effect consumption."""

    async def consume_archive_cleanup(self, plans: Sequence[ProviderEffectPlan]) -> int:
        """Attempt committed provider cleanup plans."""
        ...


@dataclasses.dataclass(frozen=True)
class AgentDecommissionAdvanceResult:
    """Result of advancing one Agent decommission job."""

    completed: bool
    waiting_retention: bool


@dataclasses.dataclass(frozen=True)
class AgentDecommissionSummary:
    """Result of one bounded Agent decommission scheduler pass."""

    claimed_count: int
    completed_count: int
    retry_scheduled_count: int
    waiting_retention_count: int
    deadline_reached: bool
    limit_reached: bool


@dataclasses.dataclass
class AgentDecommissionService:
    """Retire Agent roots and finalize only after retention purge completion."""

    operation_repository: Annotated[AgentDecommissionOperationsRepository, Depends()]
    agent_runtime_service: Annotated[
        AgentDecommissionRuntimeServiceProtocol, Depends(AgentRuntimeService)
    ]
    external_channel_lifecycle_service: Annotated[
        AgentDecommissionCleanupProtocol, Depends(ExternalChannelLifecycleService)
    ]
    broker: Annotated[AgentDecommissionBrokerProtocol, Depends(get_broker)]
    s3_service: Annotated[S3Service, Depends(get_s3_service)]
    config: Annotated[Config, Depends(get_config)]
    avatar_handler: Annotated[AvatarUploadHandler, Depends(AvatarUploadHandler)]

    async def decommission_once(
        self,
        *,
        lease_owner: str,
        deadline: datetime.datetime,
    ) -> AgentDecommissionSummary:
        """Claim and advance a bounded set of Agent decommission jobs."""
        claimed_count = 0
        completed_count = 0
        retry_scheduled_count = 0
        waiting_retention_count = 0
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
                advance_result = await self._advance(
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
                    "Agent decommission job failed; retry scheduled",
                    extra={
                        "agent_decommission_job_id": job.id,
                        "agent_id": job.agent_id,
                        "attempt_count": job.attempt_count,
                    },
                )
                continue

            completed_count += int(advance_result.completed)
            waiting_retention_count += int(advance_result.waiting_retention)

        return AgentDecommissionSummary(
            claimed_count=claimed_count,
            completed_count=completed_count,
            retry_scheduled_count=retry_scheduled_count,
            waiting_retention_count=waiting_retention_count,
            deadline_reached=deadline_reached,
            limit_reached=claimed_count == _JOB_LIMIT,
        )

    async def _advance(
        self,
        *,
        job: AgentDecommissionJob,
        lease_owner: str,
    ) -> AgentDecommissionAdvanceResult:
        """Advance one owned decommission job without bypassing session purge."""
        roots = await self.operation_repository.list_roots(agent_id=job.agent_id)

        if roots:
            await self._set_status(
                job_id=job.id,
                lease_owner=lease_owner,
                expected_attempt=job.attempt_count,
                status=AgentDecommissionStatus.RETIRING_SESSIONS,
            )
            waiting_for_active_run = False
            for root in roots:
                if root.status is AgentSessionStatus.ARCHIVED:
                    continue
                if root.status is not AgentSessionStatus.ACTIVE:
                    raise RuntimeError("Agent root Session has an unsupported status")
                retired = await self._retire_root_tree(
                    job=job,
                    lease_owner=lease_owner,
                    root_session_id=root.id,
                )
                waiting_for_active_run = waiting_for_active_run or not retired
            if waiting_for_active_run:
                raise RuntimeError("Agent root tree still has active work")
            await self._set_status(
                job_id=job.id,
                lease_owner=lease_owner,
                expected_attempt=job.attempt_count,
                status=AgentDecommissionStatus.WAITING_RETENTION,
            )
            return AgentDecommissionAdvanceResult(
                completed=False,
                waiting_retention=True,
            )

        await self._set_status(
            job_id=job.id,
            lease_owner=lease_owner,
            expected_attempt=job.attempt_count,
            status=AgentDecommissionStatus.FINALIZING,
        )
        await self._cleanup_agent_external_roots(
            job=job,
            lease_owner=lease_owner,
        )
        completed = await self.operation_repository.finalize(
            job=job, lease_owner=lease_owner
        )
        if not completed:
            raise RuntimeError("Agent decommission lease was lost before finalization")
        return AgentDecommissionAdvanceResult(
            completed=True,
            waiting_retention=False,
        )

    async def _retire_root_tree(
        self,
        *,
        job: AgentDecommissionJob,
        lease_owner: str,
        root_session_id: str,
    ) -> bool:
        """Consume effects only after atomic root retirement finishes."""
        result = await self.operation_repository.retire_root_tree(
            job=job,
            lease_owner=lease_owner,
            root_session_id=root_session_id,
        )
        if result.archived:
            await self.external_channel_lifecycle_service.consume_archive_cleanup(
                result.cleanup_plans
            )
        for session_id in result.stop_session_ids:
            await self.broker.send_message(SessionStopSignal(session_id=session_id))
        return result.retired

    async def _cleanup_agent_external_roots(
        self,
        *,
        job: AgentDecommissionJob,
        lease_owner: str,
    ) -> None:
        """Sequence completed cleanup preparation and external effects."""
        if await self.operation_repository.runtime_bound(agent_id=job.agent_id):
            await self.agent_runtime_service.request_terminal_delete_for_agent(
                job.agent_id
            )
        snapshot = await self.operation_repository.prepare_external_cleanup(
            job=job, lease_owner=lease_owner
        )
        await self.external_channel_lifecycle_service.consume_archive_cleanup(
            snapshot.cleanup_plans
        )
        for file in snapshot.files:
            if file.blob_deleted_at is not None:
                continue
            await self.s3_service.delete(
                bucket=require_workspace_s3_bucket(self.config.workspace_s3),
                key=file.object_key,
            )
            await self.operation_repository.mark_blob_deleted(file_id=file.id)
        if snapshot.agent.avatar is not None:
            await self.avatar_handler.delete_files(
                snapshot.agent.avatar,
                self.s3_service,
                require_workspace_s3_bucket(self.config.workspace_s3),
            )
        await self.operation_repository.finish_external_cleanup(agent_id=job.agent_id)

    async def _set_status(
        self,
        *,
        job_id: str,
        lease_owner: str,
        expected_attempt: int,
        status: AgentDecommissionStatus,
    ) -> None:
        """Persist an owned job phase or surface a lost lease."""
        updated = await self.operation_repository.set_status(
            job_id=job_id,
            lease_owner=lease_owner,
            expected_attempt=expected_attempt,
            status=status,
        )
        if not updated:
            raise RuntimeError("Agent decommission lease was lost")

    async def _retry(
        self,
        *,
        job: AgentDecommissionJob,
        lease_owner: str,
        error_kind: str,
        error_summary: str,
    ) -> None:
        """Release failed work with bounded exponential backoff."""
        now = datetime.datetime.now(datetime.UTC)
        delay_minutes = min(2 ** max(0, job.attempt_count - 1), 30)
        delay = min(datetime.timedelta(minutes=delay_minutes), _MAX_RETRY_DELAY)
        await self.operation_repository.mark_retry(
            job=job,
            lease_owner=lease_owner,
            next_attempt_at=now + delay,
            error_kind=error_kind,
            error_summary=error_summary,
            now=now,
        )
