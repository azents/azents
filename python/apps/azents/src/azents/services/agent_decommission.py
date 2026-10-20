"""Scheduler-owned Agent decommission through independently testable participants."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated, Protocol

from azcommon.infra.s3.service import S3Service
from fastapi import Depends

from azents.broker.deps import get_broker
from azents.core.agent_deletion import (
    AgentDeletionOwnershipLost,
    AgentDeletionParticipantFailure,
    AgentDeletionRegistry,
    AgentDeletionWaitReason,
)
from azents.core.agent_deletion_registry import get_agent_deletion_registry
from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.s3.deps import get_s3_service
from azents.repos.agent_decommission.data import AgentDecommissionJob
from azents.repos.agent_decommission_operations import (
    AgentDecommissionOperationsRepository,
)
from azents.services.agent_deletion import (
    AgentDeletionPipeline,
    AvatarDeletionParticipant,
    ChannelDeletionParticipant,
    DatabaseDeletionParticipant,
    DeletionBroker,
    DeletionChannelEffects,
    DeletionRuntime,
    FileDeletionParticipant,
    RuntimeDeletionParticipant,
    SessionRetirementParticipant,
)
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.services.external_channel.lifecycle import ExternalChannelLifecycleService
from azents.services.uploads.handlers.avatar import AvatarUploadHandler

_LEASE_DURATION = datetime.timedelta(minutes=15)
_MAX_RETRY_DELAY = datetime.timedelta(minutes=30)
_JOB_LIMIT = 100
_DEADLINE_SAFETY_MARGIN = datetime.timedelta(seconds=30)
logger = logging.getLogger(__name__)


class DecommissionClock(Protocol):
    def now(self) -> datetime.datetime: ...


class SystemDecommissionClock:
    def now(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.UTC)


@dataclasses.dataclass(frozen=True)
class AgentDecommissionAdvanceResult:
    completed: bool
    wait_reason: AgentDeletionWaitReason | None


@dataclasses.dataclass(frozen=True)
class AgentDecommissionSummary:
    claimed_count: int
    completed_count: int
    retry_scheduled_count: int
    waiting_retention_count: int
    deadline_reached: bool
    limit_reached: bool


@dataclasses.dataclass
class AgentDecommissionService:
    """Own scheduling and failure attribution, not domain-specific cleanup lists."""

    operation_repository: Annotated[AgentDecommissionOperationsRepository, Depends()]
    agent_runtime_service: Annotated[DeletionRuntime, Depends(AgentRuntimeService)]
    external_channel_lifecycle_service: Annotated[
        DeletionChannelEffects, Depends(ExternalChannelLifecycleService)
    ]
    broker: Annotated[DeletionBroker, Depends(get_broker)]
    s3_service: Annotated[S3Service, Depends(get_s3_service)]
    config: Annotated[Config, Depends(get_config)]
    avatar_handler: Annotated[AvatarUploadHandler, Depends(AvatarUploadHandler)]
    registry: Annotated[AgentDeletionRegistry, Depends(get_agent_deletion_registry)]
    clock: Annotated[DecommissionClock, Depends(SystemDecommissionClock)]

    async def decommission_once(
        self, *, lease_owner: str, deadline: datetime.datetime
    ) -> AgentDecommissionSummary:
        claimed_count = 0
        completed_count = 0
        retry_scheduled_count = 0
        waiting_retention_count = 0
        deadline_reached = False
        for _ in range(_JOB_LIMIT):
            now = self.clock.now()
            if now + _DEADLINE_SAFETY_MARGIN >= deadline:
                deadline_reached = True
                break
            job = await self.operation_repository.claim_due(
                now=now, lease_owner=lease_owner, lease_until=now + _LEASE_DURATION
            )
            if job is None:
                break
            claimed_count += 1
            try:
                result = await self._advance(job=job, lease_owner=lease_owner)
            except asyncio.CancelledError:
                raise
            except AgentDeletionOwnershipLost:
                logger.info(
                    "Agent decommission attempt lost ownership",
                    extra={
                        "agent_decommission_job_id": job.id,
                        "attempt_count": job.attempt_count,
                    },
                )
                continue
            except Exception as error:
                try:
                    await self._retry(
                        job=job,
                        lease_owner=lease_owner,
                        error_kind=type(error).__name__,
                        error_summary=str(error) or type(error).__name__,
                        failure_boundary_key=(
                            error.boundary_key
                            if isinstance(error, AgentDeletionParticipantFailure)
                            else "agent.coordinator/advance"
                        ),
                    )
                except AgentDeletionOwnershipLost:
                    logger.info(
                        "Agent decommission retry lost ownership",
                        extra={
                            "agent_decommission_job_id": job.id,
                            "attempt_count": job.attempt_count,
                        },
                    )
                    continue
                retry_scheduled_count += 1
                logger.exception(
                    "Agent decommission job failed; retry scheduled",
                    extra={
                        "agent_decommission_job_id": job.id,
                        "agent_id": job.agent_id,
                        "attempt_count": job.attempt_count,
                        "participant_key": error.participant_key
                        if isinstance(error, AgentDeletionParticipantFailure)
                        else None,
                        "phase": error.phase
                        if isinstance(error, AgentDeletionParticipantFailure)
                        else None,
                    },
                )
                continue
            completed_count += int(result.completed)
            if result.wait_reason is AgentDeletionWaitReason.RETENTION:
                waiting_retention_count += 1
            elif result.wait_reason is not None:
                now = self.clock.now()
                scheduled = await self.operation_repository.schedule_wait(
                    job=job,
                    lease_owner=lease_owner,
                    next_attempt_at=now + self._retry_delay(job.attempt_count),
                    now=now,
                )
                retry_scheduled_count += int(scheduled)
        return AgentDecommissionSummary(
            claimed_count,
            completed_count,
            retry_scheduled_count,
            waiting_retention_count,
            deadline_reached,
            claimed_count == _JOB_LIMIT,
        )

    async def _advance(
        self, *, job: AgentDecommissionJob, lease_owner: str
    ) -> AgentDecommissionAdvanceResult:
        operations = self.operation_repository
        pipeline = AgentDeletionPipeline(
            self.registry,
            (
                SessionRetirementParticipant(
                    operations, self.broker, self.external_channel_lifecycle_service
                ),
                RuntimeDeletionParticipant(operations, self.agent_runtime_service),
                ChannelDeletionParticipant(
                    operations, self.external_channel_lifecycle_service
                ),
                FileDeletionParticipant(operations, self.s3_service, self.config),
                AvatarDeletionParticipant(
                    operations, self.avatar_handler, self.s3_service, self.config
                ),
                DatabaseDeletionParticipant(operations),
            ),
            operations,
        )
        result = await pipeline.advance(job=job, lease_owner=lease_owner)
        return AgentDecommissionAdvanceResult(result.completed, result.wait_reason)

    @staticmethod
    def _retry_delay(attempt_count: int) -> datetime.timedelta:
        return min(
            datetime.timedelta(minutes=2 ** min(max(0, attempt_count - 1), 5)),
            _MAX_RETRY_DELAY,
        )

    async def _retry(
        self,
        *,
        job: AgentDecommissionJob,
        lease_owner: str,
        error_kind: str,
        error_summary: str,
        failure_boundary_key: str,
    ) -> None:
        now = self.clock.now()
        delay = self._retry_delay(job.attempt_count)
        updated = await self.operation_repository.mark_retry(
            job=job,
            lease_owner=lease_owner,
            next_attempt_at=now + delay,
            failure_boundary_key=failure_boundary_key,
            error_kind=error_kind,
            error_summary=error_summary,
            now=now,
        )
        if not updated:
            raise AgentDeletionOwnershipLost("Agent decommission retry lease was lost")
