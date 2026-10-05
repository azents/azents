"""Durable and volatile authority resolution for Public Runtime Terminal."""

import dataclasses
from datetime import datetime

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_profile.data import (
    RuntimeConfigurationAppliedSlot,
    RuntimeInfrastructureProfile,
    WorkspaceRuntimeProfile,
)
from azents.repos.runtime_terminal_authority_read import (
    RuntimeTerminalAuthorityReadRepository,
)
from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeConnectionRecord,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTarget
from azents.services.runtime_terminal.data import (
    RuntimeTerminalAuthority,
    RuntimeTerminalDeniedScope,
    RuntimeTerminalProjectionState,
    RuntimeTerminalReasonCode,
    RuntimeTerminalResource,
)
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderBindingError,
    SessionWorkingFolderBindingService,
)
from azents.services.terminal_policy.data import (
    TerminalPolicyDeniedScope,
    TerminalPolicyEvidence,
    TerminalPolicyReasonCode,
    TerminalPolicyResolution,
)
from azents.services.terminal_policy.service import TerminalPolicyResolver

_SHELL_LABEL = "Shell"


class DatabaseRuntimeTerminalAuthorityResolver:
    """Resolve Public Terminal authority from current PostgreSQL and Runner state."""

    def __init__(
        self,
        *,
        authority_repository: RuntimeTerminalAuthorityReadRepository,
        runtime_coordination: RuntimeCoordinationStore,
        working_folder_service: SessionWorkingFolderBindingService,
        policy_resolver: TerminalPolicyResolver,
    ) -> None:
        """Initialize explicit durable, volatile, and policy dependencies."""
        self.authority_repository = authority_repository
        self.runtime_coordination = runtime_coordination
        self.working_folder_service = working_folder_service
        self.policy_resolver = policy_resolver

    async def resolve(
        self,
        *,
        user_id: str,
        authentication_session_id: str,
        resource: RuntimeTerminalResource,
        resolved_at: datetime,
    ) -> RuntimeTerminalAuthority:
        """Return one fail-closed current authority projection."""
        if resolved_at.tzinfo is None or resolved_at.utcoffset() is None:
            raise ValueError("Runtime Terminal authority time must be timezone-aware")
        snapshot = await self.authority_repository.read_snapshot(
            user_id=user_id,
            authentication_session_id=authentication_session_id,
            workspace_handle=resource.workspace_handle,
            agent_id=resource.agent_id,
            session_id=resource.session_id,
            resolved_at=resolved_at,
        )
        if snapshot.reason_code is not None:
            return _authority(
                user_id=user_id,
                authentication_session_id=authentication_session_id,
                authentication_session_expires_at=(
                    snapshot.authentication_session_expires_at
                ),
                workspace_id=snapshot.workspace_id or "",
                resource=resource,
                projection_state=RuntimeTerminalProjectionState.ABSENT,
                reason_code=RuntimeTerminalReasonCode(snapshot.reason_code),
                denied_scope=_identity_denied_scope(
                    RuntimeTerminalReasonCode(snapshot.reason_code)
                ),
            )

        agent = snapshot.agent
        assert agent is not None
        runtime = snapshot.runtime
        infrastructure = snapshot.infrastructure_profile
        workspace_profile = snapshot.workspace_profile
        applied = snapshot.applied_configuration

        runner = await self._get_runner(runtime)
        runner_capabilities = _runner_capabilities(runner)
        runner_workspace_path = _runner_workspace_path(runner)
        runner_generation = runner.generation if runner is not None else None
        profile_sources_current = _profile_sources_current(
            agent=agent,
            infrastructure=infrastructure,
            workspace_profile=workspace_profile,
        )
        policy = self.policy_resolver.resolve(
            TerminalPolicyEvidence(
                access_allowed=True,
                session_available=True,
                agent_id=agent.id,
                agent_terminal_enabled=agent.terminal_enabled,
                runtime_capability=agent.runtime_capability,
                runtime_id=runtime.id if runtime is not None else None,
                runtime_active=_runtime_active(runtime, applied),
                desired_generation=(
                    runtime.desired_generation if runtime is not None else None
                ),
                infrastructure_profile_id=(
                    infrastructure.id if infrastructure is not None else None
                ),
                infrastructure_profile_version=(
                    infrastructure.version if infrastructure is not None else None
                ),
                infrastructure_profile_lifecycle=(
                    infrastructure.lifecycle if infrastructure is not None else None
                ),
                infrastructure_profile_available=profile_sources_current,
                infrastructure_terminal_enabled=(
                    infrastructure.terminal_enabled
                    if infrastructure is not None
                    else None
                ),
                workspace_profile_id=(
                    workspace_profile.id if workspace_profile is not None else None
                ),
                workspace_profile_version=(
                    workspace_profile.version if workspace_profile is not None else None
                ),
                workspace_profile_lifecycle=(
                    workspace_profile.lifecycle
                    if workspace_profile is not None
                    else None
                ),
                workspace_profile_available=profile_sources_current,
                workspace_terminal_enabled=(
                    workspace_profile.terminal_enabled
                    if workspace_profile is not None
                    else None
                ),
                runner_generation=runner_generation,
                expected_runner_generation=(
                    runtime.runner_generation if runtime is not None else None
                ),
                runner_active=_runner_active(
                    runtime,
                    runner,
                    runner_workspace_path=runner_workspace_path,
                ),
                runner_capabilities=runner_capabilities,
            )
        )
        base = self._policy_projection(
            user_id=user_id,
            authentication_session_id=authentication_session_id,
            authentication_session_expires_at=(
                snapshot.authentication_session_expires_at
            ),
            workspace_id=snapshot.workspace_id or agent.workspace_id,
            resource=resource,
            agent=agent,
            runtime=runtime,
            workspace_profile=workspace_profile,
            infrastructure=infrastructure,
            policy=policy,
        )
        if not policy.available:
            return base
        assert runtime is not None
        assert applied is not None
        assert runner_workspace_path is not None
        try:
            folder = (
                await self.working_folder_service.resolve_bound_authority_for_target(
                    agent_id=agent.id,
                    session_id=resource.session_id,
                    runtime_target=RuntimeOperationTarget(
                        id=runtime.id,
                        runtime_capability_version=agent.runtime_capability_version,
                        desired_generation=runtime.desired_generation,
                        runner_generation=runtime.runner_generation,
                        configuration_sequence=applied.sequence,
                        configuration_digest=applied.digest,
                        workspace_path=runner_workspace_path,
                    ),
                )
            )
        except SessionWorkingFolderBindingError:
            return dataclasses.replace(
                base,
                projection_state=RuntimeTerminalProjectionState.UNAVAILABLE,
                reason_code=RuntimeTerminalReasonCode.WORKING_FOLDER_UNAVAILABLE,
                denied_scope=RuntimeTerminalDeniedScope.SESSION,
                can_open_or_attach=False,
            )
        return dataclasses.replace(
            base,
            working_directory=folder.working_folder_path,
            working_directory_display=folder.working_folder_path,
            can_open_or_attach=True,
        )

    async def _get_runner(
        self,
        runtime: AgentRuntime | None,
    ) -> RuntimeConnectionRecord | None:
        if runtime is None:
            return None
        return await self.runtime_coordination.get_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=runtime.id,
        )

    def _policy_projection(
        self,
        *,
        user_id: str,
        authentication_session_id: str,
        authentication_session_expires_at: datetime | None,
        workspace_id: str,
        resource: RuntimeTerminalResource,
        agent: Agent,
        runtime: AgentRuntime | None,
        workspace_profile: WorkspaceRuntimeProfile | None,
        infrastructure: RuntimeInfrastructureProfile | None,
        policy: TerminalPolicyResolution,
    ) -> RuntimeTerminalAuthority:
        reason = _policy_reason(policy.reason_code, runtime=runtime)
        return _authority(
            user_id=user_id,
            authentication_session_id=authentication_session_id,
            authentication_session_expires_at=authentication_session_expires_at,
            workspace_id=workspace_id,
            resource=resource,
            runtime_id=runtime.id if runtime is not None else None,
            desired_generation=(
                runtime.desired_generation if runtime is not None else None
            ),
            runner_generation=policy.runner_generation,
            workspace_profile_id=(
                workspace_profile.id if workspace_profile is not None else None
            ),
            workspace_profile_version=(
                workspace_profile.version if workspace_profile is not None else None
            ),
            provider_profile_id=(
                infrastructure.id if infrastructure is not None else None
            ),
            provider_profile_version=(
                infrastructure.version if infrastructure is not None else None
            ),
            agent_policy_version=agent.updated_at.isoformat(),
            projection_state=_projection_state(reason),
            reason_code=reason,
            denied_scope=_policy_scope(policy.denied_scope),
            can_start_runtime=(
                reason is RuntimeTerminalReasonCode.RUNTIME_STOPPED
                and runtime is not None
            ),
            can_open_or_attach=policy.available,
        )


