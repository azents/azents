"""Independently executable Agent cleanup participants and ordered coordination."""

import asyncio
import dataclasses
from collections.abc import Sequence
from typing import Protocol

from azcommon.infra.s3.service import S3Service

from azents.broker.types import SessionStopSignal
from azents.core.agent_deletion import (
    AgentAvatarDeletionEvidence,
    AgentDeletionOwnershipLost,
    AgentDeletionParticipantFailure,
    AgentDeletionRegistry,
    AgentDeletionWaitReason,
    avatar_object_keys,
)
from azents.core.config import Config, require_workspace_s3_bucket
from azents.core.enums import AgentDecommissionStatus, AgentSessionStatus
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.repos.agent_decommission.data import AgentDecommissionJob
from azents.repos.agent_decommission_operations import (
    AgentDecommissionOperationsRepository,
)
from azents.repos.agent_deletion_fence import deletion_context
from azents.services.uploads.handlers.avatar import AvatarUploadHandler


class DeletionBroker(Protocol):
    async def send_message(self, signal: SessionStopSignal) -> None: ...


class DeletionRuntime(Protocol):
    async def request_terminal_delete_for_agent(
        self, agent_id: str
    ) -> object | None: ...


class DeletionChannelEffects(Protocol):
    async def consume_archive_cleanup(
        self, plans: Sequence[ProviderEffectPlan]
    ) -> int: ...


@dataclasses.dataclass
class AgentDeletionExecution:
    """Attempt-local evidence; never a substitute for final database predicates."""

    job: AgentDecommissionJob
    lease_owner: str
    avatar_evidence: AgentAvatarDeletionEvidence | None
    wait_reason: AgentDeletionWaitReason | None
    completed: bool


class AgentDeletionParticipant(Protocol):
    @property
    def key(self) -> str: ...

    async def run(self, execution: AgentDeletionExecution) -> None: ...


@dataclasses.dataclass
class SessionRetirementParticipant:
    operations: AgentDecommissionOperationsRepository
    broker: DeletionBroker
    channels: DeletionChannelEffects

    key = "agent.sessions"

    async def retire_root(
        self, execution: AgentDeletionExecution, *, root_session_id: str
    ) -> bool:
        """Keep native archive transaction and post-commit effects separate."""
        result = await self.operations.retire_root_tree(
            job=execution.job,
            lease_owner=execution.lease_owner,
            root_session_id=root_session_id,
        )
        if result.archived:
            await self.channels.consume_archive_cleanup(result.cleanup_plans)
        for session_id in result.stop_session_ids:
            await self.broker.send_message(SessionStopSignal(session_id=session_id))
        return result.retired

    async def run(self, execution: AgentDeletionExecution) -> None:
        roots = await self.operations.list_roots(agent_id=execution.job.agent_id)
        if not roots:
            await self.operations.advance_status(
                job=execution.job,
                lease_owner=execution.lease_owner,
                status=AgentDecommissionStatus.FINALIZING,
            )
            return
        await self.operations.advance_status(
            job=execution.job,
            lease_owner=execution.lease_owner,
            status=AgentDecommissionStatus.RETIRING_SESSIONS,
        )
        waiting_for_active_run = False
        for root in roots:
            if root.status is AgentSessionStatus.ARCHIVED:
                continue
            if root.status is not AgentSessionStatus.ACTIVE:
                raise RuntimeError("Agent root Session has an unsupported status")
            retired = await self.retire_root(execution, root_session_id=root.id)
            waiting_for_active_run = waiting_for_active_run or not retired
        if waiting_for_active_run:
            execution.wait_reason = AgentDeletionWaitReason.ACTIVE_WORK
            return
        await self.operations.advance_status(
            job=execution.job,
            lease_owner=execution.lease_owner,
            status=AgentDecommissionStatus.WAITING_RETENTION,
        )
        execution.wait_reason = AgentDeletionWaitReason.RETENTION


@dataclasses.dataclass
class RuntimeDeletionParticipant:
    operations: AgentDecommissionOperationsRepository
    runtime: DeletionRuntime

    key = "agent.runtime"

    async def run(self, execution: AgentDeletionExecution) -> None:
        if await self.operations.runtime_bound(agent_id=execution.job.agent_id):
            await self.operations.require_owned(
                job=execution.job, lease_owner=execution.lease_owner
            )
            await self.runtime.request_terminal_delete_for_agent(execution.job.agent_id)


