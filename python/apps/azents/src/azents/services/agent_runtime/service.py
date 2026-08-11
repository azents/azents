"""Agent Runtime service."""

import asyncio
import dataclasses
import time
from typing import Annotated, assert_never

from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentType,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    RuntimeSummary,
    WorkspaceUserRole,
)
from azents.core.runtime_profile import RuntimeConfigurationResolutionStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import (
    AgentRuntime,
    AgentRuntimeActions,
    AgentRuntimeFailureSummary,
    AgentRuntimeSummaryState,
)
from azents.repos.agent_runtime_removal import AgentRuntimeRemovalRepository
from azents.repos.agent_runtime_removal.data import AgentRuntimeRemovalOperation
from azents.repos.agent_runtime_removal_scope import (
    AgentRuntimeRemovalScopeRepository,
)
from azents.repos.agent_runtime_removal_scope.data import AgentRuntimeRemovalImpact
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.services.agent_runtime_removal import AgentRuntimeRemovalService
from azents.services.agent_runtime_removal.data import (
    AgentRuntimeRemovalConfirmationRequest,
    AgentRuntimeRemovalUnavailable,
)
from azents.services.agent_runtime_transition.data import (
    AgentRuntimeAdditionRequest,
    AgentRuntimeAdditionUnavailable,
)
from azents.services.agent_runtime_transition.service import (
    AgentRuntimeTransitionService,
)
from azents.services.runtime_profile_resolution.data import (
    RuntimeProfileResolutionResult,
    RuntimeProfileResolutionUnavailable,
)
from azents.services.runtime_profile_resolution.service import (
    RuntimeProfileResolutionService,
)
from azents.services.runtime_profile_workspace.service import (
    RuntimeProfileWorkspaceService,
    RuntimeProfileWorkspaceUnavailable,
)
from azents.services.runtime_storage_error import RuntimeStorageError

from .lifecycle_data import (
    AgentAccessDenied,
    AgentManagementAccessDenied,
    AgentNotBelongToWorkspace,
    AgentNotFound,
    AgentRuntimeActionUnavailable,
    AgentRuntimeAdditionOutput,
    AgentRuntimeConfigurationStatus,
    AgentRuntimeLifecycleOutput,
    AgentRuntimeOutput,
    AgentRuntimePublicActions,
    AgentRuntimeReadOutput,
    AgentRuntimeRemovalOutput,
    AgentRuntimeRemovalProgress,
    InvalidResetFinalDesiredState,
    ProviderDisconnected,
    RuntimeNotFound,
    RuntimeOperationAuthority,
    RuntimeOperationTarget,
    RuntimeProfileConfigurationStatus,
    RuntimeProviderUnavailable,
)

_RUNTIME_OPERATION_WAIT_TIMEOUT_SECONDS = 120.0
_RUNTIME_OPERATION_POLL_INTERVAL_SECONDS = 1.0
_SAFE_RUNTIME_CONFIGURATION_REASON_CODES = frozenset(
    {
        "provider_disabled",
        "provider_workspace_unavailable",
        "provider_disconnected",
        "provider_capability_unavailable",
        "provider_capability_invalid",
        "profile_document_invalid",
        "profile_incompatible",
        "runtime_configuration_blocked",
    }
)


@dataclasses.dataclass(frozen=True)
class _AuthorizedAgent:
    """Authorized Agent and contextual settings-management capability."""

    agent: Agent
    can_manage: bool


