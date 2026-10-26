"""Completed reads for frozen ordinary Runtime operation authority."""

import dataclasses
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    RuntimeDesiredState,
    RuntimeRunnerState,
)
from azents.core.runtime_admission import (
    RuntimeAdmissionAuthority,
    RuntimeAdmissionReady,
    RuntimeAdmissionRejected,
    RuntimeAdmissionState,
    RuntimeAdmissionWaiting,
)
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.runtime_profile import RDBRuntimeConfigurationState
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession


@dataclasses.dataclass
class RuntimeOperationAdmissionRepository:
    """Validate physical authority independently of connection availability."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def resolve(
        self, authority: RuntimeAdmissionAuthority
    ) -> RuntimeAdmissionState:
        """Return a detached rejection, transient wait, or current generation."""
        async with self.session_manager() as session:
            row = (
                await session.read_session.execute(
                    sa.select(RDBAgentRuntime, RDBAgent, RDBRuntimeConfigurationState)
                    .join(RDBAgent, RDBAgent.id == RDBAgentRuntime.agent_id)
                    .join(
                        RDBRuntimeConfigurationState,
                        RDBRuntimeConfigurationState.runtime_id == RDBAgentRuntime.id,
                    )
                    .where(RDBAgentRuntime.id == authority.runtime_id)
                )
            ).one_or_none()
            if row is None:
                return RuntimeAdmissionRejected()
            runtime, agent, configuration = row
            if (
                agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
                or agent.runtime_capability is not AgentRuntimeCapability.MANAGED
                or agent.runtime_capability_version != authority.capability_version
                or runtime.desired_state is not RuntimeDesiredState.RUNNING
                or runtime.desired_generation != authority.desired_generation
                or runtime.terminal_delete_requested_generation is not None
                or runtime.runner_state is RuntimeRunnerState.FAILED
                or configuration.applied_target_generation
                != authority.desired_generation
                or configuration.applied_sequence != authority.configuration_sequence
                or configuration.applied_digest != authority.configuration_digest
                or (
                    runtime.failure_generation == authority.desired_generation
                    and runtime.failure_code is not None
                )
            ):
                return RuntimeAdmissionRejected()
            if (
                runtime.runner_state is not RuntimeRunnerState.READY
                or runtime.runner_generation <= 0
                or runtime.workspace_path is None
            ):
                return RuntimeAdmissionWaiting()
            if runtime.workspace_path != authority.workspace_path:
                return RuntimeAdmissionRejected()
            return RuntimeAdmissionReady(runtime.runner_generation)
