"""Fenced Agent root deletion after registry-owned completion verification."""

import dataclasses
import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.agent_deletion import (
    AgentAvatarDeletionEvidence,
    AgentDeletionContext,
    AgentDeletionParticipantFailure,
    AgentDeletionRegistry,
    avatar_object_keys,
)
from azents.core.agent_deletion_registry import get_agent_deletion_registry
from azents.core.enums import AgentDecommissionStatus, AgentLifecycleStatus
from azents.core.upload_images import StoredImage
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_decommission import RDBAgentDecommissionJob
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_deletion_verification import AgentDeletionVerification


def _terminal_delete_pending(runtime: RDBAgentRuntime) -> bool:
    """Return whether a bound Runtime still requires terminal acknowledgement."""
    return runtime.runtime_provider_resource_id is not None and not (
        runtime.terminal_delete_requested_generation == runtime.desired_generation
        and runtime.terminal_delete_acknowledged_generation
        == runtime.desired_generation
    )


@dataclasses.dataclass
class AgentDecommissionFinalizerRepository:
    """Use one registry for completion obligations; retain native root authority."""

    registry: Annotated[AgentDeletionRegistry, Depends(get_agent_deletion_registry)]

    async def finalize(
        self,
        session: WriteSession,
        *,
        job_id: str,
        agent_id: str,
        lease_owner: str,
        expected_attempt: int,
        avatar_evidence: AgentAvatarDeletionEvidence,
        now: datetime.datetime,
    ) -> bool:
        """Commit verified root removal and its tombstone together."""
        job = await session.write_session.scalar(
            sa.select(RDBAgentDecommissionJob)
            .where(
                RDBAgentDecommissionJob.id == job_id,
                RDBAgentDecommissionJob.agent_id == agent_id,
                RDBAgentDecommissionJob.status == AgentDecommissionStatus.FINALIZING,
                RDBAgentDecommissionJob.lease_owner == lease_owner,
                RDBAgentDecommissionJob.attempt_count == expected_attempt,
            )
            .with_for_update()
        )
        if job is None:
            return False
        agent = await session.write_session.scalar(
            sa.select(RDBAgent)
            .where(
                RDBAgent.id == agent_id,
                RDBAgent.workspace_id == job.workspace_id,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.DECOMMISSIONING,
            )
            .with_for_update()
        )
        if agent is None:
            raise RuntimeError("Decommissioning Agent is missing")
        context = AgentDeletionContext(
            job_id=job_id,
            agent_id=agent_id,
            workspace_id=agent.workspace_id,
            lease_owner=lease_owner,
            expected_attempt=expected_attempt,
        )
        current_avatar = (
            StoredImage.model_validate(agent.avatar) if agent.avatar else None
        )
        if (
            avatar_evidence.context != context
            or avatar_evidence.keys != avatar_object_keys(current_avatar)
        ):
            raise AgentDeletionParticipantFailure(
                participant_key="agent.avatar",
                phase="verify",
                error=RuntimeError(
                    "Current avatar does not match this attempt's deletion evidence"
                ),
            )

        await AgentDeletionVerification(self.registry).require_complete(
            session, context=context
        )
        runtime = await session.write_session.scalar(
            sa.select(RDBAgentRuntime)
            .where(RDBAgentRuntime.agent_id == agent_id)
            .with_for_update()
        )
        if runtime is not None:
            if _terminal_delete_pending(runtime):
                raise AgentDeletionParticipantFailure(
                    participant_key="agent.runtime",
                    phase="verify",
                    error=RuntimeError(
                        "AgentRuntime terminal deletion is not acknowledged"
                    ),
                )
            await session.write_session.delete(runtime)
            await session.write_session.flush()

        # Only declared database children cascade; required roots were checked above.
        await session.write_session.delete(agent)
        job.status = AgentDecommissionStatus.COMPLETED
        job.lease_owner = None
        job.lease_until = None
        job.next_attempt_at = None
        job.failure_boundary_key = None
        job.last_error_kind = None
        job.last_error_summary = None
        job.completed_at = now
        job.updated_at = now
        await session.write_session.flush()
        return True