@dataclasses.dataclass(frozen=True)
class _RuntimeProfileProjection:
    """Compact Runtime Profile status for public read models."""

    status: RuntimeProfileConfigurationStatus
    available: bool
    reason_code: str | None


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
    removal_repository: Annotated[
        AgentRuntimeRemovalRepository,
        Depends(AgentRuntimeRemovalRepository),
    ]
    removal_scope_repository: Annotated[
        AgentRuntimeRemovalScopeRepository,
        Depends(AgentRuntimeRemovalScopeRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    runtime_profile_resolution_service: Annotated[
        RuntimeProfileResolutionService,
        Depends(),
    ]
    runtime_profile_workspace_service: Annotated[
        RuntimeProfileWorkspaceService,
        Depends(RuntimeProfileWorkspaceService),
    ]
    runtime_profile_repository: Annotated[
        RuntimeProfileRepository,
        Depends(RuntimeProfileRepository),
    ]
    runtime_provider_control_repository: Annotated[
        RuntimeProviderControlRepository,
        Depends(RuntimeProviderControlRepository),
    ]
    transition_service: Annotated[
        AgentRuntimeTransitionService,
        Depends(AgentRuntimeTransitionService),
    ]
    removal_service: Annotated[
        AgentRuntimeRemovalService,
        Depends(AgentRuntimeRemovalService),
    ]

    async def get(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentRuntimeReadOutput,
        AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied,
    ]:
        """Fetch the unified read-only Runtime model by Agent."""
        access = await self._get_authorized_agent(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        if isinstance(
            access,
            AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied,
        ):
            return Failure(access)
        return Success(
            await self._build_read_output(
                access.agent,
                can_manage=access.can_manage,
            )
        )

    async def add(
        self,
        agent_id: str,
        *,
        workspace_runtime_profile_id: str,
        expected_capability_version: int,
        expected_runtime_profile_selection_version: int,
        idempotency_key: str,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentRuntimeAdditionOutput,
        AgentNotFound
        | AgentNotBelongToWorkspace
        | AgentAccessDenied
        | AgentManagementAccessDenied
        | AgentRuntimeActionUnavailable,
    ]:
        """Commit or replay one dedicated Runtime addition."""
        access = await self._get_authorized_agent(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        if isinstance(
            access,
            AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied,
        ):
            return Failure(access)
        if not access.can_manage:
            return Failure(AgentManagementAccessDenied(agent_id=agent_id))
        try:
            added = await self.transition_service.add_runtime(
                AgentRuntimeAdditionRequest(
                    agent_id=agent_id,
                    workspace_runtime_profile_id=workspace_runtime_profile_id,
                    expected_capability_version=expected_capability_version,
                    expected_runtime_profile_selection_version=(
                        expected_runtime_profile_selection_version
                    ),
                    idempotency_key=idempotency_key,
                )
            )
        except AgentRuntimeAdditionUnavailable as error:
            return Failure(
                AgentRuntimeActionUnavailable(
                    code=error.code,
                    message=str(error),
                )
            )
        return Success(
            AgentRuntimeAdditionOutput(
                runtime=await self._build_read_output(
                    added.agent,
                    can_manage=True,
                ),
                replayed=added.replayed,
            )
        )

    async def remove(
        self,
        agent_id: str,
        *,
        expected_capability_version: int,
        expected_runtime_profile_selection_version: int,
        idempotency_key: str,
        confirmed: bool,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentRuntimeRemovalOutput,
        AgentNotFound
        | AgentNotBelongToWorkspace
        | AgentAccessDenied
        | AgentManagementAccessDenied
        | AgentRuntimeActionUnavailable,
    ]:
        """Commit or replay one irreversible Runtime removal."""
        access = await self._get_authorized_agent(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        if isinstance(
            access,
            AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied,
        ):
            return Failure(access)
        if not access.can_manage:
            return Failure(AgentManagementAccessDenied(agent_id=agent_id))
        if not confirmed:
            return Failure(
                AgentRuntimeActionUnavailable(
                    code="runtime_remove_confirmation_required",
                    message=(
                        "Final destructive Runtime removal confirmation is required."
                    ),
                )
            )
        try:
            removed = await self.removal_service.confirm(
                AgentRuntimeRemovalConfirmationRequest(
                    agent_id=agent_id,
                    workspace_id=workspace_id,
                    requested_by_workspace_user_id=workspace_user_id,
                    idempotency_key=idempotency_key,
                    expected_capability_version=expected_capability_version,
                    expected_runtime_profile_selection_version=(
                        expected_runtime_profile_selection_version
                    ),
                )
            )
        except AgentRuntimeRemovalUnavailable as error:
            return Failure(
                AgentRuntimeActionUnavailable(
                    code=error.code,
                    message=error.message,
                )
            )
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
        if agent is None:
            return Failure(AgentNotFound(agent_id=agent_id))
        return Success(
            AgentRuntimeRemovalOutput(
                runtime=await self._build_read_output(
                    agent,
                    can_manage=True,
                ),
                replayed=removed.replayed,
            )
        )

    async def start(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentRuntimeLifecycleOutput,
        AgentNotFound
        | AgentNotBelongToWorkspace
        | AgentAccessDenied
        | RuntimeNotFound
        | RuntimeProviderUnavailable,
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
        AgentNotFound
        | AgentNotBelongToWorkspace
        | AgentAccessDenied
        | RuntimeNotFound
        | RuntimeProviderUnavailable,
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
        AgentNotFound
        | AgentNotBelongToWorkspace
        | AgentAccessDenied
        | RuntimeNotFound
        | RuntimeProviderUnavailable,
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
        | RuntimeProviderUnavailable
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

        try:
            resolution = await self._ensure_runtime_for_agent(agent_id)
            runtime = resolution.runtime
            blocked = self.configuration_blocking_error(resolution)
            if blocked is not None:
                return Failure(blocked)
            if (
                runtime.provider_connection_state
                == RuntimeProviderConnectionState.DISCONNECTED
            ):
                return Failure(ProviderDisconnected(runtime_id=runtime.id))
            async with self.session_manager() as session:
                command = await self.runtime_repository.set_desired_state_if_ready(
                    session,
                    runtime.id,
                    RuntimeLifecycleCommandType.RESET,
                    final_desired_state,
                    expected_configuration_revision_id=(resolution.desired_revision.id),
                    reset_final_desired_state=final_desired_state,
                )
            if command is None:
                return Failure(
                    RuntimeProviderUnavailable(
                        code="runtime_configuration_changed",
                        provider_id=runtime.runtime_provider_id,
                        message=(
                            "Runtime configuration changed before reset "
                            "could be stored."
                        ),
                    )
                )
            resolution = await self._ensure_runtime_for_agent(agent_id)
        except RuntimeProfileResolutionUnavailable as error:
            return Failure(
                RuntimeProviderUnavailable(
                    code=error.code,
                    provider_id=error.provider_id,
                    message=error.message,
                )
            )
        return Success(
            AgentRuntimeLifecycleOutput(
                runtime=resolution.runtime,
                state=self.calculate_state(resolution.runtime),
                command_type=command.command_type,
                desired_generation=command.desired_generation,
                configuration=await self._configuration_status(resolution),
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
        AgentRuntimeReadOutput,
        AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied,
    ]:
        """Return current read model for Runtime observe request."""
        return await self.get(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )

    async def ensure_started_for_agent(self, agent_id: str) -> AgentRuntime:
        """Ensure an internal Runtime consumer has targeted the current Profile."""
        capability_version = await self._require_runtime_operation_capability(agent_id)
        resolution = await self._ensure_runtime_for_agent(agent_id)
        runtime = resolution.runtime
        if runtime.desired_state is RuntimeDesiredState.RUNNING:
            return runtime
        blocked = self.configuration_blocking_error(resolution)
        if blocked is not None:
            raise RuntimeProfileResolutionUnavailable(
                code=blocked.code,
                provider_id=blocked.provider_id,
                message=blocked.message,
            )
        await self._require_runtime_operation_capability(
            agent_id,
            expected_version=capability_version,
        )
        async with self.session_manager() as session:
            command = await self.runtime_repository.set_desired_state_if_ready(
                session,
                runtime.id,
                RuntimeLifecycleCommandType.START,
                RuntimeDesiredState.RUNNING,
                expected_configuration_revision_id=resolution.desired_revision.id,
            )
        if command is None:
            raise RuntimeProfileResolutionUnavailable(
                code="runtime_configuration_changed",
                provider_id=runtime.runtime_provider_id,
                message=("Runtime configuration changed before start could be stored."),
            )
        return (await self._ensure_runtime_for_agent(agent_id)).runtime

    async def resolve_operation_target(
        self,
        agent_id: str,
        *,
        wait_timeout_seconds: float = _RUNTIME_OPERATION_WAIT_TIMEOUT_SECONDS,
        poll_interval_seconds: float = _RUNTIME_OPERATION_POLL_INTERVAL_SECONDS,
        expected_authority: RuntimeOperationAuthority | None = None,
        start_if_stopped: bool = True,
    ) -> RuntimeOperationTarget:
        """Wait for the exact desired configuration and qualified Runner."""
        capability_version = await self._require_runtime_operation_capability(agent_id)
        deadline = time.monotonic() + max(wait_timeout_seconds, 0.0)
        last_resolution: RuntimeProfileResolutionResult | None = None
        expected_desired_generation: int | None = None
        expected_revision_id: str | None = None
        while True:
            await self._require_runtime_operation_capability(
                agent_id,
                expected_version=capability_version,
            )
            try:
                resolution = await self._ensure_runtime_for_agent(agent_id)
            except RuntimeProfileResolutionUnavailable as error:
                raise RuntimeStorageError(
                    f"Runtime Profile is unavailable: {error.code}"
                ) from error
            last_resolution = resolution
            if expected_authority is not None and not self._matches_expected_authority(
                resolution,
                expected_authority,
            ):
                raise RuntimeStorageError(
                    "Runtime configuration changed since the operation context "
                    "was assembled."
                )
            blocked = self.configuration_blocking_error(resolution)
            if blocked is not None:
                raise RuntimeStorageError(
                    f"Runtime Profile is unavailable: {blocked.code}"
                )
            runtime = resolution.runtime
            if runtime.desired_state is not RuntimeDesiredState.RUNNING:
                if not start_if_stopped:
                    raise RuntimeStorageError("Runtime is not running.")
                try:
                    await self._require_runtime_operation_capability(
                        agent_id,
                        expected_version=capability_version,
                    )
                    await self.ensure_started_for_agent(agent_id)
                except RuntimeProfileResolutionUnavailable as error:
                    raise RuntimeStorageError(
                        f"Runtime Profile is unavailable: {error.code}"
                    ) from error
                resolution = await self._ensure_runtime_for_agent(agent_id)
                last_resolution = resolution
                blocked = self.configuration_blocking_error(resolution)
                if blocked is not None:
                    raise RuntimeStorageError(
                        f"Runtime Profile is unavailable: {blocked.code}"
                    )
                runtime = resolution.runtime
                if (
                    expected_authority is not None
                    and not self._matches_expected_authority(
                        resolution, expected_authority
                    )
                ):
                    raise RuntimeStorageError(
                        "Runtime configuration changed since the operation context "
                        "was assembled."
                    )
            if expected_desired_generation is None:
                expected_desired_generation = runtime.desired_generation
                expected_revision_id = resolution.desired_revision.id
            elif (
                runtime.desired_generation != expected_desired_generation
                or resolution.desired_revision.id != expected_revision_id
            ):
                raise RuntimeStorageError(
                    "Runtime configuration changed while waiting for the operation."
                )
            if (
                runtime.failure_generation == runtime.desired_generation
                and runtime.failure_code is not None
            ):
                detail = runtime.failure_message or runtime.failure_code
                raise RuntimeStorageError(f"Runtime failed: {detail}")
            if runtime.provider_observed_state is RuntimeProviderObservedState.FAILED:
                detail = runtime.failure_message or runtime.failure_code
                message = "Runtime failed"
                if detail:
                    message = f"{message}: {detail}"
                raise RuntimeStorageError(message)
            target = self._qualified_operation_target(
                resolution,
                runtime_capability_version=capability_version,
            )
            if target is not None:
                await self._require_runtime_operation_capability(
                    agent_id,
                    expected_version=capability_version,
                )
                return target
            remaining_wait_seconds = deadline - time.monotonic()
            if remaining_wait_seconds <= 0:
                break
            await asyncio.sleep(
                min(max(poll_interval_seconds, 0.0), remaining_wait_seconds)
            )
        if last_resolution is None:
            raise RuntimeStorageError("Runtime is not running")
        if (
            last_resolution.runtime.provider_connection_state
            is RuntimeProviderConnectionState.DISCONNECTED
        ):
            raise RuntimeStorageError(
                "Runtime Provider is disconnected. Please try again in a moment."
            )
        if (
            last_resolution.applied_revision is None
            or last_resolution.applied_revision.id
            != last_resolution.desired_revision.id
        ):
            raise RuntimeStorageError(
                "Runtime is still applying the selected Runtime Profile."
            )
        if (
            last_resolution.runtime.provider_observed_state
            is not RuntimeProviderObservedState.RUNNING
            or last_resolution.runtime.provider_observed_generation
            != last_resolution.runtime.desired_generation
        ):
            raise RuntimeStorageError(
                "Runtime is still starting. Please try again in a moment."
            )
        raise RuntimeStorageError("Runtime runner is not ready")

    @staticmethod
    def _qualified_operation_target(
        resolution: RuntimeProfileResolutionResult,
        *,
        runtime_capability_version: int,
    ) -> RuntimeOperationTarget | None:
        """Return exact operation authority only from complete current evidence."""
        if not AgentRuntimeService._operation_target_evidence_ready(resolution):
            return None
        runtime = resolution.runtime
        desired = resolution.desired_revision
        workspace_path = runtime.workspace_path
        assert workspace_path is not None
        return RuntimeOperationTarget(
            id=runtime.id,
            runtime_capability_version=runtime_capability_version,
            desired_generation=runtime.desired_generation,
            runner_generation=runtime.runner_generation,
            configuration_revision_id=desired.id,
            configuration_digest=desired.digest,
            workspace_path=workspace_path,
        )

    @staticmethod
    def _operation_target_evidence_ready(
        resolution: RuntimeProfileResolutionResult,
    ) -> bool:
        """Return whether current Runtime evidence can support an operation."""
        runtime = resolution.runtime
        desired = resolution.desired_revision
        applied = resolution.applied_revision
        if (
            applied is None
            or applied.id != desired.id
            or desired.target_desired_generation != runtime.desired_generation
            or desired.provider_reported_digest != desired.digest
            or desired.runner_reported_digest != desired.digest
            or desired.provider_acknowledged_at is None
            or desired.runtime_observed_at is None
            or runtime.desired_state is not RuntimeDesiredState.RUNNING
            or runtime.provider_observed_state
            is not RuntimeProviderObservedState.RUNNING
            or runtime.provider_observed_generation != runtime.desired_generation
            or runtime.provider_connection_state
            is not RuntimeProviderConnectionState.CONNECTED
            or (
                runtime.failure_generation == runtime.desired_generation
                and runtime.failure_code is not None
            )
            or runtime.runner_state is not RuntimeRunnerState.READY
            or runtime.runner_generation <= 0
            or runtime.workspace_path is None
        ):
            return False
        return True

    async def _require_runtime_operation_capability(
        self,
        agent_id: str,
        *,
        expected_version: int | None = None,
    ) -> int:
        """Require one current managed Agent capability before Runtime work."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
        if (
            agent is None
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            or agent.runtime_capability is not AgentRuntimeCapability.MANAGED
        ):
            raise RuntimeStorageError("Agent Runtime capability is unavailable.")
        if (
            expected_version is not None
            and agent.runtime_capability_version != expected_version
        ):
            raise RuntimeStorageError(
                "Agent Runtime capability changed during the operation."
            )
        return agent.runtime_capability_version

    @staticmethod
    def _matches_expected_authority(
        resolution: RuntimeProfileResolutionResult,
        expected_authority: RuntimeOperationAuthority,
    ) -> bool:
        """Check that a resolution still matches the prompt-selected authority."""
        runtime = resolution.runtime
        desired = resolution.desired_revision
        return (
            desired.id == expected_authority.configuration_revision_id
            and desired.digest == expected_authority.configuration_digest
            and runtime.desired_generation == expected_authority.desired_generation
        )

    async def request_terminal_delete_for_agent(
        self,
        agent_id: str,
    ) -> AgentRuntime | None:
        """Request idempotent terminal deletion without requiring ready sources."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_agent_id(session, agent_id)
            if runtime is None:
                return None
            return await self.runtime_repository.request_terminal_delete(
                session,
                runtime.id,
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
        AgentNotFound
        | AgentNotBelongToWorkspace
        | AgentAccessDenied
        | RuntimeNotFound
        | RuntimeProviderUnavailable,
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

        try:
            resolution = await self._ensure_runtime_for_agent(agent_id)
        except RuntimeProfileResolutionUnavailable as error:
            if command_type is not RuntimeLifecycleCommandType.STOP:
                return Failure(
                    RuntimeProviderUnavailable(
                        code=error.code,
                        provider_id=error.provider_id,
                        message=error.message,
                    )
                )
            existing = await self._get_existing_resolution(agent_id)
            if existing is None:
                return Failure(
                    RuntimeProviderUnavailable(
                        code=error.code,
                        provider_id=error.provider_id,
                        message=error.message,
                    )
                )
            resolution = existing

        if command_type is not RuntimeLifecycleCommandType.STOP:
            blocked = self.configuration_blocking_error(resolution)
            if blocked is not None:
                return Failure(blocked)

        async with self.session_manager() as session:
            if command_type is RuntimeLifecycleCommandType.STOP:
                command = await self.runtime_repository.set_desired_state(
                    session,
                    resolution.runtime.id,
                    command_type,
                    desired_state,
                )
            else:
                provider_connected = await (
                    self.runtime_provider_control_repository.has_connected_connection(
                        session,
                        provider_id=resolution.desired_revision.provider_id,
                        now=tznow(),
                        for_update=True,
                    )
                )
                if not provider_connected:
                    return Failure(
                        RuntimeProviderUnavailable(
                            code="provider_disconnected",
                            provider_id=resolution.runtime.runtime_provider_id,
                            message="Runtime Provider is disconnected.",
                        )
                    )
                command = await self.runtime_repository.set_desired_state_if_ready(
                    session,
                    resolution.runtime.id,
                    command_type,
                    desired_state,
                    expected_configuration_revision_id=(resolution.desired_revision.id),
                )
        if command is None:
            if command_type is RuntimeLifecycleCommandType.STOP:
                return Failure(RuntimeNotFound(runtime_id=resolution.runtime.id))
            return Failure(
                RuntimeProviderUnavailable(
                    code="runtime_configuration_changed",
                    provider_id=resolution.runtime.runtime_provider_id,
                    message=(
                        "Runtime configuration changed before the lifecycle "
                        "command could be stored."
                    ),
                )
            )
        try:
            resolution = await self._ensure_runtime_for_agent(agent_id)
        except RuntimeProfileResolutionUnavailable as error:
            if command_type is not RuntimeLifecycleCommandType.STOP:
                return Failure(
                    RuntimeProviderUnavailable(
                        code=error.code,
                        provider_id=error.provider_id,
                        message=error.message,
                    )
                )
            existing = await self._get_existing_resolution(agent_id)
            if existing is None:
                return Failure(RuntimeNotFound(runtime_id=command.runtime.id))
            resolution = existing
        return Success(
            AgentRuntimeLifecycleOutput(
                runtime=resolution.runtime,
                state=self.calculate_state(resolution.runtime),
                command_type=command.command_type,
                desired_generation=command.desired_generation,
                configuration=await self._configuration_status(resolution),
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
        access = await self._get_authorized_agent(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        match access:
            case _AuthorizedAgent():
                return None
            case AgentNotFound() | AgentNotBelongToWorkspace() | AgentAccessDenied():
                return access
            case _:
                assert_never(access)

    async def _get_authorized_agent(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> (
        _AuthorizedAgent | AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied
    ):
        """Load one visible Agent and derive settings-management authority."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
        if agent is None or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE:
            return AgentNotFound(agent_id=agent_id)
        if agent.workspace_id != workspace_id:
            return AgentNotBelongToWorkspace(agent_id=agent_id)
        can_manage = role is WorkspaceUserRole.OWNER
        if not can_manage:
            async with self.session_manager() as session:
                can_manage = await self.agent_admin_repository.is_admin(
                    session, agent_id, workspace_user_id
                )
        if agent.type is AgentType.PRIVATE and not can_manage:
            return AgentAccessDenied(agent_id=agent_id)
        return _AuthorizedAgent(agent=agent, can_manage=can_manage)

    async def _build_read_output(
        self,
        agent: Agent,
        *,
        can_manage: bool,
    ) -> AgentRuntimeReadOutput:
        """Build the unified Runtime projection without ensuring any Runtime."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_agent_id(session, agent.id)
            active_removal = await self.removal_repository.get_active_by_agent_id(
                session,
                agent.id,
            )
            completed_removal = (
                None
                if active_removal is not None
                else await self.removal_repository.get_latest_completed_by_agent_id(
                    session,
                    agent.id,
                )
            )
            removal = active_removal or completed_removal
            if not can_manage:
                removal_impact = None
            elif removal is not None:
                removal_impact = self._removal_impact_from_operation(removal)
            elif agent.runtime_capability is AgentRuntimeCapability.MANAGED:
                removal_impact = await self.removal_scope_repository.get_impact(
                    session,
                    agent_id=agent.id,
                )
            else:
                removal_impact = None

        runtime_profile = await self._runtime_profile_projection(agent)

        state = self.calculate_state(runtime) if runtime is not None else None
        resolution = await self._get_existing_resolution(agent.id)
        configuration = (
            await self._configuration_status(resolution)
            if resolution is not None
            else None
        )
        physical_actions = (
            state.actions
            if state is not None
            and agent.runtime_capability is AgentRuntimeCapability.MANAGED
            else AgentRuntimeActions(
                start=False,
                stop=False,
                restart=False,
                reset=False,
                use_runner=False,
            )
        )
        add_available = (
            can_manage
            and agent.runtime_capability is AgentRuntimeCapability.NONE
            and active_removal is None
            and (
                runtime is None
                or self.transition_service.completed_removal_authorizes_rearm(
                    completed_removal,
                    runtime,
                )
            )
        )
        profile_actions_available = runtime_profile.status == "configured"
        return AgentRuntimeReadOutput(
            capability=agent.runtime_capability,
            capability_version=agent.runtime_capability_version,
            runtime_profile_id=agent.runtime_profile_id,
            runtime_profile_selection_version=(agent.runtime_profile_selection_version),
            runtime_profile_status=runtime_profile.status,
            runtime_profile_available=runtime_profile.available,
            runtime_profile_availability_reason_code=runtime_profile.reason_code,
            removal_impact=removal_impact,
            removal=(
                self._removal_progress_from_operation(removal)
                if removal is not None
                else None
            ),
            runtime=runtime,
            state=state,
            configuration=configuration,
            actions=AgentRuntimePublicActions(
                add=add_available,
                remove=(
                    can_manage
                    and agent.runtime_capability is AgentRuntimeCapability.MANAGED
                    and active_removal is None
                ),
                start=(
                    (physical_actions.start and profile_actions_available)
                    or (
                        agent.runtime_capability is AgentRuntimeCapability.MANAGED
                        and runtime is None
                        and profile_actions_available
                    )
                ),
                stop=physical_actions.stop,
                restart=(physical_actions.restart and profile_actions_available),
                reset=physical_actions.reset and profile_actions_available,
                observe=(
                    agent.runtime_capability is AgentRuntimeCapability.MANAGED
                    and runtime is not None
                ),
                use_runner=(physical_actions.use_runner and profile_actions_available),
            ),
        )

    async def _runtime_profile_projection(
        self,
        agent: Agent,
    ) -> _RuntimeProfileProjection:
        """Project current Profile configuration without resolving Runtime state."""
        if agent.runtime_capability is not AgentRuntimeCapability.MANAGED:
            return _RuntimeProfileProjection(
                status="not_applicable",
                available=False,
                reason_code=None,
            )
        if agent.runtime_profile_id is None:
            return _RuntimeProfileProjection(
                status="profile_required",
                available=False,
                reason_code="runtime_profile_unconfigured",
            )
        try:
            projection = await self.runtime_profile_workspace_service.get_profile(
                agent.workspace_id,
                agent.runtime_profile_id,
            )
        except RuntimeProfileWorkspaceUnavailable as error:
            return _RuntimeProfileProjection(
                status="unavailable",
                available=False,
                reason_code=error.code,
            )
        if projection.available:
            return _RuntimeProfileProjection(
                status="configured",
                available=True,
                reason_code=None,
            )
        return _RuntimeProfileProjection(
            status="unavailable",
            available=False,
            reason_code=projection.reason_code,
        )

    @staticmethod
    def _removal_impact_from_operation(
        operation: AgentRuntimeRemovalOperation,
    ) -> AgentRuntimeRemovalImpact:
        """Project immutable privacy-safe impact from a removal operation."""
        return AgentRuntimeRemovalImpact(
            active_root_session_count=operation.active_root_session_count,
            active_subagent_count=operation.active_subagent_count,
            active_run_count=operation.active_run_count,
            queued_runtime_action_count=operation.queued_runtime_action_count,
        )

    @staticmethod
    def _removal_progress_from_operation(
        operation: AgentRuntimeRemovalOperation,
    ) -> AgentRuntimeRemovalProgress:
        """Project bounded removal progress without internal authority fields."""
        return AgentRuntimeRemovalProgress(
            id=operation.id,
            status=operation.status,
            stage=operation.stage,
            confirmed_at=operation.confirmed_at,
            cleanup_scanned_context_count=operation.cleanup_scanned_context_count,
            cleanup_invalidated_context_count=(
                operation.cleanup_invalidated_context_count
            ),
            product_cleanup_completed_at=operation.product_cleanup_completed_at,
            physical_deletion_required=operation.physical_deletion_required,
            physical_delete_requested_at=operation.physical_delete_requested_at,
            physical_delete_acknowledgement_kind=(
                operation.physical_delete_acknowledgement_kind
            ),
            physical_delete_acknowledged_at=(operation.physical_delete_acknowledged_at),
            attempt_count=operation.attempt_count,
            next_attempt_at=operation.next_attempt_at,
            last_error_kind=operation.last_error_kind,
            last_error_summary=operation.last_error_summary,
            started_at=operation.started_at,
            completed_at=operation.completed_at,
            updated_at=operation.updated_at,
        )

    async def _ensure_runtime_for_agent(
        self, agent_id: str
    ) -> RuntimeProfileResolutionResult:
        """Ensure Agent Runtime through exact Workspace Runtime Profile selection."""
        return await self.runtime_profile_resolution_service.ensure_for_agent(agent_id)

    async def _get_existing_resolution(
        self,
        agent_id: str,
    ) -> RuntimeProfileResolutionResult | None:
        """Load retained configuration evidence without resolving new sources."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_agent_id(session, agent_id)
            if (
                runtime is None
                or runtime.desired_runtime_configuration_revision_id is None
            ):
                return None
            desired = await self.runtime_profile_repository.get_configuration_revision(
                session,
                revision_id=runtime.desired_runtime_configuration_revision_id,
            )
            if desired is None:
                return None
            applied = None
            if runtime.applied_runtime_configuration_revision_id is not None:
                applied = (
                    await self.runtime_profile_repository.get_configuration_revision(
                        session,
                        revision_id=(runtime.applied_runtime_configuration_revision_id),
                    )
                )
        return RuntimeProfileResolutionResult(
            runtime=runtime,
            desired_revision=desired,
            applied_revision=applied,
            runtime_created=False,
        )

    async def _build_output(
        self,
        resolution: RuntimeProfileResolutionResult,
    ) -> AgentRuntimeOutput:
        """Combine Runtime raw state and configuration summary."""
        return AgentRuntimeOutput(
            runtime=resolution.runtime,
            state=self.calculate_state(resolution.runtime),
            configuration=await self._configuration_status(resolution),
        )

    async def _configuration_status(
        self,
        resolution: RuntimeProfileResolutionResult,
    ) -> AgentRuntimeConfigurationStatus:
        desired = resolution.desired_revision
        applied = resolution.applied_revision
        if desired.resolution_status.value == "blocked":
            status = "configuration_blocked"
        elif applied is None:
            status = "configured_not_created"
        elif applied.id != desired.id:
            status = "waiting_for_recreation"
        else:
            status = "applied"
        return AgentRuntimeConfigurationStatus(
            status=status,
            desired=desired,
            applied=applied,
        )

    @staticmethod
    def _safe_configuration_reason_code(reason_code: str | None) -> str:
        """Return only bounded reason codes in user-facing projections."""
        if reason_code in _SAFE_RUNTIME_CONFIGURATION_REASON_CODES:
            return reason_code
        return "runtime_configuration_blocked"

    @staticmethod
    def configuration_blocking_error(
        resolution: RuntimeProfileResolutionResult,
    ) -> RuntimeProviderUnavailable | None:
        """Reject creation commands when current exact sources are blocked."""
        desired = resolution.desired_revision
        if (
            desired.resolution_status
            is not RuntimeConfigurationResolutionStatus.BLOCKED
        ):
            return None
        return RuntimeProviderUnavailable(
            code=desired.reason_code or "runtime_configuration_blocked",
            provider_id=resolution.runtime.runtime_provider_id,
            message="The selected Runtime Profile cannot create a Runtime.",
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
