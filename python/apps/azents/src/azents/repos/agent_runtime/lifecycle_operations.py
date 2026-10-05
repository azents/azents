"""Completed Agent Runtime lifecycle reads and atomic commands."""

import dataclasses
from typing import Annotated

from azcommon.datetime import tznow
from fastapi import Depends

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
)
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime, AgentRuntimeLifecycleCommand
from azents.repos.agent_runtime_removal import AgentRuntimeRemovalRepository
from azents.repos.agent_runtime_removal.data import AgentRuntimeRemovalOperation
from azents.repos.agent_runtime_removal_scope import AgentRuntimeRemovalScopeRepository
from azents.repos.agent_runtime_removal_scope.data import AgentRuntimeRemovalImpact
from azents.repos.runtime_profile.data import (
    RuntimeConfigurationAppliedSlot,
    RuntimeConfigurationSlot,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)


@dataclasses.dataclass(frozen=True)
class AgentRuntimeReadState:
    """Detached Runtime and removal evidence from one completed read."""

    runtime: AgentRuntime | None
    active_removal: AgentRuntimeRemovalOperation | None
    completed_removal: AgentRuntimeRemovalOperation | None
    removal_impact: AgentRuntimeRemovalImpact | None


@dataclasses.dataclass(frozen=True)
class RuntimeRetainedConfiguration:
    """Retained desired and applied configuration with no live session."""

    runtime: AgentRuntime
    desired: RuntimeConfigurationSlot
    applied: RuntimeConfigurationAppliedSlot | None


@dataclasses.dataclass(frozen=True)
class RuntimeRetainedTarget:
    """Agent capability and configuration from the same retained read scope."""

    agent: Agent | None
    configuration: RuntimeRetainedConfiguration | None


@dataclasses.dataclass(frozen=True)
class RuntimeLifecycleCommandResult:
    """Command result plus exact Provider connection rejection."""

    command: AgentRuntimeLifecycleCommand | None
    provider_disconnected: bool


