"""Scheduler-owned Agent decommission coordinator."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated

from azcommon.infra.s3.service import S3Service
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.deps import get_broker
from azents.broker.types import SessionBroker, SessionStopSignal
from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    AgentDecommissionStatus,
    AgentSessionRunState,
    AgentSessionStatus,
)
from azents.core.s3.deps import get_s3_service
from azents.core.session_lifecycle import (
    SessionLifecycleParticipantDefinition,
    SessionLifecycleTransitionContext,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_decommission import AgentDecommissionRepository
from azents.repos.agent_decommission.data import AgentDecommissionJob
from azents.repos.agent_decommission_finalizer import (
    AgentDecommissionFinalizerRepository,
)
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.services.external_channel.lifecycle import ExternalChannelLifecycleService
from azents.services.session_lifecycle.orchestrator import (
    SessionLifecycleOrchestrator,
)
from azents.services.session_lifecycle.registry import (
    get_session_lifecycle_orchestrator,
)
from azents.services.uploads.handlers.avatar import AvatarUploadHandler

_LEASE_DURATION = datetime.timedelta(minutes=15)
_MAX_RETRY_DELAY = datetime.timedelta(minutes=30)
_JOB_LIMIT = 100
_DEADLINE_SAFETY_MARGIN = datetime.timedelta(seconds=30)

logger = logging.getLogger(__name__)


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

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    decommission_repository: Annotated[
        AgentDecommissionRepository, Depends(AgentDecommissionRepository)
    ]
    finalizer_repository: Annotated[
        AgentDecommissionFinalizerRepository,
        Depends(AgentDecommissionFinalizerRepository),
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    retention_repository: Annotated[
        ArchivedSessionRetentionRepository,
        Depends(ArchivedSessionRetentionRepository),
    ]
    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    exchange_file_repository: Annotated[
        ExchangeFileRepository, Depends(ExchangeFileRepository)
    ]
    lifecycle_orchestrator: Annotated[
        SessionLifecycleOrchestrator,
        Depends(get_session_lifecycle_orchestrator),
    ]
    external_channel_lifecycle_service: Annotated[
        ExternalChannelLifecycleService,
        Depends(ExternalChannelLifecycleService),
    ]
    broker: Annotated[SessionBroker, Depends(get_broker)]
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
            async with self.session_manager() as session:
                job = await self.decommission_repository.claim_due(
                    session,
                    now=now,
                    lease_owner=lease_owner,
                    lease_until=now + _LEASE_DURATION,
                )
            if job is None:
                break
            claimed_count += 1

            try:
                completed, waiting_retention = await self._advance(
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

            completed_count += int(completed)
            waiting_retention_count += int(waiting_retention)

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
    ) -> tuple[bool, bool]:
        """Advance one owned decommission job without bypassing session purge."""
        async with self.session_manager() as session:
            roots = await self.agent_session_repository.list_root_trees_by_agent_id(
                session,
                agent_id=job.agent_id,
            )

        if roots:
            await self._set_status(
                job_id=job.id,
                lease_owner=lease_owner,
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
                status=AgentDecommissionStatus.WAITING_RETENTION,
            )
            return False, True

        await self._set_status(
            job_id=job.id,
            lease_owner=lease_owner,
            status=AgentDecommissionStatus.FINALIZING,
        )
        await self._cleanup_agent_external_roots(
            job=job,
            lease_owner=lease_owner,
        )
        async with self.session_manager() as session:
            completed = await self.finalizer_repository.finalize(
                session,
                job_id=job.id,
                agent_id=job.agent_id,
                lease_owner=lease_owner,
                now=datetime.datetime.now(datetime.UTC),
            )
        if not completed:
            raise RuntimeError("Agent decommission lease was lost before finalization")
        return True, False

    async def _retire_root_tree(
        self,
        *,
        job: AgentDecommissionJob,
        lease_owner: str,
        root_session_id: str,
    ) -> bool:
        """Stop and archive one root tree through the shared lifecycle registry."""
        stop_session_ids: list[str] = []
        active = False
        async with self.session_manager() as session:
            tree = await self.agent_session_repository.lock_root_tree_sessions(
                session,
                root_session_id=root_session_id,
            )
            if not tree:
                return True
            if any(item.status is not AgentSessionStatus.ACTIVE for item in tree):
                raise RuntimeError("Agent root tree changed during decommission")
            session_ids = [item.id for item in tree]
            for session_id in session_ids:
                await self.agent_session_repository.request_stop(
                    session,
                    session_id=session_id,
                    stop_request_id=uuid7().hex,
                    user_id=None,
                )
            active = any(
                item.run_state is AgentSessionRunState.RUNNING for item in tree
            ) or await self.agent_run_repository.has_active_for_session_ids(
                session,
                session_ids=session_ids,
            )
            stop_session_ids = session_ids

            if not active:
                settings = await self.retention_repository.lock_settings(session)
                if settings.archived_session_retention_days is None:
                    raise RuntimeError(
                        "Agent decommission cannot retire roots under Unlimited "
                        "retention"
                    )
                archived_at = datetime.datetime.now(datetime.UTC)
                purge_after = archived_at + datetime.timedelta(
                    days=settings.archived_session_retention_days
                )

                async def archive_tree() -> None:
                    """Archive a system-owned root tree under the decommission fence."""
                    await self.agent_session_repository.archive_tree(
                        session,
                        root_session_id=root_session_id,
                        session_ids=session_ids,
                        archived_at=archived_at,
                        purge_after=purge_after,
                        policy_revision=settings.revision,
                        retention_days=settings.archived_session_retention_days,
                    )

                async def archive_participant(
                    definition: SessionLifecycleParticipantDefinition,
                    context: SessionLifecycleTransitionContext,
                ) -> None:
                    """Apply lifecycle-owned state before archiving the root tree."""
                    await self.external_channel_lifecycle_service.archive_participant(
                        session,
                        definition,
                        context,
                    )

                await self.lifecycle_orchestrator.archive(
                    context=SessionLifecycleTransitionContext(
                        transition_id=f"{job.id}:{root_session_id}:decommission",
                        root_session_id=root_session_id,
                        subtree_session_ids=tuple(session_ids),
                    ),
                    participant_operation=archive_participant,
                    transition=archive_tree,
                )
                await self.retention_repository.schedule_purge_job(
                    session,
                    root_session_id=root_session_id,
                    eligible_at=purge_after,
                    policy_revision=settings.revision,
                    now=archived_at,
                )
                owned = await self.decommission_repository.set_status(
                    session,
                    job_id=job.id,
                    lease_owner=lease_owner,
                    status=AgentDecommissionStatus.RETIRING_SESSIONS,
                    now=archived_at,
                )
                if not owned:
                    raise RuntimeError("Agent decommission lease was lost")
                await session.commit()

        for session_id in stop_session_ids:
            await self.broker.send_message(SessionStopSignal(session_id=session_id))
        return not active

    async def _cleanup_agent_external_roots(
        self,
        *,
        job: AgentDecommissionJob,
        lease_owner: str,
    ) -> None:
        """Clean direct Agent-owned blobs and request terminal Runtime deletion."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, job.agent_id)
            if agent is None:
                raise RuntimeError("Decommissioning Agent is missing")
            now = datetime.datetime.now(datetime.UTC)
            await self.external_channel_lifecycle_service.cleanup_decommissioned_agent(
                session,
                agent_id=job.agent_id,
                now=now,
            )
            await self.exchange_file_repository.expire_unbound_by_agent_id(
                session,
                agent_id=job.agent_id,
                expired_at=now,
            )
            files = await self.exchange_file_repository.list_unbound_by_agent_id(
                session,
                agent_id=job.agent_id,
            )
            runtime = await self.runtime_repository.get_by_agent_id(
                session,
                job.agent_id,
            )
            if runtime is not None and runtime.runtime_provider_id is not None:
                await self.runtime_repository.request_terminal_delete(
                    session,
                    runtime.id,
                )
            owned = await self.decommission_repository.set_status(
                session,
                job_id=job.id,
                lease_owner=lease_owner,
                status=AgentDecommissionStatus.FINALIZING,
                now=now,
            )
            if not owned:
                raise RuntimeError("Agent decommission lease was lost")
            await session.commit()

        for file in files:
            if file.blob_deleted_at is not None:
                continue
            await self.s3_service.delete(
                bucket=self.config.workspace_s3.bucket,
                key=file.object_key,
            )
            async with self.session_manager() as session:
                await self.exchange_file_repository.mark_blob_deleted(
                    session,
                    file_id=file.id,
                    blob_deleted_at=datetime.datetime.now(datetime.UTC),
                )

        if agent.avatar is not None:
            await self.avatar_handler.delete_files(
                agent.avatar,
                self.s3_service,
                self.config.workspace_s3.bucket,
            )

        async with self.session_manager() as session:
            await self.exchange_file_repository.delete_unbound_expired_by_agent_id(
                session,
                agent_id=job.agent_id,
            )
            runtime = await self.runtime_repository.get_by_agent_id(
                session,
                job.agent_id,
            )
            if runtime is not None and runtime.runtime_provider_id is not None:
                acknowledged = (
                    await self.runtime_repository.get_terminal_delete_acknowledged(
                        session,
                        runtime.id,
                    )
                )
                if acknowledged is None:
                    raise RuntimeError(
                        "AgentRuntime terminal deletion acknowledgement is pending"
                    )

    async def _set_status(
        self,
        *,
        job_id: str,
        lease_owner: str,
        status: AgentDecommissionStatus,
    ) -> None:
        """Persist an owned job phase or surface a lost lease."""
        async with self.session_manager() as session:
            updated = await self.decommission_repository.set_status(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                status=status,
                now=datetime.datetime.now(datetime.UTC),
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
        async with self.session_manager() as session:
            await self.decommission_repository.mark_retry(
                session,
                job_id=job.id,
                lease_owner=lease_owner,
                next_attempt_at=now + delay,
                error_kind=error_kind,
                error_summary=error_summary,
                now=now,
            )
