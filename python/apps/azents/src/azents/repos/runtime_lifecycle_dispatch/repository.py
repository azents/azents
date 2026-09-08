"""Database-only Runtime lifecycle dispatch composition."""

import dataclasses
from typing import Annotated

from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as RuntimeProviderCommandType,
)
from azents_runtime_control.runtime_configuration import (
    RuntimeConfigurationEnvelope,
    RuntimeConfigurationEvidence,
    canonical_runtime_configuration_json,
    parse_runtime_configuration_envelope,
)
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRuntimeCapability,
    RuntimeDesiredState,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
)
from azents.core.runtime_profile import RuntimeConfigurationStateStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime, AgentRuntimeFailurePatch
from azents.repos.runtime_profile.data import RuntimeConfigurationState
from azents.repos.runtime_profile.repository import RuntimeProfileRepository

from .data import (
    RuntimeLifecycleDispatchAdmission,
    RuntimeLifecycleDispatchAdmissionResult,
    RuntimeLifecycleDispatchPreflight,
    RuntimeLifecycleDispatchPreflightResult,
    RuntimeLifecycleDispatchRejection,
    RuntimeLifecycleDispatchRejectionReason,
    RuntimeLifecycleDispatchRequest,
    RuntimeLifecycleDispatchSnapshot,
)


