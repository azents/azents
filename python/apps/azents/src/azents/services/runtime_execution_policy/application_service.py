"""Runtime execution-policy application and restrictive convergence."""

import dataclasses
import hashlib
import json
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimePolicySnapshotApplicationState,
    WorkspaceUserRole,
)
from azents.core.runtime_execution_policy import (
    RUNTIME_EXECUTION_PLATFORM_POLICY_ID,
    SYSTEM_STANDARD_PROFILE_ID,
    JsonValue,
    RuntimeExecutionAuditEventType,
    RuntimeExecutionChangeDirection,
    RuntimeExecutionChangeSummary,
    RuntimeExecutionManagementLayer,
    RuntimeExecutionModuleId,
    RuntimeExecutionModuleSupport,
    RuntimeExecutionNetworkMode,
    RuntimeExecutionPolicyDocument,
    RuntimeExecutionProfileLifecycle,
    RuntimeExecutionProviderCapabilities,
    RuntimeExecutionResolution,
    RuntimeExecutionSourceVersions,
    RuntimeExecutionStorageMode,
    canonical_runtime_execution_policy,
    digest_runtime_execution_policy,
    empty_runtime_execution_restriction,
    resolve_runtime_execution_policy,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime, AgentRuntimeLifecycleCommand
from azents.repos.runtime_execution_policy.data import (
    RuntimeExecutionPolicyAuditEventCreate,
)
from azents.repos.runtime_execution_policy.repository import (
    RuntimeExecutionPolicyRepository,
)
from azents.repos.runtime_provider_policy.data import (
    RuntimePolicySnapshot,
    RuntimePolicySnapshotCreate,
)
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)
from azents.services.runtime_execution_policy.service import (
    RuntimeExecutionPolicyUnavailable,
)


@dataclasses.dataclass
class RuntimeExecutionPolicyApplicationUnavailable(RuntimeExecutionPolicyUnavailable):
    """Current Agent intent cannot be safely targeted."""


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionPolicyApplicationResult:
    """One exact target snapshot created or reused by application."""

    snapshot: RuntimePolicySnapshot
    created: bool


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionPolicyConvergenceResult:
    """Summary for one bounded convergence scan."""

    scanned: int
    targeted: int
    stopped: int
    pending_expansion: int


@dataclasses.dataclass(frozen=True)
class _ResolvedRuntimePolicy:
    """Locked resolution inputs and current immutable application state."""

    runtime: AgentRuntime
    target_snapshot: RuntimePolicySnapshot
    applied_snapshot: RuntimePolicySnapshot | None
    profile_id: str
    resolution: RuntimeExecutionResolution


@dataclasses.dataclass(frozen=True)
class _LifecycleTargetResult:
    """Lifecycle command with its exact immutable target snapshot."""

    command: AgentRuntimeLifecycleCommand
    snapshot: RuntimePolicySnapshot
    created: bool