def _authority(
    *,
    user_id: str,
    authentication_session_id: str,
    authentication_session_expires_at: datetime | None,
    workspace_id: str,
    resource: RuntimeTerminalResource,
    projection_state: RuntimeTerminalProjectionState,
    reason_code: RuntimeTerminalReasonCode | None,
    denied_scope: RuntimeTerminalDeniedScope | None,
    runtime_id: str | None = None,
    desired_generation: int | None = None,
    runner_generation: int | None = None,
    workspace_profile_id: str | None = None,
    workspace_profile_version: int | None = None,
    provider_profile_id: str | None = None,
    provider_profile_version: int | None = None,
    agent_policy_version: str | None = None,
    working_directory: str | None = None,
    working_directory_display: str | None = None,
    can_start_runtime: bool = False,
    can_open_or_attach: bool = False,
) -> RuntimeTerminalAuthority:
    return RuntimeTerminalAuthority(
        user_id=user_id,
        authentication_session_id=authentication_session_id,
        authentication_session_expires_at=authentication_session_expires_at,
        workspace_id=workspace_id,
        resource=resource,
        runtime_id=runtime_id,
        desired_generation=desired_generation,
        runner_generation=runner_generation,
        workspace_profile_id=workspace_profile_id,
        workspace_profile_version=workspace_profile_version,
        provider_profile_id=provider_profile_id,
        provider_profile_version=provider_profile_version,
        agent_policy_version=agent_policy_version,
        working_directory=working_directory,
        working_directory_display=working_directory_display,
        shell_label=_SHELL_LABEL,
        projection_state=projection_state,
        reason_code=reason_code,
        denied_scope=denied_scope,
        can_start_runtime=can_start_runtime,
        can_open_or_attach=can_open_or_attach,
    )