@dataclasses.dataclass
class RuntimeLifecycleDispatchRepository:
    """Own complete database operations for one Runtime Provider dispatch."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    profile_repository: Annotated[
        RuntimeProfileRepository, Depends(RuntimeProfileRepository)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def preflight(
        self,
        request: RuntimeLifecycleDispatchRequest,
    ) -> RuntimeLifecycleDispatchPreflightResult:
        """Validate one selected Runtime without consuming its lifecycle claim."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.lock_by_id(
                session,
                request.runtime.agent_id,
            )
            if agent is None or not _runtime_dispatch_allowed(
                agent.runtime_capability,
                request.command_type,
            ):
                return _rejection(
                    RuntimeLifecycleDispatchRejectionReason.AGENT_CAPABILITY_CHANGED
                )
            current = await self.runtime_repository.get_by_id_for_update(
                session,
                request.runtime.id,
            )
            if not _runtime_dispatch_snapshot_matches(current, request.runtime):
                return _rejection(
                    RuntimeLifecycleDispatchRejectionReason.RUNTIME_SNAPSHOT_CHANGED
                )
            assert current is not None
            provider_id = current.runtime_provider_id
            if provider_id is None:
                failure_code = "PROVIDER_NOT_CONFIGURED"
                failure_message = "Agent Runtime has no configured Runtime Provider."
                await self.runtime_repository.record_runtime_failure(
                    session,
                    current.id,
                    AgentRuntimeFailurePatch(
                        generation=current.desired_generation,
                        code=failure_code,
                        message=failure_message,
                    ),
                )
                return RuntimeLifecycleDispatchRejection(
                    reason=(
                        RuntimeLifecycleDispatchRejectionReason.PROVIDER_NOT_CONFIGURED
                    ),
                    failure_code=failure_code,
                    failure_message=failure_message,
                )
            return _preflight(
                agent=agent,
                runtime=current,
                provider_id=provider_id,
                request=request,
            )

    async def claim(
        self,
        preflight: RuntimeLifecycleDispatchPreflight,
        *,
        connection_generation: int,
    ) -> RuntimeLifecycleDispatchAdmissionResult:
        """Revalidate, claim, and configure one live-connection dispatch."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.lock_by_id(
                session,
                preflight.agent_id,
            )
            if (
                agent is None
                or agent.runtime_capability is not preflight.agent_runtime_capability
                or agent.runtime_capability_version
                != preflight.agent_runtime_capability_version
                or not _runtime_dispatch_allowed(
                    agent.runtime_capability,
                    preflight.command_type,
                )
            ):
                return _rejection(
                    RuntimeLifecycleDispatchRejectionReason.AGENT_CAPABILITY_CHANGED
                )
            current = await self.runtime_repository.get_by_id_for_update(
                session,
                preflight.runtime_id,
            )
            if not _runtime_dispatch_preflight_matches(current, preflight):
                return _rejection(
                    RuntimeLifecycleDispatchRejectionReason.RUNTIME_SNAPSHOT_CHANGED
                )
            assert current is not None
            if (
                preflight.required_provider_generation is not None
                and connection_generation != preflight.required_provider_generation
            ):
                return _rejection(
                    RuntimeLifecycleDispatchRejectionReason.PROVIDER_GENERATION_CHANGED
                )
            state = await self.profile_repository.get_configuration_state(
                session,
                runtime_id=current.id,
            )
            if (
                preflight.required_observed_generation is not None
                or preflight.required_configuration_sequence is not None
            ) and not _current_network_policy_repair_target(
                current,
                state=state,
                provider_id=preflight.provider_id,
                provider_generation=preflight.required_provider_generation,
                observed_generation=preflight.required_observed_generation,
                configuration_sequence=preflight.required_configuration_sequence,
            ):
                return _rejection(
                    RuntimeLifecycleDispatchRejectionReason.REPAIR_TARGET_CHANGED
                )
            if preflight.claim_lifecycle:
                claimed = await self.runtime_repository.claim_lifecycle_dispatch(
                    session,
                    current.id,
                    current.desired_generation,
                    retry_delay=preflight.lifecycle_retry_delay,
                )
                if claimed is None:
                    return _rejection(
                        RuntimeLifecycleDispatchRejectionReason.LIFECYCLE_CLAIM_UNAVAILABLE
                    )
                current = claimed
            try:
                runtime_configuration = _runtime_configuration(
                    current,
                    state=state,
                    require_ready=preflight.command_type
                    not in {
                        RuntimeProviderCommandType.STOP,
                        RuntimeProviderCommandType.TERMINAL_DELETE,
                        RuntimeProviderCommandType.OBSERVE,
                    },
                )
            except ValueError as error:
                failure_code = "RUNTIME_CONFIGURATION_INVALID"
                failure_message = str(error)
                await self.runtime_repository.record_runtime_failure(
                    session,
                    current.id,
                    AgentRuntimeFailurePatch(
                        generation=current.desired_generation,
                        code=failure_code,
                        message=failure_message,
                    ),
                )
                return RuntimeLifecycleDispatchRejection(
                    reason=(
                        RuntimeLifecycleDispatchRejectionReason.CONFIGURATION_INVALID
                    ),
                    failure_code=failure_code,
                    failure_message=failure_message,
                )
            return _admission(
                agent=agent,
                runtime=current,
                provider_id=preflight.provider_id,
                command_type=preflight.command_type,
                connection_generation=connection_generation,
                runtime_configuration=runtime_configuration,
            )

    async def record_connection_outcome(
        self,
        snapshot: RuntimeLifecycleDispatchSnapshot,
        connection_state: RuntimeProviderConnectionState,
    ) -> bool:
        """Record connection state only while dispatch authority remains current."""
        async with self.session_manager() as session:
            current = await self._load_current_snapshot(
                session,
                snapshot,
            )
            if current is None:
                return False
            updated = await self.runtime_repository.record_provider_connection_state(
                session,
                snapshot.runtime_id,
                connection_state,
            )
            return updated is not None

    async def _load_current_snapshot(
        self,
        session: AsyncSession,
        snapshot: RuntimeLifecycleDispatchSnapshot,
    ) -> AgentRuntime | None:
        """Lock and revalidate one Agent and Runtime dispatch snapshot."""
        agent = await self.agent_repository.lock_by_id(
            session,
            snapshot.agent_id,
        )
        if (
            agent is None
            or agent.runtime_capability is not snapshot.agent_runtime_capability
            or agent.runtime_capability_version
            != snapshot.agent_runtime_capability_version
            or not _runtime_dispatch_allowed(
                agent.runtime_capability,
                snapshot.command_type,
            )
        ):
            return None
        current = await self.runtime_repository.get_by_id_for_update(
            session,
            snapshot.runtime_id,
        )
        if not _runtime_dispatch_outcome_matches(current, snapshot):
            return None
        return current


def _rejection(
    reason: RuntimeLifecycleDispatchRejectionReason,
) -> RuntimeLifecycleDispatchRejection:
    return RuntimeLifecycleDispatchRejection(
        reason=reason,
        failure_code=None,
        failure_message=None,
    )


def _preflight(
    *,
    agent: Agent,
    runtime: AgentRuntime,
    provider_id: str,
    request: RuntimeLifecycleDispatchRequest,
) -> RuntimeLifecycleDispatchPreflight:
    return RuntimeLifecycleDispatchPreflight(
        runtime_id=runtime.id,
        agent_id=runtime.agent_id,
        workspace_id=runtime.workspace_id,
        agent_runtime_capability=agent.runtime_capability,
        agent_runtime_capability_version=agent.runtime_capability_version,
        provider_id=provider_id,
        provider_resource_id=runtime.runtime_provider_resource_id,
        configuration_sequence=runtime.configuration_sequence,
        desired_state=runtime.desired_state,
        desired_generation=runtime.desired_generation,
        last_lifecycle_command=runtime.last_lifecycle_command,
        reset_final_desired_state=runtime.reset_final_desired_state,
        terminal_delete_requested_generation=(
            runtime.terminal_delete_requested_generation
        ),
        provider_generation=runtime.provider_generation,
        provider_observed_generation=runtime.provider_observed_generation,
        provider_observed_state=runtime.provider_observed_state,
        last_lifecycle_dispatch_generation=(runtime.last_lifecycle_dispatch_generation),
        provider_connection_state=runtime.provider_connection_state,
        command_type=request.command_type,
        claim_lifecycle=request.claim_lifecycle,
        required_provider_generation=request.required_provider_generation,
        required_observed_generation=request.required_observed_generation,
        required_configuration_sequence=request.required_configuration_sequence,
        lifecycle_retry_delay=request.lifecycle_retry_delay,
    )


def _admission(
    *,
    agent: Agent,
    runtime: AgentRuntime,
    provider_id: str,
    command_type: RuntimeProviderCommandType,
    connection_generation: int,
    runtime_configuration: RuntimeConfigurationEnvelope,
) -> RuntimeLifecycleDispatchAdmission:
    return RuntimeLifecycleDispatchAdmission(
        runtime_id=runtime.id,
        agent_id=runtime.agent_id,
        workspace_id=runtime.workspace_id,
        agent_runtime_capability=agent.runtime_capability,
        agent_runtime_capability_version=agent.runtime_capability_version,
        provider_id=provider_id,
        provider_resource_id=runtime.runtime_provider_resource_id,
        configuration_sequence=runtime.configuration_sequence,
        desired_state=runtime.desired_state,
        desired_generation=runtime.desired_generation,
        last_lifecycle_command=runtime.last_lifecycle_command,
        reset_final_desired_state=runtime.reset_final_desired_state,
        terminal_delete_requested_generation=(
            runtime.terminal_delete_requested_generation
        ),
        provider_generation=runtime.provider_generation,
        provider_observed_generation=runtime.provider_observed_generation,
        provider_observed_state=runtime.provider_observed_state,
        last_lifecycle_dispatch_generation=(runtime.last_lifecycle_dispatch_generation),
        provider_connection_state=runtime.provider_connection_state,
        command_type=command_type,
        connection_generation=connection_generation,
        runtime_configuration=runtime_configuration,
    )


def _runtime_dispatch_allowed(
    capability: AgentRuntimeCapability,
    command_type: RuntimeProviderCommandType,
) -> bool:
    """Allow ordinary dispatch only while managed; removal owns terminal delete."""
    return capability is AgentRuntimeCapability.MANAGED or (
        capability is AgentRuntimeCapability.REMOVING
        and command_type is RuntimeProviderCommandType.TERMINAL_DELETE
    )


def _runtime_dispatch_snapshot_matches(
    current: AgentRuntime | None,
    expected: AgentRuntime,
) -> bool:
    """Require the locked Runtime to match the selected dispatch authority."""
    return (
        current is not None
        and current.agent_id == expected.agent_id
        and current.runtime_provider_id == expected.runtime_provider_id
        and current.runtime_provider_resource_id
        == expected.runtime_provider_resource_id
        and current.desired_state is expected.desired_state
        and current.desired_generation == expected.desired_generation
        and current.last_lifecycle_command is expected.last_lifecycle_command
        and current.terminal_delete_requested_generation
        == expected.terminal_delete_requested_generation
        and current.configuration_sequence == expected.configuration_sequence
        and current.provider_generation == expected.provider_generation
        and current.provider_observed_generation
        == expected.provider_observed_generation
        and current.provider_observed_state is expected.provider_observed_state
    )


def _runtime_dispatch_preflight_matches(
    current: AgentRuntime | None,
    preflight: RuntimeLifecycleDispatchPreflight,
) -> bool:
    """Require claim authority to remain equal to the preflight snapshot."""
    return (
        current is not None
        and current.agent_id == preflight.agent_id
        and current.runtime_provider_id == preflight.provider_id
        and current.runtime_provider_resource_id == preflight.provider_resource_id
        and current.desired_state is preflight.desired_state
        and current.desired_generation == preflight.desired_generation
        and current.last_lifecycle_command is preflight.last_lifecycle_command
        and current.terminal_delete_requested_generation
        == preflight.terminal_delete_requested_generation
        and current.configuration_sequence == preflight.configuration_sequence
        and current.provider_generation == preflight.provider_generation
        and current.provider_observed_generation
        == preflight.provider_observed_generation
        and current.provider_observed_state is preflight.provider_observed_state
        and current.last_lifecycle_dispatch_generation
        == preflight.last_lifecycle_dispatch_generation
    )


def _runtime_dispatch_outcome_matches(
    current: AgentRuntime | None,
    snapshot: RuntimeLifecycleDispatchSnapshot,
) -> bool:
    """Reject a dispatch outcome after any snapshotted authority changed."""
    return (
        current is not None
        and current.agent_id == snapshot.agent_id
        and current.runtime_provider_id == snapshot.provider_id
        and current.runtime_provider_resource_id == snapshot.provider_resource_id
        and current.desired_state is snapshot.desired_state
        and current.desired_generation == snapshot.desired_generation
        and current.last_lifecycle_command is snapshot.last_lifecycle_command
        and current.terminal_delete_requested_generation
        == snapshot.terminal_delete_requested_generation
        and current.configuration_sequence == snapshot.configuration_sequence
        and current.provider_generation == snapshot.provider_generation
        and current.provider_observed_generation
        == snapshot.provider_observed_generation
        and current.provider_observed_state is snapshot.provider_observed_state
        and current.last_lifecycle_dispatch_generation
        == snapshot.last_lifecycle_dispatch_generation
        and current.provider_connection_state is snapshot.provider_connection_state
    )


def _current_network_policy_repair_target(
    runtime: AgentRuntime,
    *,
    state: RuntimeConfigurationState | None,
    provider_id: str,
    provider_generation: int | None,
    observed_generation: int | None,
    configuration_sequence: int | None,
) -> bool:
    """Return whether one drift-repair snapshot remains current at dispatch."""
    return (
        runtime.runtime_provider_id == provider_id
        and runtime.desired_state is RuntimeDesiredState.RUNNING
        and runtime.provider_observed_state is RuntimeProviderObservedState.RUNNING
        and runtime.provider_generation == provider_generation
        and runtime.provider_observed_generation == observed_generation
        and runtime.desired_generation == observed_generation
        and runtime.last_lifecycle_dispatch_generation >= runtime.desired_generation
        and runtime.terminal_delete_requested_generation is None
        and state is not None
        and state.applied is not None
        and state.desired.status is RuntimeConfigurationStateStatus.READY
        and state.desired.sequence == configuration_sequence
        and state.applied.sequence == configuration_sequence
    )


def _runtime_configuration(
    runtime: AgentRuntime,
    *,
    state: RuntimeConfigurationState | None,
    require_ready: bool,
) -> RuntimeConfigurationEnvelope:
    """Build and validate one exact Runtime configuration envelope."""
    if state is None:
        raise ValueError("Runtime configuration state is missing.")
    desired = state.desired
    slot = (
        desired
        if desired.status is RuntimeConfigurationStateStatus.READY
        else state.applied
    )
    if require_ready:
        slot = desired
    if (
        slot is None
        or slot.document is None
        or slot.digest is None
        or slot.document.resolved_configuration is None
    ):
        raise ValueError("Runtime configuration target document is missing.")
    document = slot.document
    resolved_configuration = document.resolved_configuration
    assert resolved_configuration is not None
    if (
        runtime.runtime_provider_resource_id is None
        or document.provider_id != runtime.runtime_provider_resource_id
    ):
        raise ValueError("Runtime configuration Provider binding is invalid.")
    if require_ready and slot.target_generation != runtime.desired_generation:
        raise ValueError("Runtime configuration target generation is stale.")
    envelope = RuntimeConfigurationEnvelope(
        evidence=RuntimeConfigurationEvidence(
            configuration_sequence=slot.sequence,
            digest=slot.digest,
            desired_generation=runtime.desired_generation,
        ),
        resolved_configuration_json=canonical_runtime_configuration_json(
            resolved_configuration
        ),
    )
    configuration = parse_runtime_configuration_envelope(
        envelope,
        desired_generation=runtime.desired_generation,
        expected_provider_kind=None,
    )
    if (
        configuration.provider.id != document.provider_id
        or configuration.provider.logical_id != runtime.runtime_provider_id
        or configuration.provider.capability_revision_id
        != document.provider_capability_revision_id
    ):
        raise ValueError("Runtime configuration Provider reference is invalid.")
    if not require_ready:
        return envelope
    if (
        configuration.infrastructure_profile.id != document.infrastructure_profile_id
        or configuration.infrastructure_profile.version
        != document.infrastructure_profile_version
    ):
        raise ValueError(
            "Runtime configuration Infrastructure Profile reference is invalid."
        )
    if (
        configuration.workspace_runtime_profile.id
        != document.workspace_runtime_profile_id
        or configuration.workspace_runtime_profile.version
        != document.workspace_runtime_profile_version
    ):
        raise ValueError(
            "Runtime configuration Workspace Runtime Profile reference is invalid."
        )
    return envelope
