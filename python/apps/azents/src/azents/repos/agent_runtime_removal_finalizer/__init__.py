"""Atomic Agent Runtime removal finalization repository."""

import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRuntimeCapability,
    AgentRuntimeRemovalStage,
    AgentRuntimeRemovalStatus,
    RuntimeTerminalDeleteAcknowledgementKind,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_runtime_removal import (
    RDBAgentRuntimeRemovalOperation,
)
from azents.rdb.models.runtime_profile import RDBRuntimeConfigurationState
from azents.repos.agent_runtime_removal_scope import (
    AgentRuntimeRemovalScopeRepository,
)


class AgentRuntimeRemovalFinalizerRepository:
    """Finalize Runtime removal while preserving the Agent and retained state."""

    def __init__(
        self,
        scope_repository: Annotated[
            AgentRuntimeRemovalScopeRepository,
            Depends(AgentRuntimeRemovalScopeRepository),
        ],
    ) -> None:
        """Initialize finalization dependencies."""
        self.scope_repository = scope_repository

    async def finalize(
        self,
        session: AsyncSession,
        *,
        operation_id: str,
        lease_owner: str,
        now: datetime.datetime,
    ) -> bool:
        """Commit `removing → none` and complete its operation atomically."""
        operation = await session.scalar(
            sa.select(RDBAgentRuntimeRemovalOperation)
            .where(
                RDBAgentRuntimeRemovalOperation.id == operation_id,
                RDBAgentRuntimeRemovalOperation.status
                == AgentRuntimeRemovalStatus.RUNNING,
                RDBAgentRuntimeRemovalOperation.stage
                == AgentRuntimeRemovalStage.FINALIZING,
                RDBAgentRuntimeRemovalOperation.lease_owner == lease_owner,
            )
            .with_for_update()
        )
        if operation is None:
            return False
        if (
            operation.product_cleanup_completed_at is None
            or operation.physical_deletion_required is None
        ):
            raise RuntimeError("Runtime removal evidence is incomplete")

        agent = await session.scalar(
            sa.select(RDBAgent)
            .where(
                RDBAgent.id == operation.agent_id,
                RDBAgent.workspace_id == operation.workspace_id,
                RDBAgent.runtime_capability == AgentRuntimeCapability.REMOVING,
                RDBAgent.runtime_capability_version
                == operation.committed_capability_version,
                RDBAgent.runtime_profile_id.is_(None),
                RDBAgent.shell_enabled.is_(False),
            )
            .with_for_update()
        )
        if agent is None:
            raise RuntimeError("Removing Agent state changed before finalization")

        await self.scope_repository.require_cleanup_complete(
            session,
            agent_id=operation.agent_id,
            agent_runtime_id=operation.agent_runtime_id,
        )
        runtime = await session.scalar(
            sa.select(RDBAgentRuntime)
            .where(RDBAgentRuntime.agent_id == operation.agent_id)
            .with_for_update()
        )
        self._require_physical_deletion(operation=operation, runtime=runtime)
        if runtime is not None:
            await session.execute(
                sa.delete(RDBRuntimeConfigurationState).where(
                    RDBRuntimeConfigurationState.runtime_id == runtime.id
                )
            )

        agent.runtime_capability = AgentRuntimeCapability.NONE
        agent.runtime_capability_version += 1
        agent.runtime_profile_id = None
        agent.shell_enabled = False
        agent.updated_at = now

        operation.status = AgentRuntimeRemovalStatus.COMPLETED
        operation.stage = AgentRuntimeRemovalStage.COMPLETED
        operation.lease_owner = None
        operation.lease_until = None
        operation.next_attempt_at = None
        operation.last_error_kind = None
        operation.last_error_summary = None
        operation.completed_at = now
        operation.updated_at = now
        await session.flush()
        return True

    def _require_physical_deletion(
        self,
        *,
        operation: RDBAgentRuntimeRemovalOperation,
        runtime: RDBAgentRuntime | None,
    ) -> None:
        """Require exact logical Runtime and terminal deletion evidence."""
        if operation.agent_runtime_id is None:
            if runtime is not None or operation.physical_deletion_required is not False:
                raise RuntimeError("Unexpected Runtime exists during finalization")
            return
        if runtime is None or runtime.id != operation.agent_runtime_id:
            raise RuntimeError("Removal target AgentRuntime is missing")
        if operation.physical_deletion_required is False:
            if not (
                runtime.terminal_delete_requested_generation
                == runtime.desired_generation
                and runtime.terminal_delete_acknowledged_generation
                == runtime.desired_generation
                and runtime.terminal_delete_acknowledgement_kind
                is RuntimeTerminalDeleteAcknowledgementKind.NO_PHYSICAL_BINDING
                and runtime.terminal_delete_acknowledged_at is not None
            ):
                raise RuntimeError("No-physical-binding deletion proof is missing")
            return
        target_generation = operation.target_terminal_delete_generation
        if not (
            target_generation is not None
            and runtime.desired_generation == target_generation
            and runtime.terminal_delete_requested_generation == target_generation
            and runtime.terminal_delete_acknowledged_generation == target_generation
            and runtime.terminal_delete_acknowledgement_kind
            is operation.physical_delete_acknowledgement_kind
            and runtime.terminal_delete_acknowledged_at
            == operation.physical_delete_acknowledged_at
            and operation.physical_delete_acknowledged_at is not None
        ):
            raise RuntimeError("Exact Runtime deletion acknowledgement is missing")