def _runtime_active(
    runtime: AgentRuntime | None,
    applied: RuntimeConfigurationAppliedSlot | None,
) -> bool:
    return (
        runtime is not None
        and applied is not None
        and runtime.desired_state is RuntimeDesiredState.RUNNING
        and runtime.terminal_delete_requested_generation is None
        and runtime.provider_observed_state is RuntimeProviderObservedState.RUNNING
        and runtime.provider_observed_generation == runtime.desired_generation
        and applied.target_generation == runtime.desired_generation
    )


def _runner_active(
    runtime: AgentRuntime | None,
    runner: RuntimeConnectionRecord | None,
    *,
    runner_workspace_path: str | None,
) -> bool:
    return (
        runtime is not None
        and runner is not None
        and runtime.runner_state is RuntimeRunnerState.READY
        and runtime.runner_generation > 0
        and runner.generation == runtime.runner_generation
        and runtime.workspace_path is not None
        and runner_workspace_path == runtime.workspace_path
    )


def _runner_capabilities(
    runner: RuntimeConnectionRecord | None,
) -> frozenset[str]:
    if runner is None:
        return frozenset()
    values = runner.metadata.get("capabilities")
    if not isinstance(values, list) or not all(
        isinstance(item, str) for item in values
    ):
        return frozenset()
    return frozenset(item for item in values if isinstance(item, str))


def _runner_workspace_path(runner: RuntimeConnectionRecord | None) -> str | None:
    if runner is None:
        return None
    value = runner.metadata.get("workspace_path")
    if not isinstance(value, str) or not value:
        return None
    return value


def _profile_sources_current(
    *,
    agent: Agent,
    infrastructure: RuntimeInfrastructureProfile | None,
    workspace_profile: WorkspaceRuntimeProfile | None,
) -> bool:
    return (
        infrastructure is not None
        and workspace_profile is not None
        and agent.runtime_profile_id == workspace_profile.id
        and workspace_profile.infrastructure_profile_id == infrastructure.id
        and workspace_profile.provider_id == infrastructure.provider_id
    )