@dataclasses.dataclass
class ChannelDeletionParticipant:
    operations: AgentDecommissionOperationsRepository
    channels: DeletionChannelEffects

    key = "agent.channels"

    async def run(self, execution: AgentDeletionExecution) -> None:
        plans = await self.operations.cleanup_channels(
            job=execution.job, lease_owner=execution.lease_owner
        )
        # Canonical termination is required; remote presentation stays best-effort.
        await self.channels.consume_archive_cleanup(plans)


@dataclasses.dataclass
class FileDeletionParticipant:
    operations: AgentDecommissionOperationsRepository
    s3: S3Service
    config: Config

    key = "agent.files"

    async def run(self, execution: AgentDeletionExecution) -> None:
        files = await self.operations.prepare_files(
            job=execution.job, lease_owner=execution.lease_owner
        )
        for file in files:
            if file.blob_deleted_at is not None:
                continue
            await self.s3.delete(
                bucket=require_workspace_s3_bucket(self.config.workspace_s3),
                key=file.object_key,
            )
            await self.operations.mark_blob_deleted(
                job=execution.job,
                lease_owner=execution.lease_owner,
                file_id=file.id,
                object_key=file.object_key,
            )
        await self.operations.finish_files(
            job=execution.job, lease_owner=execution.lease_owner
        )


@dataclasses.dataclass
class AvatarDeletionParticipant:
    operations: AgentDecommissionOperationsRepository
    handler: AvatarUploadHandler
    s3: S3Service
    config: Config

    key = "agent.avatar"

    async def run(self, execution: AgentDeletionExecution) -> None:
        avatar = await self.operations.read_avatar(
            job=execution.job, lease_owner=execution.lease_owner
        )
        keys = avatar_object_keys(avatar)
        if avatar is not None:
            await self.handler.delete_files(
                avatar, self.s3, require_workspace_s3_bucket(self.config.workspace_s3)
            )
        execution.avatar_evidence = AgentAvatarDeletionEvidence(
            context=deletion_context(execution.job, lease_owner=execution.lease_owner),
            keys=keys,
        )


@dataclasses.dataclass
class DatabaseDeletionParticipant:
    operations: AgentDecommissionOperationsRepository

    key = "agent.database"

    async def run(self, execution: AgentDeletionExecution) -> None:
        if execution.avatar_evidence is None:
            raise RuntimeError("Agent deletion avatar evidence is missing")
        acknowledged = await self.operations.runtime_acknowledged(
            job=execution.job, lease_owner=execution.lease_owner
        )
        if not acknowledged:
            execution.wait_reason = AgentDeletionWaitReason.RUNTIME_ACKNOWLEDGEMENT
            return
        execution.completed = await self.operations.finalize(
            job=execution.job,
            lease_owner=execution.lease_owner,
            avatar_evidence=execution.avatar_evidence,
        )
        if not execution.completed:
            raise AgentDeletionOwnershipLost(
                "Agent decommission lease was lost before finalization"
            )


@dataclasses.dataclass
class AgentDeletionPipeline:
    registry: AgentDeletionRegistry
    participants: tuple[AgentDeletionParticipant, ...]
    operations: AgentDecommissionOperationsRepository

    async def advance(
        self, *, job: AgentDecommissionJob, lease_owner: str
    ) -> AgentDeletionExecution:
        """Validate full composition before executing any participant effects."""
        self.registry.require_handlers(
            participant.key for participant in self.participants
        )
        handlers = {participant.key: participant for participant in self.participants}
        execution = AgentDeletionExecution(job, lease_owner, None, None, False)
        for definition in self.registry.participants:
            try:
                await handlers[definition.key].run(execution)
            except asyncio.CancelledError:
                raise
            except AgentDeletionOwnershipLost, AgentDeletionParticipantFailure:
                raise
            except Exception as error:
                raise AgentDeletionParticipantFailure(
                    participant_key=definition.key, phase="cleanup", error=error
                ) from error
            if execution.wait_reason is not None:
                break
            if not execution.completed:
                await self.operations.clear_failure_boundary(
                    job=job,
                    lease_owner=lease_owner,
                    boundary_key=f"{definition.key}/cleanup",
                )
        return execution
