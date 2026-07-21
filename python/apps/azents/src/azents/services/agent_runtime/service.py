"""Agent Runtime service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentType,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    RuntimeSummary,
    WorkspaceUserRole,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import (
    AgentRuntime,
    AgentRuntimeActions,
    AgentRuntimeFailureSummary,
    AgentRuntimeSummaryState,
)

from .lifecycle_data import (
    AgentAccessDenied,
    AgentNotBelongToWorkspace,
    AgentNotFound,
    AgentRuntimeLifecycleOutput,
    AgentRuntimeOutput,
    InvalidResetFinalDesiredState,
    ProviderDisconnected,
    RuntimeNotFound,
)


def _get_runtime_default_provider_id(
    config: Annotated[Config, Depends(get_config)],
) -> str | None:
    """Agent Runtime default Provider ID DI."""
    return config.runtime.default_provider_id


@dataclasses.dataclass
class AgentRuntimeService:
    """Agent Runtime lifecycle service."""

    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_admin_repository: Annotated[
        AgentAdminRepository, Depends(AgentAdminRepository)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    runtime_default_provider_id: Annotated[
        str | None,
        Depends(_get_runtime_default_provider_id),
    ]

    async def get(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentRuntimeOutput,
        AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied,
    ]:
        """Fetch Runtime status by Agent."""
        access_error = await self._authorize_agent(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        if access_error is not None:
            return Failure(access_error)

        async with self.session_manager() as session:
            runtime = await self._ensure_runtime_for_agent(session, agent_id)
        return Success(self._build_output(runtime))

    async def start(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentRuntimeLifecycleOutput,
        AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied | RuntimeNotFound,
    ]:
        """Store Runtime start desired state."""
        return await self._set_lifecycle_command(
            agent_id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )

    async def stop(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentRuntimeLifecycleOutput,
        AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied | RuntimeNotFound,
    ]:
        """Store Runtime stop desired state."""
        return await self._set_lifecycle_command(
            agent_id,
            RuntimeLifecycleCommandType.STOP,
            RuntimeDesiredState.STOPPED,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )

    async def restart(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentRuntimeLifecycleOutput,
        AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied | RuntimeNotFound,
    ]:
        """Store Runtime restart command and final running desired state."""
        return await self._set_lifecycle_command(
            agent_id,
            RuntimeLifecycleCommandType.RESTART,
            RuntimeDesiredState.RUNNING,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )

    async def reset(
        self,
        agent_id: str,
        *,
        final_desired_state: RuntimeDesiredState,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentRuntimeLifecycleOutput,
        AgentNotFound
        | AgentNotBelongToWorkspace
        | AgentAccessDenied
        | RuntimeNotFound
        | ProviderDisconnected
        | InvalidResetFinalDesiredState,
    ]:
        """Store Runtime reset command and desired state after reset."""
        if final_desired_state not in {
            RuntimeDesiredState.RUNNING,
            RuntimeDesiredState.STOPPED,
        }:
            return Failure(
                InvalidResetFinalDesiredState(final_desired_state=final_desired_state)
            )

        access_error = await self._authorize_agent(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        if access_error is not None:
            return Failure(access_error)

        async with self.session_manager() as session:
            runtime = await self._ensure_runtime_for_agent(session, agent_id)
            if (
                runtime.provider_connection_state
                == RuntimeProviderConnectionState.DISCONNECTED
            ):
                return Failure(ProviderDisconnected(runtime_id=runtime.id))
            command = await self.runtime_repository.set_desired_state(
                session,
                runtime.id,
                RuntimeLifecycleCommandType.RESET,
                final_desired_state,
                reset_final_desired_state=final_desired_state,
            )
        if command is None:
            return Failure(RuntimeNotFound(runtime_id=runtime.id))
        return Success(
            AgentRuntimeLifecycleOutput(
                runtime=command.runtime,
                state=self.calculate_state(command.runtime),
                command_type=command.command_type,
                desired_generation=command.desired_generation,
            )
        )

    async def observe(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentRuntimeOutput,
        AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied,
    ]:
        """Return current read model for Runtime observe request."""
        return await self.get(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )

    async def _set_lifecycle_command(
        self,
        agent_id: str,
        command_type: RuntimeLifecycleCommandType,
        desired_state: RuntimeDesiredState,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentRuntimeLifecycleOutput,
        AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied | RuntimeNotFound,
    ]:
        """Common lifecycle command storage logic."""
        access_error = await self._authorize_agent(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        if access_error is not None:
            return Failure(access_error)

        async with self.session_manager() as session:
            runtime = await self._ensure_runtime_for_agent(session, agent_id)
            command = await self.runtime_repository.set_desired_state(
                session,
                runtime.id,
                command_type,
                desired_state,
            )
        if command is None:
            return Failure(RuntimeNotFound(runtime_id=runtime.id))
        return Success(
            AgentRuntimeLifecycleOutput(
                runtime=command.runtime,
                state=self.calculate_state(command.runtime),
                command_type=command.command_type,
                desired_generation=command.desired_generation,
            )
        )

    async def _authorize_agent(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied | None:
        """Check Agent Runtime access permission."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
        if agent is None or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE:
            return AgentNotFound(agent_id=agent_id)
        if agent.workspace_id != workspace_id:
            return AgentNotBelongToWorkspace(agent_id=agent_id)
        if agent.type == AgentType.PRIVATE and role != WorkspaceUserRole.OWNER:
            async with self.session_manager() as session:
                is_admin = await self.agent_admin_repository.is_admin(
                    session, agent_id, workspace_user_id
                )
            if not is_admin:
                return AgentAccessDenied(agent_id=agent_id)
        return None

    async def _ensure_runtime_for_agent(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> AgentRuntime:
        """Ensure Agent Runtime and apply specified default provider."""
        return await self.runtime_repository.ensure_for_agent(
            session,
            agent_id,
            default_runtime_provider_id=self.runtime_default_provider_id,
        )

    def _build_output(self, runtime: AgentRuntime) -> AgentRuntimeOutput:
        """Combine Runtime raw state and summary."""
        return AgentRuntimeOutput(
            runtime=runtime,
            state=self.calculate_state(runtime),
        )

    def calculate_state(self, runtime: AgentRuntime) -> AgentRuntimeSummaryState:
        """Calculate summary/actions from Runtime raw axes."""
        current_failure = self._get_current_failure(runtime)
        if current_failure is not None:
            summary = RuntimeSummary.FAILED
        elif runtime.provider_observed_state == RuntimeProviderObservedState.FAILED:
            summary = RuntimeSummary.FAILED
        elif self._provider_action_blocked(runtime):
            summary = RuntimeSummary.PROVIDER_DISCONNECTED
        else:
            match runtime.provider_observed_state:
                case RuntimeProviderObservedState.STARTING:
                    summary = RuntimeSummary.STARTING
                case RuntimeProviderObservedState.STOPPING:
                    summary = RuntimeSummary.STOPPING
                case RuntimeProviderObservedState.RESETTING:
                    summary = RuntimeSummary.RESETTING
                case RuntimeProviderObservedState.RECOVERING:
                    summary = RuntimeSummary.RECOVERING
                case RuntimeProviderObservedState.RUNNING:
                    if runtime.runner_state in {
                        RuntimeRunnerState.READY,
                        RuntimeRunnerState.DEGRADED,
                    }:
                        summary = RuntimeSummary.RUNNING
                    else:
                        summary = RuntimeSummary.RUNNER_UNAVAILABLE
                case RuntimeProviderObservedState.STOPPED:
                    summary = (
                        RuntimeSummary.STARTING
                        if runtime.desired_state == RuntimeDesiredState.RUNNING
                        else RuntimeSummary.STOPPED
                    )
                case RuntimeProviderObservedState.UNKNOWN:
                    summary = (
                        RuntimeSummary.STARTING
                        if runtime.desired_state == RuntimeDesiredState.RUNNING
                        else RuntimeSummary.STOPPED
                    )
                case _:
                    assert_never(runtime.provider_observed_state)

        return AgentRuntimeSummaryState(
            summary=summary,
            actions=self._calculate_actions(runtime),
            failure=current_failure,
        )

    def _calculate_actions(self, runtime: AgentRuntime) -> AgentRuntimeActions:
        """Calculate action availability from Runtime raw axes."""
        if runtime.terminal_delete_requested_generation is not None:
            return AgentRuntimeActions(
                start=False,
                stop=False,
                restart=False,
                reset=False,
                use_runner=False,
            )
        backend_running = (
            runtime.provider_observed_state == RuntimeProviderObservedState.RUNNING
        )
        desired_running = runtime.desired_state == RuntimeDesiredState.RUNNING
        provider_connected = (
            runtime.provider_connection_state
            == RuntimeProviderConnectionState.CONNECTED
        )
        use_runner = (
            backend_running and runtime.runner_state == RuntimeRunnerState.READY
        )
        return AgentRuntimeActions(
            start=not desired_running or self._get_current_failure(runtime) is not None,
            stop=desired_running or backend_running,
            restart=desired_running or backend_running,
            reset=provider_connected,
            use_runner=use_runner,
        )

    def _provider_action_blocked(self, runtime: AgentRuntime) -> bool:
        """Check whether desired transition was blocked by Provider disconnection."""
        if (
            runtime.provider_connection_state
            == RuntimeProviderConnectionState.CONNECTED
        ):
            return False
        if runtime.desired_state == RuntimeDesiredState.RUNNING:
            return (
                runtime.provider_observed_state != RuntimeProviderObservedState.RUNNING
            )
        return runtime.provider_observed_state not in {
            RuntimeProviderObservedState.STOPPED,
            RuntimeProviderObservedState.UNKNOWN,
        }

    def _get_current_failure(
        self, runtime: AgentRuntime
    ) -> AgentRuntimeFailureSummary | None:
        """Return only failure for current desired generation."""
        if runtime.failure_generation != runtime.desired_generation:
            return None
        failure_generation = runtime.failure_generation
        if failure_generation is None:
            return None
        if runtime.failure_code is None or runtime.failure_message is None:
            return None
        return AgentRuntimeFailureSummary(
            generation=failure_generation,
            code=runtime.failure_code,
            message=runtime.failure_message,
        )