def _policy_reason(
    reason: TerminalPolicyReasonCode | None,
    *,
    runtime: AgentRuntime | None,
) -> RuntimeTerminalReasonCode | None:
    if reason is None:
        return None
    if reason is TerminalPolicyReasonCode.RUNTIME_INACTIVE:
        if runtime is not None and runtime.desired_state is RuntimeDesiredState.STOPPED:
            return RuntimeTerminalReasonCode.RUNTIME_STOPPED
        return RuntimeTerminalReasonCode.RUNTIME_STARTING
    return {
        TerminalPolicyReasonCode.ACCESS_DENIED: RuntimeTerminalReasonCode.ACCESS_DENIED,
        TerminalPolicyReasonCode.SESSION_UNAVAILABLE: (
            RuntimeTerminalReasonCode.SESSION_NOT_FOUND
        ),
        TerminalPolicyReasonCode.RUNTIME_FREE_AGENT: (
            RuntimeTerminalReasonCode.RUNTIME_FREE_AGENT
        ),
        TerminalPolicyReasonCode.RUNTIME_UNAVAILABLE: (
            RuntimeTerminalReasonCode.RUNTIME_UNAVAILABLE
        ),
        TerminalPolicyReasonCode.INFRASTRUCTURE_PROFILE_UNAVAILABLE: (
            RuntimeTerminalReasonCode.PROFILE_UNAVAILABLE
        ),
        TerminalPolicyReasonCode.WORKSPACE_PROFILE_UNAVAILABLE: (
            RuntimeTerminalReasonCode.PROFILE_UNAVAILABLE
        ),
        TerminalPolicyReasonCode.INFRASTRUCTURE_TERMINAL_DISABLED: (
            RuntimeTerminalReasonCode.TERMINAL_DISABLED
        ),
        TerminalPolicyReasonCode.WORKSPACE_TERMINAL_DISABLED: (
            RuntimeTerminalReasonCode.TERMINAL_DISABLED
        ),
        TerminalPolicyReasonCode.AGENT_TERMINAL_DISABLED: (
            RuntimeTerminalReasonCode.TERMINAL_DISABLED
        ),
        TerminalPolicyReasonCode.RUNNER_UNAVAILABLE: (
            RuntimeTerminalReasonCode.RUNNER_UNAVAILABLE
        ),
        TerminalPolicyReasonCode.RUNNER_GENERATION_STALE: (
            RuntimeTerminalReasonCode.RUNNER_UNAVAILABLE
        ),
        TerminalPolicyReasonCode.RUNNER_TERMINAL_UNSUPPORTED: (
            RuntimeTerminalReasonCode.RUNNER_TERMINAL_UNSUPPORTED
        ),
    }[reason]


def _policy_scope(
    scope: TerminalPolicyDeniedScope | None,
) -> RuntimeTerminalDeniedScope | None:
    if scope is None:
        return None
    return RuntimeTerminalDeniedScope(scope.value)


def _identity_denied_scope(
    reason: RuntimeTerminalReasonCode,
) -> RuntimeTerminalDeniedScope:
    if reason in {
        RuntimeTerminalReasonCode.SESSION_NOT_FOUND,
        RuntimeTerminalReasonCode.SESSION_AGENT_MISMATCH,
    }:
        return RuntimeTerminalDeniedScope.SESSION
    if reason is RuntimeTerminalReasonCode.AGENT_NOT_FOUND:
        return RuntimeTerminalDeniedScope.AGENT
    return RuntimeTerminalDeniedScope.ACCESS


def _projection_state(
    reason: RuntimeTerminalReasonCode | None,
) -> RuntimeTerminalProjectionState:
    if reason is None:
        return RuntimeTerminalProjectionState.READY
    if reason is RuntimeTerminalReasonCode.RUNTIME_STOPPED:
        return RuntimeTerminalProjectionState.STOPPED
    if reason is RuntimeTerminalReasonCode.RUNTIME_STARTING:
        return RuntimeTerminalProjectionState.STARTING
    if reason in {
        RuntimeTerminalReasonCode.ACCESS_DENIED,
        RuntimeTerminalReasonCode.AGENT_NOT_FOUND,
        RuntimeTerminalReasonCode.SESSION_NOT_FOUND,
        RuntimeTerminalReasonCode.SESSION_AGENT_MISMATCH,
        RuntimeTerminalReasonCode.RUNTIME_FREE_AGENT,
    }:
        return RuntimeTerminalProjectionState.ABSENT
    return RuntimeTerminalProjectionState.UNAVAILABLE