@dataclasses.dataclass
class AgentRuntimeLifecycleOperationsRepository:
    """Own lifecycle database scopes without changing their mutation fences."""

    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_admin_repository: Annotated[
        AgentAdminRepository, Depends(AgentAdminRepository)
    ]
    removal_repository: Annotated[
        AgentRuntimeRemovalRepository, Depends(AgentRuntimeRemovalRepository)
    ]
    removal_scope_repository: Annotated[
        AgentRuntimeRemovalScopeRepository, Depends(AgentRuntimeRemovalScopeRepository)
    ]
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    runtime_profile_repository: Annotated[
        RuntimeProfileRepository, Depends(RuntimeProfileRepository)
    ]
    runtime_provider_control_repository: Annotated[
        RuntimeProviderControlRepository, Depends(RuntimeProviderControlRepository)
    ]

    async def get_agent(self, agent_id: str) -> Agent | None:
        """Complete the original ordinary Agent observation."""
        async with self.session_manager() as session:
            return await self.agent_repository.get_by_id(session, agent_id)

    async def is_admin(self, agent_id: str, workspace_user_id: str) -> bool:
        """Complete one exact settings-management membership read."""
        async with self.session_manager() as session:
            return await self.agent_admin_repository.is_admin(
                session, agent_id, workspace_user_id
            )

    async def set_current_desired_state(
        self,
        *,
        runtime_id: str,
        command_type: RuntimeLifecycleCommandType,
        desired_state: RuntimeDesiredState,
        expected_configuration_sequence: int,
        expected_digest: str,
        expected_generation: int,
        reset_final_desired_state: RuntimeDesiredState | None,
    ) -> AgentRuntimeLifecycleCommand | None:
        """Preserve configuration and lifecycle CAS in one completed mutation."""
        runtime_repository = self.runtime_repository
        async with self.session_manager() as session:
            return await runtime_repository.set_desired_state_if_configuration_current(
                session,
                runtime_id,
                command_type,
                desired_state,
                expected_configuration_sequence=expected_configuration_sequence,
                expected_digest=expected_digest,
                expected_generation=expected_generation,
                reset_final_desired_state=reset_final_desired_state,
            )

    async def request_terminal_delete(self, agent_id: str) -> AgentRuntime | None:
        """Read and request deletion atomically for one logical Runtime."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_agent_id(session, agent_id)
            if runtime is None:
                return None
            return await self.runtime_repository.request_terminal_delete(
                session, runtime.id
            )

    async def lifecycle_command(
        self,
        *,
        runtime_id: str,
        command_type: RuntimeLifecycleCommandType,
        desired_state: RuntimeDesiredState,
        provider_id: str | None,
        expected_configuration_sequence: int,
        expected_digest: str | None,
        expected_generation: int,
    ) -> RuntimeLifecycleCommandResult:
        """Group connection acceptance and exact command mutation as before."""
        runtime_repository = self.runtime_repository
        connection_repository = self.runtime_provider_control_repository
        async with self.session_manager() as session:
            if command_type is RuntimeLifecycleCommandType.STOP:
                command = await self.runtime_repository.set_desired_state(
                    session, runtime_id, command_type, desired_state
                )
            else:
                assert provider_id is not None
                assert expected_digest is not None
                provider_connected = (
                    await connection_repository.has_connected_connection(
                        session, provider_id=provider_id, now=tznow()
                    )
                )
                if not provider_connected:
                    return RuntimeLifecycleCommandResult(
                        command=None, provider_disconnected=True
                    )
                command = (
                    await runtime_repository.set_desired_state_if_configuration_current(
                        session,
                        runtime_id,
                        command_type,
                        desired_state,
                        expected_configuration_sequence=expected_configuration_sequence,
                        expected_digest=expected_digest,
                        expected_generation=expected_generation,
                    )
                )
            return RuntimeLifecycleCommandResult(
                command=command, provider_disconnected=False
            )

    async def read_state(
        self, agent: Agent, *, can_manage: bool
    ) -> AgentRuntimeReadState:
        """Complete the existing Runtime/removal/impact projection snapshot."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_agent_id(session, agent.id)
            active = await self.removal_repository.get_active_by_agent_id(
                session, agent.id
            )
            completed = (
                None
                if active is not None
                else await self.removal_repository.get_latest_completed_by_agent_id(
                    session, agent.id
                )
            )
            removal = active or completed
            if not can_manage:
                impact = None
            elif removal is not None:
                impact = AgentRuntimeRemovalImpact(
                    active_root_session_count=removal.active_root_session_count,
                    active_subagent_count=removal.active_subagent_count,
                    active_run_count=removal.active_run_count,
                    queued_runtime_action_count=removal.queued_runtime_action_count,
                )
            elif agent.runtime_capability is AgentRuntimeCapability.MANAGED:
                impact = await self.removal_scope_repository.get_impact(
                    session, agent_id=agent.id
                )
            else:
                impact = None
            return AgentRuntimeReadState(
                runtime=runtime,
                active_removal=active,
                completed_removal=completed,
                removal_impact=impact,
            )

    async def read_lifecycle(self, agent_id: str) -> AgentRuntimeReadState:
        """Complete only the Runtime and active-removal lifecycle observations."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_agent_id(session, agent_id)
            active = await self.removal_repository.get_active_by_agent_id(
                session, agent_id
            )
            return AgentRuntimeReadState(
                runtime=runtime,
                active_removal=active,
                completed_removal=None,
                removal_impact=None,
            )

    async def retained_configuration(
        self, agent_id: str
    ) -> RuntimeRetainedConfiguration | None:
        """Read existing configuration without reconciliation."""
        async with self.session_manager() as session:
            return await self._read_configuration(session, agent_id)

    async def retained_target(self, agent_id: str) -> RuntimeRetainedTarget:
        """Read capability and retained configuration through the original RO scope."""
        async with self.read_session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            configuration = (
                await self._read_configuration(session, agent_id)
                if agent is not None
                and agent.lifecycle_status is AgentLifecycleStatus.ACTIVE
                and agent.runtime_capability is AgentRuntimeCapability.MANAGED
                else None
            )
            return RuntimeRetainedTarget(agent=agent, configuration=configuration)

    async def _read_configuration(
        self, session: ReadSession, agent_id: str
    ) -> RuntimeRetainedConfiguration | None:
        runtime = await self.runtime_repository.get_by_agent_id(session, agent_id)
        if runtime is None:
            return None
        state = await self.runtime_profile_repository.get_configuration_state(
            session, runtime_id=runtime.id
        )
        if state is None:
            return None
        return RuntimeRetainedConfiguration(
            runtime=runtime, desired=state.desired, applied=state.applied
        )
