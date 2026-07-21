"""Agent decommission finalization repository."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentDecommissionStatus, AgentLifecycleStatus
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_admin import RDBAgentAdmin
from azents.rdb.models.agent_decommission import RDBAgentDecommissionJob
from azents.rdb.models.agent_project_catalog import RDBAgentProjectCatalogEntry
from azents.rdb.models.agent_project_default import RDBAgentProjectDefault
from azents.rdb.models.agent_project_preset import RDBAgentProjectPreset
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.artifact import RDBArtifact
from azents.rdb.models.exchange_file import RDBExchangeFile
from azents.rdb.models.memory import RDBAgentMemory
from azents.rdb.models.model_file import RDBModelFile
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.models.toolkit import RDBAgentToolkit
from azents.rdb.models.toolkit_state import RDBToolkitState


class AgentDecommissionFinalizerRepository:
    """Finalize Agent resources only after lifecycle roots are absent."""

    async def finalize(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        agent_id: str,
        lease_owner: str,
        now: datetime.datetime,
    ) -> bool:
        """Delete verified Agent-owned rows and complete its job tombstone."""
        job = await session.scalar(
            sa.select(RDBAgentDecommissionJob)
            .where(
                RDBAgentDecommissionJob.id == job_id,
                RDBAgentDecommissionJob.agent_id == agent_id,
                RDBAgentDecommissionJob.status == AgentDecommissionStatus.FINALIZING,
                RDBAgentDecommissionJob.lease_owner == lease_owner,
            )
            .with_for_update()
        )
        if job is None:
            return False

        agent = await session.scalar(
            sa.select(RDBAgent)
            .where(
                RDBAgent.id == agent_id,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.DECOMMISSIONING,
            )
            .with_for_update()
        )
        if agent is None:
            raise RuntimeError("Decommissioning Agent is missing")

        await self._require_absent_lifecycle_roots(session, agent_id=agent_id)

        runtime = await session.scalar(
            sa.select(RDBAgentRuntime)
            .where(RDBAgentRuntime.agent_id == agent_id)
            .with_for_update()
        )
        if runtime is not None:
            acknowledged = (
                runtime.terminal_delete_requested_generation
                == runtime.desired_generation
                and runtime.terminal_delete_acknowledged_generation
                == runtime.desired_generation
            )
            if runtime.runtime_provider_id is not None and not acknowledged:
                raise RuntimeError("AgentRuntime terminal deletion is not acknowledged")
            await session.delete(runtime)

        for model in (
            RDBAgentAdmin,
            RDBAgentProjectCatalogEntry,
            RDBAgentProjectDefault,
            RDBAgentProjectPreset,
            RDBAgentToolkit,
            RDBAgentMemory,
        ):
            await session.execute(sa.delete(model).where(model.agent_id == agent_id))

        await session.delete(agent)
        job.status = AgentDecommissionStatus.COMPLETED
        job.lease_owner = None
        job.lease_until = None
        job.next_attempt_at = None
        job.last_error_kind = None
        job.last_error_summary = None
        job.completed_at = now
        job.updated_at = now
        await session.flush()
        return True

    async def _require_absent_lifecycle_roots(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> None:
        """Reject finalization while lifecycle-owned resources still remain."""
        remaining = (
            (RDBAgentSession, "AgentSession"),
            (RDBArtifact, "Artifact"),
            (RDBExchangeFile, "ExchangeFile"),
            (RDBModelFile, "ModelFile"),
            (RDBSessionAgentContext, "SessionAgentContext"),
            (RDBToolkitState, "ToolkitState"),
        )
        for model, label in remaining:
            exists = await session.scalar(
                sa.select(sa.exists().where(model.agent_id == agent_id))
            )
            if exists:
                raise RuntimeError(f"{label} lifecycle root remains")
