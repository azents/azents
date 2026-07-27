"""Runtime execution-policy application and restrictive convergence."""

import dataclasses
import hashlib
import json
from typing import Annotated

from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimePolicySnapshotApplicationState,
    RuntimeProviderContractStatus,
    WorkspaceUserRole,
)
from azents.core.runtime_execution_policy import (
    SYSTEM_STANDARD_PROFILE_ID,
    JsonValue,
    RuntimeExecutionAuditEventType,
    RuntimeExecutionChangeDirection,
    RuntimeExecutionChangeSummary,
    RuntimeExecutionManagementLayer,
    RuntimeExecutionModuleId,
    RuntimeExecutionNetworkMode,
    RuntimeExecutionPolicyDocument,
    RuntimeExecutionPolicyLayer,
    RuntimeExecutionPolicyStatus,
    RuntimeExecutionProfileLifecycle,
    RuntimeExecutionProviderCapabilities,
    RuntimeExecutionRequiredAction,
    RuntimeExecutionResolution,
    RuntimeExecutionSourceVersions,
    RuntimeExecutionStorageMode,
    canonical_runtime_execution_policy,
    canonical_runtime_execution_policy_json,
    digest_runtime_execution_policy,
    empty_runtime_execution_restriction,
    resolve_runtime_execution_policy,
)
from azents.core.runtime_provider_contract import (
    RuntimeProviderCapabilityContract,
    runtime_execution_capabilities_from_provider_contract,
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
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
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
class RuntimeExecutionCapabilitySummary:
    """One safe boolean execution capability summary."""

    module_id: RuntimeExecutionModuleId
    version: int
    enabled: bool


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionConfiguredSummary:
    """Current configured execution-policy summary."""

    profile_id: str
    digest: str
    capabilities: tuple[RuntimeExecutionCapabilitySummary, ...]
    storage_mode: RuntimeExecutionStorageMode
    storage_capacity_bytes: int | None
    network_mode: RuntimeExecutionNetworkMode


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionSnapshotSummary:
    """Safe immutable target or applied snapshot summary."""

    profile_id: str
    digest: str
    desired_generation: int
    capabilities: tuple[RuntimeExecutionCapabilitySummary, ...]
    storage_mode: RuntimeExecutionStorageMode
    storage_capacity_bytes: int | None
    network_mode: RuntimeExecutionNetworkMode


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionPolicyStatusProjection:
    """Server-authoritative read-only Runtime execution-policy projection."""

    status: RuntimeExecutionPolicyStatus
    configured: RuntimeExecutionConfiguredSummary
    target: RuntimeExecutionSnapshotSummary | None
    applied: RuntimeExecutionSnapshotSummary | None
    desired_generation: int
    governing_layers: dict[str, RuntimeExecutionPolicyLayer]
    reason_codes: tuple[str, ...]
    required_action: RuntimeExecutionRequiredAction


@dataclasses.dataclass(frozen=True)
class _ResolvedRuntimePolicy:
    """Locked resolution inputs and current immutable application state."""

    runtime: AgentRuntime
    target_snapshot: RuntimePolicySnapshot
    applied_snapshot: RuntimePolicySnapshot | None
    accepted_contract_revision_id: str
    provider_compatibility: dict[str, JsonValue]
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
    provider_repository: Annotated[
        RuntimeProviderRepository,
        Depends(RuntimeProviderRepository),
    ]
    agent_admin_repository: Annotated[
        AgentAdminRepository,
        Depends(AgentAdminRepository),
    ]

    async def get_status(
        self,
        *,
        agent_id: str,
    ) -> RuntimeExecutionPolicyStatusProjection:
        """Return a read-only server-derived execution-policy status."""
        async with self.session_manager() as session:
            resolved = await self._resolve_read(session, agent_id=agent_id)
        return _build_status_projection(resolved)

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
        else:
            source_versions = _snapshot_source_versions(target)
            profile_id = target.execution_profile_id
            execution_source_trace = target.execution_source_trace
        provider_compatibility = resolved.provider_compatibility

        next_generation = resolved.runtime.desired_generation + 1
        canonical_policy_json = canonical_runtime_execution_policy_json(
            effective_policy
        )
        execution_digest = digest_runtime_execution_policy(effective_policy)
        snapshot = await self.snapshot_repository.create_and_advance_target_snapshot(
            session,
            create=RuntimePolicySnapshotCreate(
                runtime_id=resolved.runtime.id,
                provider_id=target.provider_id,
                contract_revision_id=resolved.accepted_contract_revision_id,
                config_revision_id=target.config_revision_id,
                override_provider_id=target.override_provider_id,
                override_version=target.override_version,
                execution_profile_id=profile_id,
                execution_profile_version=source_versions.profile,
                execution_workspace_version=source_versions.workspace,
                execution_agent_version=source_versions.agent,
                resolved_execution_policy_json=canonical_policy_json,
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
        return await self._resolve(
            session,
            agent_id=agent_id,
            supplied_runtime=locked_runtime,
            for_update=True,
        )

    async def _resolve_read(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> _ResolvedRuntimePolicy:
        """Resolve current Runtime policy without locks or mutations."""
        return await self._resolve(
            session,
            agent_id=agent_id,
            supplied_runtime=None,
            for_update=False,
        )

    async def _resolve(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        supplied_runtime: AgentRuntime | None,
        for_update: bool,
    ) -> _ResolvedRuntimePolicy:
        runtime = supplied_runtime or (
            await self.runtime_repository.get_by_agent_id_for_update(
                session,
                agent_id,
            )
            if for_update
            else await self.runtime_repository.get_by_agent_id(
                session,
                agent_id,
            )
        )
        if runtime is None or runtime.runtime_provider_resource_id is None:
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "runtime_provider_binding_missing",
                agent_id,
            )
        provider = await self.provider_repository.get_by_id(
            session,
            provider_id=runtime.runtime_provider_resource_id,
            for_update=for_update,
        )
        if provider is None or provider.accepted_contract_revision_id is None:
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "runtime_provider_contract_unaccepted",
                runtime.runtime_provider_resource_id,
            )
        contract_revision = await self.snapshot_repository.get_contract_by_id(
            session,
            contract_revision_id=provider.accepted_contract_revision_id,
            for_update=False,
        )
        if (
            contract_revision is None
            or contract_revision.provider_id != provider.id
            or contract_revision.status is not RuntimeProviderContractStatus.ACCEPTED
        ):
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "runtime_provider_contract_unaccepted",
                provider.id,
            )
        try:
            provider_contract = RuntimeProviderCapabilityContract.model_validate(
                contract_revision.contract
            )
        except ValidationError as error:
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "runtime_provider_contract_invalid",
                provider.id,
            ) from error
        provider_capabilities = runtime_execution_capabilities_from_provider_contract(
            provider_contract
        )
        setting = await self.policy_repository.get_agent_setting(
            session,
            agent_id=agent_id,
            for_update=for_update,
        )
        workspace = await self.policy_repository.get_workspace(
            session,
            workspace_id=runtime.workspace_id,
            for_update=for_update,
        )
        if setting is None:
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "execution_policy_state_missing",
                agent_id,
            )
        profile = await self.policy_repository.get_profile(
            session,
            profile_id=setting.profile_id,
            for_update=for_update,
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
            for_update=for_update,
        )
        if target_snapshot is None:
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "runtime_policy_target_missing",
                runtime.id,
            )
        if (
            target_snapshot.contract_revision_id != contract_revision.id
            and target_snapshot.config_revision_id is not None
        ):
            raise RuntimeExecutionPolicyApplicationUnavailable(
                "runtime_provider_configuration_contract_stale",
                provider.id,
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
            profile_policy=profile.policy,
            workspace_restriction=workspace_restriction,
            agent_restriction=setting.restriction,
            source_versions=RuntimeExecutionSourceVersions(
                profile=profile.version,
                workspace=workspace.version if workspace is not None else 1,
                agent=setting.version,
            ),
            provider_capabilities=provider_capabilities,
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
            accepted_contract_revision_id=contract_revision.id,
            provider_compatibility=_provider_compatibility(
                contract_revision_id=contract_revision.id,
                contract_digest=contract_revision.digest,
                capabilities=provider_capabilities,
            ),
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
            contract_revision_id=resolved.accepted_contract_revision_id,
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
        canonical_policy_json = canonical_runtime_execution_policy_json(
            effective_policy
        )
        snapshot = await self.snapshot_repository.create_and_advance_target_snapshot(
            session,
            create=RuntimePolicySnapshotCreate(
                runtime_id=runtime.id,
                provider_id=resolved.target_snapshot.provider_id,
                contract_revision_id=resolved.accepted_contract_revision_id,
                config_revision_id=resolved.target_snapshot.config_revision_id,
                override_provider_id=resolved.target_snapshot.override_provider_id,
                override_version=resolved.target_snapshot.override_version,
                execution_profile_id=resolved.profile_id,
                execution_profile_version=source_versions.profile,
                execution_workspace_version=source_versions.workspace,
                execution_agent_version=source_versions.agent,
                resolved_execution_policy_json=canonical_policy_json,
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
                execution_provider_compatibility=resolved.provider_compatibility,
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


def _build_status_projection(
    resolved: _ResolvedRuntimePolicy,
) -> RuntimeExecutionPolicyStatusProjection:
    runtime = resolved.runtime
    resolution = resolved.resolution
    configured = _configured_summary(
        profile_id=resolved.profile_id,
        digest=resolution.digest,
        policy=resolution.effective_policy,
    )
    target = _snapshot_summary(resolved.target_snapshot)
    applied = _snapshot_summary(resolved.applied_snapshot)

    if not resolution.available:
        reason_codes = (
            (resolution.availability_reason.value,)
            if resolution.availability_reason is not None
            else ("execution_policy_unavailable",)
        )
        return RuntimeExecutionPolicyStatusProjection(
            status=RuntimeExecutionPolicyStatus.UNAVAILABLE,
            configured=configured,
            target=target,
            applied=applied,
            desired_generation=runtime.desired_generation,
            governing_layers=dict(resolution.governing_layers),
            reason_codes=reason_codes,
            required_action=RuntimeExecutionRequiredAction.ADMINISTRATOR_ACTION,
        )

    divergence = _divergence_reasons(resolved)
    if divergence:
        return RuntimeExecutionPolicyStatusProjection(
            status=RuntimeExecutionPolicyStatus.DIVERGENT,
            configured=configured,
            target=target,
            applied=applied,
            desired_generation=runtime.desired_generation,
            governing_layers=dict(resolution.governing_layers),
            reason_codes=divergence,
            required_action=RuntimeExecutionRequiredAction.ADMINISTRATOR_ACTION,
        )

    configured_matches_target = _snapshot_matches_target(
        resolved.target_snapshot,
        contract_revision_id=resolved.accepted_contract_revision_id,
        execution_digest=resolution.digest,
        source_versions=resolution.source_versions,
        desired_generation=runtime.desired_generation,
    )
    if not configured_matches_target:
        automatic = (
            resolution.change.direction is RuntimeExecutionChangeDirection.RESTRICTIVE
            and _automatic_convergence_source_allowed(resolved)
        )
        return RuntimeExecutionPolicyStatusProjection(
            status=(
                RuntimeExecutionPolicyStatus.PENDING
                if automatic
                else RuntimeExecutionPolicyStatus.CONFIGURED
            ),
            configured=configured,
            target=target,
            applied=applied,
            desired_generation=runtime.desired_generation,
            governing_layers=dict(resolution.governing_layers),
            reason_codes=(
                ("automatic_convergence_pending",)
                if automatic
                else ("explicit_apply_required",)
            ),
            required_action=(
                RuntimeExecutionRequiredAction.WAIT
                if automatic
                else RuntimeExecutionRequiredAction.APPLY
            ),
        )

    target_applied = (
        resolved.target_snapshot.application_state
        is RuntimePolicySnapshotApplicationState.APPLIED
        and resolved.applied_snapshot is not None
        and resolved.applied_snapshot.id == resolved.target_snapshot.id
    )
    return RuntimeExecutionPolicyStatusProjection(
        status=(
            RuntimeExecutionPolicyStatus.APPLIED
            if target_applied
            else RuntimeExecutionPolicyStatus.PENDING
        ),
        configured=configured,
        target=target,
        applied=applied,
        desired_generation=runtime.desired_generation,
        governing_layers=dict(resolution.governing_layers),
        reason_codes=() if target_applied else ("application_pending",),
        required_action=(
            RuntimeExecutionRequiredAction.NONE
            if target_applied
            else RuntimeExecutionRequiredAction.WAIT
        ),
    )


def _divergence_reasons(resolved: _ResolvedRuntimePolicy) -> tuple[str, ...]:
    runtime = resolved.runtime
    target = resolved.target_snapshot
    applied = resolved.applied_snapshot
    reasons: list[str] = []
    if target.application_state is RuntimePolicySnapshotApplicationState.DIVERGENT:
        reasons.append("target_divergent")
    if (
        target.execution_reported_digest is not None
        and target.execution_reported_digest != target.execution_target_digest
    ):
        reasons.append("reported_digest_mismatch")
    if target.target_desired_generation != runtime.desired_generation:
        reasons.append("target_generation_mismatch")
    if (
        runtime.failure_generation == runtime.desired_generation
        and runtime.failure_code is not None
        and target.application_state
        is not RuntimePolicySnapshotApplicationState.APPLIED
    ):
        reasons.append(runtime.failure_code)
    if runtime.applied_runtime_policy_snapshot_id is not None:
        if applied is None:
            reasons.append("applied_snapshot_missing")
        elif (
            applied.application_state
            is not RuntimePolicySnapshotApplicationState.APPLIED
        ):
            reasons.append("applied_snapshot_unverified")
    if (
        target.application_state is RuntimePolicySnapshotApplicationState.APPLIED
        and runtime.applied_runtime_policy_snapshot_id != target.id
    ):
        reasons.append("applied_pointer_mismatch")
    return tuple(dict.fromkeys(reasons))


def _configured_summary(
    *,
    profile_id: str,
    digest: str,
    policy: RuntimeExecutionPolicyDocument,
) -> RuntimeExecutionConfiguredSummary:
    return RuntimeExecutionConfiguredSummary(
        profile_id=profile_id,
        digest=digest,
        capabilities=_capability_summaries(policy),
        storage_mode=policy.engine_storage.mode,
        storage_capacity_bytes=policy.engine_storage.capacity_bytes,
        network_mode=policy.network_egress.mode,
    )


def _snapshot_summary(
    snapshot: RuntimePolicySnapshot | None,
) -> RuntimeExecutionSnapshotSummary | None:
    policy = _snapshot_policy(snapshot)
    if (
        snapshot is None
        or policy is None
        or snapshot.execution_profile_id is None
        or snapshot.execution_target_digest is None
    ):
        return None
    return RuntimeExecutionSnapshotSummary(
        profile_id=snapshot.execution_profile_id,
        digest=snapshot.execution_target_digest,
        desired_generation=snapshot.target_desired_generation,
        capabilities=_capability_summaries(policy),
        storage_mode=policy.engine_storage.mode,
        storage_capacity_bytes=policy.engine_storage.capacity_bytes,
        network_mode=policy.network_egress.mode,
    )


def _capability_summaries(
    policy: RuntimeExecutionPolicyDocument,
) -> tuple[RuntimeExecutionCapabilitySummary, ...]:
    return tuple(
        RuntimeExecutionCapabilitySummary(
            module_id=module.module_id,
            version=module.version,
            enabled=module.enabled,
        )
        for module in (policy.image_build, policy.container_run, policy.compose)
    )


def _snapshot_policy(
    snapshot: RuntimePolicySnapshot | None,
) -> RuntimeExecutionPolicyDocument | None:
    if snapshot is None or snapshot.resolved_execution_policy_json is None:
        return None
    return RuntimeExecutionPolicyDocument.model_validate_json(
        snapshot.resolved_execution_policy_json
    )


def _snapshot_source_versions(
    snapshot: RuntimePolicySnapshot,
) -> RuntimeExecutionSourceVersions:
    values = (
        snapshot.execution_profile_version,
        snapshot.execution_workspace_version,
        snapshot.execution_agent_version,
    )
    if any(value is None for value in values):
        raise RuntimeExecutionPolicyApplicationUnavailable(
            "runtime_policy_target_incomplete",
            snapshot.id,
        )
    profile, workspace, agent = values
    assert profile is not None
    assert workspace is not None
    assert agent is not None
    return RuntimeExecutionSourceVersions(
        profile=profile,
        workspace=workspace,
        agent=agent,
    )


def _snapshot_matches_target(
    snapshot: RuntimePolicySnapshot,
    *,
    contract_revision_id: str,
    execution_digest: str,
    source_versions: RuntimeExecutionSourceVersions,
    desired_generation: int,
) -> bool:
    return (
        snapshot.contract_revision_id == contract_revision_id
        and snapshot.execution_target_digest == execution_digest
        and snapshot.target_desired_generation == desired_generation
        and snapshot.execution_profile_version == source_versions.profile
        and snapshot.execution_workspace_version == source_versions.workspace
        and snapshot.execution_agent_version == source_versions.agent
    )


def _provider_compatibility(
    *,
    contract_revision_id: str,
    contract_digest: str,
    capabilities: RuntimeExecutionProviderCapabilities,
) -> dict[str, JsonValue]:
    """Build the safe accepted-contract evidence stored with a snapshot."""
    supported_modules: list[JsonValue] = [
        {
            "module_id": support.module_id.value,
            "version": support.version,
        }
        for support in sorted(
            capabilities.supported_modules,
            key=lambda item: (item.module_id.value, item.version),
        )
    ]
    storage_modes: list[JsonValue] = [
        mode.value for mode in sorted(capabilities.storage_modes)
    ]
    network_modes: list[JsonValue] = [
        mode.value for mode in sorted(capabilities.network_modes)
    ]
    return {
        "mode": "accepted_contract",
        "contract_revision_id": contract_revision_id,
        "contract_digest": contract_digest,
        "authority_bearing_policy_supported": capabilities.privileged_engine,
        "supported_modules": supported_modules,
        "storage_modes": storage_modes,
        "network_modes": network_modes,
    }


def _automatic_convergence_source_allowed(
    resolved: _ResolvedRuntimePolicy,
) -> bool:
    """Allow system convergence while the Agent's selected intent is unchanged."""
    source_versions = resolved.resolution.source_versions
    target = resolved.target_snapshot
    return target.execution_agent_version == source_versions.agent


def _restrictive_projection(
    applied: RuntimeExecutionPolicyDocument,
    current: RuntimeExecutionPolicyDocument,
    change: RuntimeExecutionChangeSummary,
) -> RuntimeExecutionPolicyDocument:
    projected = canonical_runtime_execution_policy(applied)
    current_values = canonical_runtime_execution_policy(current)
    if not isinstance(projected, dict) or not isinstance(current_values, dict):
        raise AssertionError("Canonical execution policies must be objects.")
    atomic_modules = {
        field.path.split(".", 1)[0]
        for field in change.fields
        if field.direction is RuntimeExecutionChangeDirection.RESTRICTIVE
        and field.path in {"engine_storage.mode", "network_egress.mode"}
    }
    for module in atomic_modules:
        projected[module] = current_values[module]
    for field in change.fields:
        if field.direction is RuntimeExecutionChangeDirection.RESTRICTIVE:
            if field.path.split(".", 1)[0] in atomic_modules:
                continue
            _copy_path(projected, current_values, field.path.split("."))
    _normalize_projected_resource_pairs(projected)
    return RuntimeExecutionPolicyDocument.model_validate(projected)


def _normalize_projected_resource_pairs(policy: dict[str, JsonValue]) -> None:
    """Keep selectively projected Kubernetes requests within their limits."""
    resources = policy.get("resources")
    if not isinstance(resources, dict):
        raise ValueError("Execution-policy resources module is invalid.")
    for request_name, limit_name in (
        ("cpu_request_millicores", "cpu_limit_millicores"),
        ("memory_request_bytes", "memory_limit_bytes"),
    ):
        request = resources.get(request_name)
        limit = resources.get(limit_name)
        if isinstance(request, int) and isinstance(limit, int) and request > limit:
            resources[request_name] = limit


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