@dataclasses.dataclass
class RuntimeExecutionPolicyApplicationService:
    """Create immutable targets and converge only restrictive policy changes."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    policy_repository: Annotated[
        RuntimeExecutionPolicyRepository,
        Depends(RuntimeExecutionPolicyRepository),
    ]
    snapshot_repository: Annotated[
        RuntimeProviderPolicyRepository,
        Depends(RuntimeProviderPolicyRepository),
    ]
    runtime_repository: Annotated[
        AgentRuntimeRepository,
        Depends(AgentRuntimeRepository),
    ]
    agent_admin_repository: Annotated[
        AgentAdminRepository,
        Depends(AgentAdminRepository),
    ]

    async def apply_agent_for_manager(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        actor_workspace_user_id: str,
        correlation_id: str,
    ) -> RuntimeExecutionPolicyApplicationResult:
        """Authorize and explicitly target current Agent intent."""
        async with self.session_manager() as session:
            owner_workspace_id = await self.policy_repository.get_agent_workspace_id(
                session,
                agent_id=agent_id,
            )
            if owner_workspace_id != workspace_id:
                raise RuntimeExecutionPolicyApplicationUnavailable(
                    "agent_not_found",
                    agent_id,
                )
            if role is not WorkspaceUserRole.OWNER and not (
                await self.agent_admin_repository.is_admin(
                    session,
                    agent_id,
                    workspace_user_id,
                )
            ):
                raise RuntimeExecutionPolicyApplicationUnavailable(
                    "agent_access_denied",
                    agent_id,
                )
            resolved = await self._resolve_locked(session, agent_id=agent_id)
            if not resolved.resolution.available:
                raise RuntimeExecutionPolicyApplicationUnavailable(
                    resolved.resolution.availability_reason.value
                    if resolved.resolution.availability_reason is not None
                    else "execution_policy_unavailable",
                    agent_id,
                )
            return await self._target_resolution(
                session,
                resolved=resolved,
                effective_policy=resolved.resolution.effective_policy,
                classification=RuntimeExecutionChangeDirection.APPLICATION,
                actor_workspace_user_id=actor_workspace_user_id,
                correlation_id=correlation_id,
                system_authority=False,
                reason_code="agent_apply",
            )

    async def converge_once(
        self,
        *,
        page_size: int = 100,
    ) -> RuntimeExecutionPolicyConvergenceResult:
        """Scan all bound Runtimes and auto-target restrictive changes only."""
        scanned = targeted = stopped = pending_expansion = 0
        after_runtime_id: str | None = None
        while True:
            async with self.session_manager() as session:
                page = await self.runtime_repository.list_policy_convergence_candidates(
                    session,
                    after_runtime_id=after_runtime_id,
                    limit=page_size,
                )
            if not page:
                break
            for candidate in page:
                scanned += 1
                outcome = await self._converge_runtime(candidate.id)
                targeted += outcome == "targeted"
                stopped += outcome == "stopped"
                pending_expansion += outcome == "pending_expansion"
            after_runtime_id = page[-1].id
        return RuntimeExecutionPolicyConvergenceResult(
            scanned=scanned,
            targeted=targeted,
            stopped=stopped,
            pending_expansion=pending_expansion,
        )

    async def target_lifecycle_command(
        self,
        *,
        agent_id: str,
        command_type: RuntimeLifecycleCommandType,
        desired_state: RuntimeDesiredState,
        reset_final_desired_state: RuntimeDesiredState | None,
        terminal_delete_requested: bool,
    ) -> AgentRuntimeLifecycleCommand:
        """Advance lifecycle generation with an immutable exact policy target."""
        async with self.session_manager() as session:
            resolved = await self._resolve_locked(session, agent_id=agent_id)
            result = await self._target_lifecycle_command_locked(
                session,
                resolved=resolved,
                command_type=command_type,
                desired_state=desired_state,
                reset_final_desired_state=reset_final_desired_state,
                terminal_delete_requested=terminal_delete_requested,
            )
            return result.command

    async def _target_lifecycle_command_locked(
        self,
        session: AsyncSession,
        *,
        resolved: _ResolvedRuntimePolicy,
        command_type: RuntimeLifecycleCommandType,
        desired_state: RuntimeDesiredState,
        reset_final_desired_state: RuntimeDesiredState | None,
        terminal_delete_requested: bool,
    ) -> _LifecycleTargetResult:
        """Create one generation-fenced lifecycle target under the Runtime lock."""
        if (
            terminal_delete_requested
            and resolved.runtime.terminal_delete_requested_generation
            == resolved.runtime.desired_generation
        ):
            return _LifecycleTargetResult(
                command=AgentRuntimeLifecycleCommand(
                    runtime=resolved.runtime,
                    command_type=command_type,
                    desired_generation=resolved.runtime.desired_generation,
                ),
                snapshot=resolved.target_snapshot,
                created=False,
            )
        target = resolved.target_snapshot
        effective_policy = _snapshot_policy(target)
        if effective_policy is None:
            if not resolved.resolution.available:
                raise RuntimeExecutionPolicyApplicationUnavailable(
                    resolved.resolution.availability_reason.value
                    if resolved.resolution.availability_reason is not None
                    else "execution_policy_unavailable",
                    resolved.runtime.agent_id,
                )
            effective_policy = resolved.resolution.effective_policy
            source_versions = resolved.resolution.source_versions
            profile_id = resolved.profile_id
            execution_source_trace = {
                "governing_layers": {
                    path: layer.value
                    for path, layer in resolved.resolution.governing_layers.items()
                },
                "reductions": [
                    reduction.model_dump(mode="json")
                    for reduction in resolved.resolution.reductions
                ],
            }
            provider_compatibility = {
                "mode": "standard_only",
                "authority_bearing_policy_supported": False,
            }
        else:
            source_versions = _snapshot_source_versions(target)
            profile_id = target.execution_profile_id
            execution_source_trace = target.execution_source_trace
            provider_compatibility = target.execution_provider_compatibility

        next_generation = resolved.runtime.desired_generation + 1
        canonical_policy = canonical_runtime_execution_policy(effective_policy)
        if not isinstance(canonical_policy, dict):
            raise AssertionError("Canonical execution policy must be an object.")
        execution_digest = digest_runtime_execution_policy(effective_policy)
        snapshot = await self.snapshot_repository.create_and_advance_target_snapshot(
            session,
            create=RuntimePolicySnapshotCreate(
                runtime_id=resolved.runtime.id,
                provider_id=target.provider_id,
                contract_revision_id=target.contract_revision_id,
                config_revision_id=target.config_revision_id,
                override_provider_id=target.override_provider_id,
                override_version=target.override_version,
                execution_profile_id=profile_id,
                execution_platform_version=source_versions.platform,
                execution_profile_version=source_versions.profile,
                execution_workspace_version=source_versions.workspace,
                execution_agent_version=source_versions.agent,
                resolved_execution_policy=canonical_policy,
                execution_source_trace=execution_source_trace,
                execution_provider_compatibility=provider_compatibility,
                execution_target_digest=execution_digest,
                execution_reported_digest=None,
                resolved_config=target.resolved_config,
                encrypted_secrets=target.encrypted_secrets,
                secret_metadata=target.secret_metadata,
                source_trace={
                    **target.source_trace,
                    "execution_policy": execution_digest,
                },
                digest=_snapshot_digest(
                    runtime_id=resolved.runtime.id,
                    provider_id=target.provider_id,
                    base_snapshot_id=target.id,
                    execution_digest=execution_digest,
                    desired_generation=next_generation,
                ),
                target_desired_generation=next_generation,
                application_state=RuntimePolicySnapshotApplicationState.PENDING,
            ),
            expected_target_snapshot_id=target.id,
            lifecycle_command=command_type,
            desired_state=desired_state,
            reset_final_desired_state=reset_final_desired_state,
            terminal_delete_requested=terminal_delete_requested,
        )
        if snapshot is None:
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "runtime_policy_target_conflict",
                resolved.runtime.id,
            )
        runtime = await self.runtime_repository.get_by_id(
            session,
            resolved.runtime.id,
        )
        if runtime is None:
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "runtime_not_found",
                resolved.runtime.id,
            )
        return _LifecycleTargetResult(
            command=AgentRuntimeLifecycleCommand(
                runtime=runtime,
                command_type=command_type,
                desired_generation=runtime.desired_generation,
            ),
            snapshot=snapshot,
            created=True,
        )

    async def _converge_runtime(self, runtime_id: str) -> str:
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_id_for_update(
                session,
                runtime_id,
            )
            if runtime is None:
                return "unchanged"
            resolved = await self._resolve_locked(
                session,
                agent_id=runtime.agent_id,
                locked_runtime=runtime,
            )
            if not _automatic_convergence_source_allowed(resolved):
                return "pending_expansion"
            if not resolved.resolution.available:
                if runtime.desired_state is RuntimeDesiredState.STOPPED:
                    return "unchanged"
                stopped = await self._target_lifecycle_command_locked(
                    session,
                    resolved=resolved,
                    command_type=RuntimeLifecycleCommandType.STOP,
                    desired_state=RuntimeDesiredState.STOPPED,
                    reset_final_desired_state=None,
                    terminal_delete_requested=False,
                )
                await self._append_audit(
                    session,
                    resolved=resolved,
                    snapshot=stopped.snapshot,
                    classification=RuntimeExecutionChangeDirection.INCOMPATIBLE,
                    actor_workspace_user_id=None,
                    correlation_id=f"policy-convergence:{runtime.id}",
                    system_authority=True,
                    reason_code="automatic_incompatible_stop",
                )
                return "stopped"

            direction = resolved.resolution.change.direction
            if direction in {
                RuntimeExecutionChangeDirection.METADATA_ONLY,
                RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING,
            }:
                return (
                    "pending_expansion"
                    if direction is RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
                    else "unchanged"
                )
            applied_policy = _snapshot_policy(resolved.applied_snapshot)
            if applied_policy is None:
                applied_policy = resolved.resolution.effective_policy
            effective_policy = (
                resolved.resolution.effective_policy
                if direction is RuntimeExecutionChangeDirection.RESTRICTIVE
                else _restrictive_projection(
                    applied_policy,
                    resolved.resolution.effective_policy,
                    resolved.resolution.change,
                )
            )
            result = await self._target_resolution(
                session,
                resolved=resolved,
                effective_policy=effective_policy,
                classification=direction,
                actor_workspace_user_id=None,
                correlation_id=f"policy-convergence:{runtime.id}",
                system_authority=True,
                reason_code="automatic_restriction",
            )
            return "targeted" if result.created else "unchanged"

    async def _resolve_locked(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        locked_runtime: AgentRuntime | None = None,
    ) -> _ResolvedRuntimePolicy:
        runtime = (
            locked_runtime
            or await self.runtime_repository.get_by_agent_id_for_update(
                session,
                agent_id,
            )
        )
        if runtime is None or runtime.runtime_provider_resource_id is None:
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "runtime_provider_binding_missing",
                agent_id,
            )
        platform = await self.policy_repository.get_platform(session, for_update=True)
        setting = await self.policy_repository.get_agent_setting(
            session,
            agent_id=agent_id,
            for_update=True,
        )
        workspace = await self.policy_repository.get_workspace(
            session,
            workspace_id=runtime.workspace_id,
            for_update=True,
        )
        if platform is None or setting is None:
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "execution_policy_state_missing",
                RUNTIME_EXECUTION_PLATFORM_POLICY_ID if platform is None else agent_id,
            )
        profile = await self.policy_repository.get_profile(
            session,
            profile_id=setting.profile_id,
            for_update=True,
        )
        if profile is None:
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "profile_not_found",
                setting.profile_id,
            )
        if runtime.runtime_policy_snapshot_id is None:
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "runtime_policy_target_missing",
                runtime.id,
            )
        target_snapshot = await self.snapshot_repository.get_snapshot(
            session,
            snapshot_id=runtime.runtime_policy_snapshot_id,
            for_update=True,
        )
        if target_snapshot is None:
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "runtime_policy_target_missing",
                runtime.id,
            )
        applied_snapshot = None
        if runtime.applied_runtime_policy_snapshot_id is not None:
            applied_snapshot = await self.snapshot_repository.get_snapshot(
                session,
                snapshot_id=runtime.applied_runtime_policy_snapshot_id,
                for_update=False,
            )
        workspace_restriction = (
            workspace.restriction
            if workspace is not None
            else empty_runtime_execution_restriction()
        )
        allowed_profiles = (
            workspace.allowed_profile_ids
            if workspace is not None
            else frozenset({SYSTEM_STANDARD_PROFILE_ID})
        )
        resolution = resolve_runtime_execution_policy(
            platform_policy=platform.policy,
            profile_policy=profile.policy,
            workspace_restriction=workspace_restriction,
            agent_restriction=setting.restriction,
            source_versions=RuntimeExecutionSourceVersions(
                platform=platform.version,
                profile=profile.version,
                workspace=workspace.version if workspace is not None else 1,
                agent=setting.version,
            ),
            provider_capabilities=_phase_three_provider_capabilities(),
            profile_active=(
                profile.lifecycle is RuntimeExecutionProfileLifecycle.ACTIVE
            ),
            profile_allowed=profile.id in allowed_profiles,
            applied_policy=_snapshot_policy(applied_snapshot),
        )
        return _ResolvedRuntimePolicy(
            runtime=runtime,
            target_snapshot=target_snapshot,
            applied_snapshot=applied_snapshot,
            profile_id=profile.id,
            resolution=resolution,
        )

    async def _target_resolution(
        self,
        session: AsyncSession,
        *,
        resolved: _ResolvedRuntimePolicy,
        effective_policy: RuntimeExecutionPolicyDocument,
        classification: RuntimeExecutionChangeDirection,
        actor_workspace_user_id: str | None,
        correlation_id: str,
        system_authority: bool,
        reason_code: str,
    ) -> RuntimeExecutionPolicyApplicationResult:
        runtime = resolved.runtime
        source_versions = resolved.resolution.source_versions
        execution_digest = digest_runtime_execution_policy(effective_policy)
        if _snapshot_matches_target(
            resolved.target_snapshot,
            execution_digest=execution_digest,
            source_versions=source_versions,
            desired_generation=runtime.desired_generation,
        ):
            return RuntimeExecutionPolicyApplicationResult(
                snapshot=resolved.target_snapshot,
                created=False,
            )
        next_generation = runtime.desired_generation + 1
        lifecycle_command = (
            RuntimeLifecycleCommandType.RESTART
            if runtime.desired_state is RuntimeDesiredState.RUNNING
            else RuntimeLifecycleCommandType.STOP
        )
        canonical_policy = canonical_runtime_execution_policy(effective_policy)
        if not isinstance(canonical_policy, dict):
            raise AssertionError("Canonical execution policy must be an object.")
        snapshot = await self.snapshot_repository.create_and_advance_target_snapshot(
            session,
            create=RuntimePolicySnapshotCreate(
                runtime_id=runtime.id,
                provider_id=resolved.target_snapshot.provider_id,
                contract_revision_id=resolved.target_snapshot.contract_revision_id,
                config_revision_id=resolved.target_snapshot.config_revision_id,
                override_provider_id=resolved.target_snapshot.override_provider_id,
                override_version=resolved.target_snapshot.override_version,
                execution_profile_id=resolved.profile_id,
                execution_platform_version=source_versions.platform,
                execution_profile_version=source_versions.profile,
                execution_workspace_version=source_versions.workspace,
                execution_agent_version=source_versions.agent,
                resolved_execution_policy=canonical_policy,
                execution_source_trace={
                    "governing_layers": {
                        path: layer.value
                        for path, layer in resolved.resolution.governing_layers.items()
                    },
                    "reductions": [
                        reduction.model_dump(mode="json")
                        for reduction in resolved.resolution.reductions
                    ],
                },
                execution_provider_compatibility={
                    "mode": "standard_only",
                    "authority_bearing_policy_supported": False,
                },
                execution_target_digest=execution_digest,
                execution_reported_digest=None,
                resolved_config=resolved.target_snapshot.resolved_config,
                encrypted_secrets=resolved.target_snapshot.encrypted_secrets,
                secret_metadata=resolved.target_snapshot.secret_metadata,
                source_trace={
                    **resolved.target_snapshot.source_trace,
                    "execution_policy": execution_digest,
                },
                digest=_snapshot_digest(
                    runtime_id=runtime.id,
                    provider_id=resolved.target_snapshot.provider_id,
                    base_snapshot_id=resolved.target_snapshot.id,
                    execution_digest=execution_digest,
                    desired_generation=next_generation,
                ),
                target_desired_generation=next_generation,
                application_state=RuntimePolicySnapshotApplicationState.PENDING,
            ),
            expected_target_snapshot_id=resolved.target_snapshot.id,
            lifecycle_command=lifecycle_command,
            desired_state=None,
            reset_final_desired_state=None,
            terminal_delete_requested=False,
        )
        if snapshot is None:
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "runtime_policy_target_conflict",
                runtime.id,
            )
        await self._append_audit(
            session,
            resolved=resolved,
            snapshot=snapshot,
            classification=classification,
            actor_workspace_user_id=actor_workspace_user_id,
            correlation_id=correlation_id,
            system_authority=system_authority,
            reason_code=reason_code,
        )
        return RuntimeExecutionPolicyApplicationResult(snapshot=snapshot, created=True)

    async def _append_audit(
        self,
        session: AsyncSession,
        *,
        resolved: _ResolvedRuntimePolicy,
        snapshot: RuntimePolicySnapshot | None,
        classification: RuntimeExecutionChangeDirection,
        actor_workspace_user_id: str | None,
        correlation_id: str,
        system_authority: bool,
        reason_code: str,
    ) -> None:
        await self.policy_repository.append_audit_event(
            session,
            create=RuntimeExecutionPolicyAuditEventCreate(
                event_type=RuntimeExecutionAuditEventType.TARGET_SNAPSHOT_ATTACHED,
                management_layer=RuntimeExecutionManagementLayer.RUNTIME,
                target_id=resolved.runtime.id,
                correlation_id=correlation_id,
                classification=classification,
                changed_paths=tuple(
                    field.path for field in resolved.resolution.change.fields
                ),
                impact_counts={"runtime_count": 1},
                reason_code=reason_code,
                outcome_code="targeted" if snapshot is not None else "stopped",
                metadata={
                    "snapshot_id": snapshot.id if snapshot is not None else None,
                    "desired_generation": (
                        snapshot.target_desired_generation
                        if snapshot is not None
                        else resolved.runtime.desired_generation + 1
                    ),
                },
                workspace_id=resolved.runtime.workspace_id,
                agent_id=resolved.runtime.agent_id,
                runtime_id=resolved.runtime.id,
                actor_user_id=None,
                actor_workspace_user_id=actor_workspace_user_id,
                system_authority=system_authority,
                before_digest=(
                    resolved.applied_snapshot.execution_target_digest
                    if resolved.applied_snapshot is not None
                    else None
                ),
                after_digest=(
                    snapshot.execution_target_digest if snapshot is not None else None
                ),
            ),
        )


def _phase_three_provider_capabilities() -> RuntimeExecutionProviderCapabilities:
    """Expose only support that cannot grant Runtime authority in Phase 3."""
    return RuntimeExecutionProviderCapabilities(
        supported_modules=frozenset(
            RuntimeExecutionModuleSupport(module_id=module_id, version=1)
            for module_id in RuntimeExecutionModuleId
        ),
        privileged_engine=False,
        storage_modes=frozenset({RuntimeExecutionStorageMode.NONE}),
        network_modes=frozenset({RuntimeExecutionNetworkMode.NONE}),
        resource_maxima=None,
    )


def _snapshot_policy(
    snapshot: RuntimePolicySnapshot | None,
) -> RuntimeExecutionPolicyDocument | None:
    if snapshot is None or snapshot.resolved_execution_policy is None:
        return None
    return RuntimeExecutionPolicyDocument.model_validate(
        snapshot.resolved_execution_policy
    )


def _snapshot_source_versions(
    snapshot: RuntimePolicySnapshot,
) -> RuntimeExecutionSourceVersions:
    values = (
        snapshot.execution_platform_version,
        snapshot.execution_profile_version,
        snapshot.execution_workspace_version,
        snapshot.execution_agent_version,
    )
    if any(value is None for value in values):
        raise RuntimeExecutionPolicyApplicationUnavailable(
            "runtime_policy_target_incomplete",
            snapshot.id,
        )
    platform, profile, workspace, agent = values
    assert platform is not None
    assert profile is not None
    assert workspace is not None
    assert agent is not None
    return RuntimeExecutionSourceVersions(
        platform=platform,
        profile=profile,
        workspace=workspace,
        agent=agent,
    )


def _snapshot_matches_target(
    snapshot: RuntimePolicySnapshot,
    *,
    execution_digest: str,
    source_versions: RuntimeExecutionSourceVersions,
    desired_generation: int,
) -> bool:
    return (
        snapshot.execution_target_digest == execution_digest
        and snapshot.target_desired_generation == desired_generation
        and snapshot.execution_platform_version == source_versions.platform
        and snapshot.execution_profile_version == source_versions.profile
        and snapshot.execution_workspace_version == source_versions.workspace
        and snapshot.execution_agent_version == source_versions.agent
    )


def _automatic_convergence_source_allowed(
    resolved: _ResolvedRuntimePolicy,
) -> bool:
    """Allow automatic targeting only when Profile and Agent intent are unchanged."""
    source_versions = resolved.resolution.source_versions
    target = resolved.target_snapshot
    return (
        target.execution_profile_version == source_versions.profile
        and target.execution_agent_version == source_versions.agent
    )


def _restrictive_projection(
    applied: RuntimeExecutionPolicyDocument,
    current: RuntimeExecutionPolicyDocument,
    change: RuntimeExecutionChangeSummary,
) -> RuntimeExecutionPolicyDocument:
    projected = canonical_runtime_execution_policy(applied)
    current_values = canonical_runtime_execution_policy(current)
    if not isinstance(projected, dict) or not isinstance(current_values, dict):
        raise AssertionError("Canonical execution policies must be objects.")
    for field in change.fields:
        if field.direction is RuntimeExecutionChangeDirection.RESTRICTIVE:
            _copy_path(projected, current_values, field.path.split("."))
    return RuntimeExecutionPolicyDocument.model_validate(projected)


def _copy_path(
    target: dict[str, JsonValue],
    source: dict[str, JsonValue],
    path: list[str],
) -> None:
    key = path[0]
    if len(path) == 1:
        target[key] = source[key]
        return
    target_child = target.get(key)
    source_child = source.get(key)
    if not isinstance(target_child, dict) or not isinstance(source_child, dict):
        raise ValueError("Execution-policy change path is invalid.")
    _copy_path(target_child, source_child, path[1:])


def _snapshot_digest(
    *,
    runtime_id: str,
    provider_id: str,
    base_snapshot_id: str,
    execution_digest: str,
    desired_generation: int,
) -> str:
    encoded = json.dumps(
        {
            "runtime_id": runtime_id,
            "provider_id": provider_id,
            "base_snapshot_id": base_snapshot_id,
            "execution_digest": execution_digest,
            "desired_generation": desired_generation,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
