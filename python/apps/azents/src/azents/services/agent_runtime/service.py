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
    WorkspaceUserRole,
)
from azents.core.runtime_profile import RuntimeConfigurationStateStatus
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
    AgentRuntimeLifecyclePresentation,
    AgentRuntimeLifecycleProvider,
    AgentRuntimeLifecycleRunner,
    AgentRuntimeLifecycleSnapshot,
    AgentRuntimeOutput,
    AgentRuntimePublicActions,
    AgentRuntimeReadOutput,
    AgentRuntimeRemovalOutput,
    AgentRuntimeRemovalProgress,
    InvalidResetFinalDesiredState,
    ProviderDisconnected,
    RuntimeAvailability,
    RuntimeLifecycleConvergence,
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
        "runtime_profile_required",
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
            assert resolution.desired.digest is not None
            if (
                runtime.provider_connection_state
                == RuntimeProviderConnectionState.DISCONNECTED
            ):
                return Failure(ProviderDisconnected(runtime_id=runtime.id))
            async with self.session_manager() as session:
                command = await (
                    self.runtime_repository.set_desired_state_if_configuration_current(
                        session,
                        runtime.id,
                        RuntimeLifecycleCommandType.RESET,
                        final_desired_state,
                        expected_configuration_sequence=resolution.desired.sequence,
                        expected_digest=resolution.desired.digest,
                        expected_generation=runtime.desired_generation,
                        reset_final_desired_state=final_desired_state,
                    )
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
        configuration = await self._configuration_status(resolution)
        return Success(
            AgentRuntimeLifecycleOutput(
                runtime=resolution.runtime,
                lifecycle=self.calculate_lifecycle(
                    resolution.runtime,
                    configuration=configuration,
                    removing=False,
                ),
                command_type=command.command_type,
                desired_generation=command.desired_generation,
                configuration=configuration,
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
        assert resolution.desired.digest is not None
        await self._require_runtime_operation_capability(
            agent_id,
            expected_version=capability_version,
        )
        async with self.session_manager() as session:
            command = await (
                self.runtime_repository.set_desired_state_if_configuration_current(
                    session,
                    runtime.id,
                    RuntimeLifecycleCommandType.START,
                    RuntimeDesiredState.RUNNING,
                    expected_configuration_sequence=resolution.desired.sequence,
                    expected_digest=resolution.desired.digest,
                    expected_generation=runtime.desired_generation,
                )
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
        expected_configuration_sequence: int | None = None
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
                expected_configuration_sequence = resolution.desired.sequence
            elif (
                runtime.desired_generation != expected_desired_generation
                or resolution.desired.sequence != expected_configuration_sequence
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
            last_resolution.applied is None
            or last_resolution.applied.sequence != last_resolution.desired.sequence
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
        desired = resolution.desired
        workspace_path = runtime.workspace_path
        assert workspace_path is not None
        assert desired.digest is not None
        return RuntimeOperationTarget(
            id=runtime.id,
            runtime_capability_version=runtime_capability_version,
            desired_generation=runtime.desired_generation,
            runner_generation=runtime.runner_generation,
            configuration_sequence=desired.sequence,
            configuration_digest=desired.digest,
            workspace_path=workspace_path,
        )

    @staticmethod
    def _operation_target_evidence_ready(
        resolution: RuntimeProfileResolutionResult,
    ) -> bool:
        """Return whether current Runtime evidence can support an operation."""
        runtime = resolution.runtime
        desired = resolution.desired
        applied = resolution.applied
        if (
            applied is None
            or desired.status is not RuntimeConfigurationStateStatus.READY
            or desired.document is None
            or applied.sequence != desired.sequence
            or desired.target_generation != runtime.desired_generation
            or desired.provider_reported_digest != desired.digest
            or desired.runner_reported_digest != desired.digest
            or desired.provider_acknowledged_at is None
            or desired.runner_observed_at is None
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
        desired = resolution.desired
        return (
            desired.sequence == expected_authority.configuration_sequence
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
            desired_document = resolution.desired.document
            desired_digest = resolution.desired.digest
            assert desired_document is not None
            assert desired_digest is not None

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
                        provider_id=desired_document.provider_id,
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
                command = await (
                    self.runtime_repository.set_desired_state_if_configuration_current(
                        session,
                        resolution.runtime.id,
                        command_type,
                        desired_state,
                        expected_configuration_sequence=resolution.desired.sequence,
                        expected_digest=desired_digest,
                        expected_generation=resolution.runtime.desired_generation,
                    )
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
        configuration = await self._configuration_status(resolution)
        return Success(
            AgentRuntimeLifecycleOutput(
                runtime=resolution.runtime,
                lifecycle=self.calculate_lifecycle(
                    resolution.runtime,
                    configuration=configuration,
                    removing=False,
                ),
                command_type=command.command_type,
                desired_generation=command.desired_generation,
                configuration=configuration,
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

        resolution = await self._get_existing_resolution(agent.id)
        configuration = (
            await self._configuration_status(resolution)
            if resolution is not None
            else None
        )
        lifecycle = (
            self.calculate_lifecycle(
                runtime,
                configuration=configuration,
                removing=active_removal is not None,
            )
            if runtime is not None
            else None
        )
        physical_actions = (
            self._calculate_lifecycle_actions(
                runtime,
                configuration=configuration,
                removing=active_removal is not None,
            )
            if runtime is not None
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
            lifecycle=lifecycle,
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

    async def get_lifecycle_snapshot(
        self,
        agent_id: str,
    ) -> AgentRuntimeLifecycleSnapshot:
        """Return the shared Runtime lifecycle snapshot without mutation."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_agent_id(session, agent_id)
            active_removal = await self.removal_repository.get_active_by_agent_id(
                session,
                agent_id,
            )
        resolution = await self._get_existing_resolution(agent_id)
        configuration = (
            await self._configuration_status(resolution)
            if resolution is not None
            else None
        )
        if runtime is None:
            return AgentRuntimeLifecycleSnapshot(
                runtime=None,
                lifecycle=None,
                actions=AgentRuntimeActions(
                    start=False,
                    stop=False,
                    restart=False,
                    reset=False,
                    use_runner=False,
                ),
            )
        return AgentRuntimeLifecycleSnapshot(
            runtime=runtime,
            lifecycle=self.calculate_lifecycle(
                runtime,
                configuration=configuration,
                removing=active_removal is not None,
            ),
            actions=self._calculate_lifecycle_actions(
                runtime,
                configuration=configuration,
                removing=active_removal is not None,
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
            if runtime is None:
                return None
            state = await self.runtime_profile_repository.get_configuration_state(
                session,
                runtime_id=runtime.id,
                for_update=False,
            )
            if state is None:
                return None
        return RuntimeProfileResolutionResult(
            runtime=runtime,
            desired=state.desired,
            applied=state.applied,
            runtime_created=False,
        )

    async def _build_output(
        self,
        resolution: RuntimeProfileResolutionResult,
    ) -> AgentRuntimeOutput:
        """Combine Runtime raw state and configuration summary."""
        configuration = await self._configuration_status(resolution)
        return AgentRuntimeOutput(
            runtime=resolution.runtime,
            lifecycle=self.calculate_lifecycle(
                resolution.runtime,
                configuration=configuration,
                removing=False,
            ),
            configuration=configuration,
        )

    async def _configuration_status(
        self,
        resolution: RuntimeProfileResolutionResult,
    ) -> AgentRuntimeConfigurationStatus:
        desired = resolution.desired
        applied = resolution.applied
        if desired.status is RuntimeConfigurationStateStatus.UNCONFIGURED:
            status = "profile_required"
        elif desired.status is RuntimeConfigurationStateStatus.BLOCKED:
            status = "configuration_blocked"
        elif applied is None:
            status = "configured_not_created"
        elif applied.sequence != desired.sequence:
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
        desired = resolution.desired
        if desired.status not in {
            RuntimeConfigurationStateStatus.BLOCKED,
            RuntimeConfigurationStateStatus.UNCONFIGURED,
        }:
            return None
        return RuntimeProviderUnavailable(
            code=desired.reason_code or "runtime_configuration_blocked",
            provider_id=resolution.runtime.runtime_provider_id,
            message="The selected Runtime Profile cannot create a Runtime.",
        )

    def calculate_lifecycle(
        self,
        runtime: AgentRuntime,
        *,
        configuration: AgentRuntimeConfigurationStatus | None,
        removing: bool,
    ) -> AgentRuntimeLifecyclePresentation:
        """Compose one precedence-ordered lifecycle presentation."""
        current_failure = self._get_current_failure(runtime)
        if removing or runtime.terminal_delete_requested_generation is not None:
            convergence = "stopping"
            availability = "removing"
            reason_code = "runtime_removal_in_progress"
        elif current_failure is not None:
            convergence = "failed"
            availability = "failed"
            reason_code = "runtime_failed"
        elif runtime.provider_observed_state is RuntimeProviderObservedState.FAILED:
            convergence = "failed"
            availability = "failed"
            reason_code = "provider_failed"
        elif configuration is not None and configuration.status in {
            "profile_required",
            "configuration_blocked",
            "waiting_for_recreation",
        }:
            convergence = "blocked"
            availability = "configuration_blocked"
            if configuration.status == "waiting_for_recreation":
                reason_code = "runtime_recreation_required"
            elif configuration.desired is not None:
                reason_code = self._safe_configuration_reason_code(
                    configuration.desired.reason_code
                )
            else:
                reason_code = "runtime_profile_required"
        elif self._provider_action_blocked(runtime):
            convergence = "blocked"
            availability = "provider_disconnected"
            reason_code = "provider_disconnected"
        else:
            convergence, availability, reason_code = self._lifecycle_convergence(
                runtime
            )

        return AgentRuntimeLifecyclePresentation(
            target=runtime.desired_state,
            convergence=convergence,
            provider=AgentRuntimeLifecycleProvider(
                connection=runtime.provider_connection_state,
                resource=runtime.provider_observed_state,
            ),
            runner=AgentRuntimeLifecycleRunner(state=runtime.runner_state),
            availability=availability,
            reason_code=reason_code,
            desired_generation=runtime.desired_generation,
        )

    @staticmethod
    def _lifecycle_convergence(
        runtime: AgentRuntime,
    ) -> tuple[RuntimeLifecycleConvergence, RuntimeAvailability, str | None]:
        """Derive lifecycle status after higher-precedence checks."""
        observed = runtime.provider_observed_state
        if runtime.desired_state is RuntimeDesiredState.STOPPED:
            if observed in {
                RuntimeProviderObservedState.STOPPED,
                RuntimeProviderObservedState.UNKNOWN,
            }:
                return "stable", "stopped", None
            if observed is RuntimeProviderObservedState.RESETTING:
                return "resetting", "transitioning", "runtime_resetting"
            return "stopping", "transitioning", "runtime_stopping"
        if observed is RuntimeProviderObservedState.RESETTING:
            return "resetting", "transitioning", "runtime_resetting"
        if observed is RuntimeProviderObservedState.RECOVERING:
            return "recovering", "transitioning", "runtime_recovering"
        if observed is not RuntimeProviderObservedState.RUNNING:
            return "starting", "transitioning", "runtime_starting"
        if runtime.runner_state is not RuntimeRunnerState.READY:
            reason_by_state = {
                RuntimeRunnerState.UNKNOWN: "runner_unknown",
                RuntimeRunnerState.DISCONNECTED: "runner_disconnected",
                RuntimeRunnerState.STARTING: "runner_starting",
                RuntimeRunnerState.DEGRADED: "runner_degraded",
                RuntimeRunnerState.FAILED: "runner_failed",
            }
            return (
                "stable",
                "runner_unavailable",
                reason_by_state[runtime.runner_state],
            )
        return "stable", "ready", None

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

    def _calculate_lifecycle_actions(
        self,
        runtime: AgentRuntime,
        *,
        configuration: AgentRuntimeConfigurationStatus | None,
        removing: bool,
    ) -> AgentRuntimeActions:
        """Apply shared removal and configuration guards to Runtime actions."""
        if removing:
            return AgentRuntimeActions(
                start=False,
                stop=False,
                restart=False,
                reset=False,
                use_runner=False,
            )
        actions = self._calculate_actions(runtime)
        creation_available = configuration is None or configuration.status not in {
            "profile_required",
            "configuration_blocked",
        }
        return AgentRuntimeActions(
            start=actions.start and creation_available,
            stop=actions.stop,
            restart=actions.restart and creation_available,
            reset=actions.reset and creation_available,
            use_runner=actions.use_runner and creation_available,
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
