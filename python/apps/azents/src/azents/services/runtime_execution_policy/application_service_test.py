"""Runtime execution-policy application and convergence tests."""

# pyright: reportPrivateUsage=false

import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimePolicySnapshotApplicationState,
    WorkspaceUserRole,
)
from azents.core.runtime_execution_policy import (
    RuntimeExecutionAvailabilityReason,
    RuntimeExecutionChangeDirection,
    RuntimeExecutionDockerModule,
    RuntimeExecutionModuleId,
    RuntimeExecutionModuleSupport,
    RuntimeExecutionPolicyStatus,
    RuntimeExecutionProfileLifecycle,
    RuntimeExecutionProviderCapabilities,
    RuntimeExecutionRequiredAction,
    RuntimeExecutionSourceVersions,
    RuntimeExecutionStorageMode,
    canonical_runtime_execution_policy_json,
    classify_runtime_execution_change,
    digest_runtime_execution_policy,
    empty_runtime_execution_restriction,
    resolve_runtime_execution_policy,
    standard_runtime_execution_policy,
)
from azents.core.runtime_provider_contract import RuntimeProviderCapabilityContract
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_execution_policy.data import (
    AgentRuntimeExecutionSetting,
    RuntimeExecutionProfile,
)
from azents.repos.runtime_provider_policy.data import (
    RuntimePolicySnapshot,
    RuntimeProviderContractRevision,
)

from .application_service import (
    RuntimeExecutionPolicyApplicationService,
    RuntimeExecutionPolicyApplicationUnavailable,
    _automatic_convergence_source_allowed,
    _build_status_projection,
    _ResolvedRuntimePolicy,
    _restrictive_projection,
)

_NOW = datetime.datetime.now(datetime.timezone.utc)
_REGION_CONFIGURATION_FIELD: dict[str, object] = {
    "name": "region",
    "scope": "platform",
    "type": "string",
    "application_impact": "immediate",
}


def _provider_contract_revision(
    revision_id: str,
    *,
    configuration_fields: list[dict[str, object]],
) -> RuntimeProviderContractRevision:
    """Build one Provider contract revision for configuration-schema tests."""
    contract = {
        "schema_version": 1,
        "implementation_key": "kubernetes",
        "implementation_version": revision_id,
        "protocol_version": "agent-runtime-provider-kubernetes-v1",
        "core_lifecycle_operations": [
            "start",
            "stop",
            "restart",
            "reset",
            "observe",
            "terminal_delete",
        ],
        "persistence": {
            "kind": "persistent",
            "reset_destroys_workspace": True,
            "terminal_delete_destroys_workspace": True,
        },
        "configuration_fields": configuration_fields,
    }
    return RuntimeProviderContractRevision(
        id=revision_id,
        provider_id="provider-1",
        digest=revision_id.removeprefix("contract-").rjust(64, "0"),
        implementation_version=revision_id,
        protocol_version="agent-runtime-provider-kubernetes-v1",
        contract=contract,
        compatibility={},
        created_at=_NOW,
    )


def _legacy_provider_capabilities() -> RuntimeExecutionProviderCapabilities:
    """Model a Provider that supports only the Standard Profile."""
    return RuntimeExecutionProviderCapabilities(
        supported_modules=frozenset(),
        storage_modes=frozenset({RuntimeExecutionStorageMode.NONE}),
        resource_maxima=None,
    )


def _direct_provider_capabilities() -> RuntimeExecutionProviderCapabilities:
    """Model a Provider that supports Kubernetes Runtime resources."""
    return RuntimeExecutionProviderCapabilities(
        supported_modules=frozenset(
            (
                RuntimeExecutionModuleSupport(
                    module_id=RuntimeExecutionModuleId.RESOURCES, version=1
                ),
            )
        ),
        storage_modes=frozenset({RuntimeExecutionStorageMode.NONE}),
        resource_maxima=None,
    )


def _engine_provider_capabilities() -> RuntimeExecutionProviderCapabilities:
    """Model a Provider that supports temporary Docker storage."""
    return RuntimeExecutionProviderCapabilities(
        supported_modules=frozenset(
            (
                RuntimeExecutionModuleSupport(
                    module_id=RuntimeExecutionModuleId.DOCKER, version=1
                ),
                RuntimeExecutionModuleSupport(
                    module_id=RuntimeExecutionModuleId.RESOURCES, version=1
                ),
            )
        ),
        storage_modes=frozenset(
            {RuntimeExecutionStorageMode.NONE, RuntimeExecutionStorageMode.EPHEMERAL}
        ),
        resource_maxima=None,
    )


@asynccontextmanager
async def _session_manager() -> AsyncIterator[Mock]:
    yield Mock()


def _runtime() -> AgentRuntime:
    return AgentRuntime(
        id="runtime-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        runtime_provider_id="provider-logical-1",
        runtime_provider_resource_id="provider-1",
        runtime_policy_snapshot_id="snapshot-1",
        desired_state=RuntimeDesiredState.RUNNING,
        desired_generation=2,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _snapshot() -> RuntimePolicySnapshot:
    return RuntimePolicySnapshot(
        id="snapshot-1",
        runtime_id="runtime-1",
        provider_id="provider-1",
        contract_revision_id="contract-1",
        config_revision_id=None,
        override_provider_id=None,
        override_version=None,
        execution_profile_id=None,
        execution_profile_version=None,
        execution_workspace_version=None,
        execution_agent_version=None,
        resolved_execution_policy_json=None,
        execution_source_trace=None,
        execution_provider_compatibility=None,
        execution_target_digest=None,
        execution_reported_digest=None,
        resolved_config={},
        encrypted_secrets=None,
        secret_metadata={},
        source_trace={},
        digest="a" * 64,
        target_desired_generation=2,
        application_state=RuntimePolicySnapshotApplicationState.PENDING,
        provider_acknowledged_at=None,
        runtime_observed_at=None,
        created_at=_NOW,
    )


def _resolved() -> _ResolvedRuntimePolicy:
    standard = standard_runtime_execution_policy()
    resolution = resolve_runtime_execution_policy(
        profile_policy=standard,
        workspace_restriction=empty_runtime_execution_restriction(),
        agent_restriction=empty_runtime_execution_restriction(),
        source_versions=RuntimeExecutionSourceVersions(
            profile=2,
            workspace=3,
            agent=4,
        ),
        provider_capabilities=_direct_provider_capabilities(),
        profile_active=True,
        profile_allowed=True,
        applied_policy=None,
    )
    assert resolution.available
    return _ResolvedRuntimePolicy(
        runtime=_runtime(),
        target_snapshot=_snapshot(),
        applied_snapshot=None,
        current_contract_revision_id="contract-1",
        provider_compatibility={
            "mode": "current_contract",
            "contract_revision_id": "contract-1",
        },
        profile_id="system-standard",
        resolution=resolution,
    )


def _unavailable_resolved() -> _ResolvedRuntimePolicy:
    policy = standard_runtime_execution_policy()
    unavailable = resolve_runtime_execution_policy(
        profile_policy=policy,
        workspace_restriction=empty_runtime_execution_restriction(),
        agent_restriction=empty_runtime_execution_restriction(),
        source_versions=RuntimeExecutionSourceVersions(
            profile=2,
            workspace=3,
            agent=4,
        ),
        provider_capabilities=_direct_provider_capabilities(),
        profile_active=False,
        profile_allowed=True,
        applied_policy=policy,
    )
    assert not unavailable.available
    resolved = _resolved()
    return dataclasses.replace(
        resolved,
        target_snapshot=dataclasses.replace(
            resolved.target_snapshot,
            execution_profile_id="system-standard",
            execution_profile_version=2,
            execution_workspace_version=3,
            execution_agent_version=4,
            resolved_execution_policy_json=(
                canonical_runtime_execution_policy_json(policy)
            ),
            execution_source_trace={},
            execution_provider_compatibility={},
            execution_target_digest=digest_runtime_execution_policy(policy),
        ),
        resolution=unavailable,
    )


def _targeted_resolved(
    *,
    state: RuntimePolicySnapshotApplicationState,
    applied: bool,
) -> _ResolvedRuntimePolicy:
    resolved = _resolved()
    policy = resolved.resolution.effective_policy
    snapshot = dataclasses.replace(
        resolved.target_snapshot,
        execution_profile_id=resolved.profile_id,
        execution_profile_version=resolved.resolution.source_versions.profile,
        execution_workspace_version=resolved.resolution.source_versions.workspace,
        execution_agent_version=resolved.resolution.source_versions.agent,
        resolved_execution_policy_json=canonical_runtime_execution_policy_json(policy),
        execution_source_trace={},
        execution_provider_compatibility={},
        execution_target_digest=resolved.resolution.digest,
        execution_reported_digest=(
            resolved.resolution.digest
            if state is RuntimePolicySnapshotApplicationState.APPLIED
            else None
        ),
        application_state=state,
    )
    runtime = resolved.runtime.model_copy(
        update={
            "applied_runtime_policy_snapshot_id": snapshot.id if applied else None,
        }
    )
    return dataclasses.replace(
        resolved,
        runtime=runtime,
        target_snapshot=snapshot,
        applied_snapshot=snapshot if applied else None,
    )


def _upper_layer_change_resolved(
    *,
    current_cpu: int,
    current_memory: int,
    source_versions: RuntimeExecutionSourceVersions,
    target_source_versions: RuntimeExecutionSourceVersions,
) -> _ResolvedRuntimePolicy:
    baseline = standard_runtime_execution_policy()
    baseline = baseline.model_copy(
        update={
            "resources": baseline.resources.model_copy(
                update={
                    "cpu_limit_millicores": 500,
                    "memory_limit_bytes": 1_000,
                }
            )
        }
    )
    current = baseline.model_copy(
        update={
            "resources": baseline.resources.model_copy(
                update={
                    "cpu_limit_millicores": current_cpu,
                    "memory_limit_bytes": current_memory,
                }
            )
        }
    )
    resolution = resolve_runtime_execution_policy(
        profile_policy=current,
        workspace_restriction=empty_runtime_execution_restriction(),
        agent_restriction=empty_runtime_execution_restriction(),
        source_versions=source_versions,
        provider_capabilities=_direct_provider_capabilities(),
        profile_active=True,
        profile_allowed=True,
        applied_policy=baseline,
    )
    target_digest = digest_runtime_execution_policy(baseline)
    target = dataclasses.replace(
        _snapshot(),
        execution_profile_id="system-standard",
        execution_profile_version=target_source_versions.profile,
        execution_workspace_version=target_source_versions.workspace,
        execution_agent_version=target_source_versions.agent,
        resolved_execution_policy_json=canonical_runtime_execution_policy_json(
            baseline
        ),
        execution_source_trace={},
        execution_provider_compatibility={},
        execution_target_digest=target_digest,
        execution_reported_digest=target_digest,
        application_state=RuntimePolicySnapshotApplicationState.APPLIED,
    )
    runtime = _runtime().model_copy(
        update={"applied_runtime_policy_snapshot_id": target.id}
    )
    return _ResolvedRuntimePolicy(
        runtime=runtime,
        target_snapshot=target,
        applied_snapshot=target,
        current_contract_revision_id="contract-1",
        provider_compatibility={
            "mode": "current_contract",
            "contract_revision_id": "contract-1",
        },
        profile_id="system-standard",
        resolution=resolution,
    )


def _storage_expansion_resolved() -> _ResolvedRuntimePolicy:
    """Return a Runtime whose remaining change enables Docker authority."""
    standard = standard_runtime_execution_policy()
    applied_policy = standard.model_copy(
        update={
            "resources": standard.resources.model_copy(
                update={"ephemeral_storage_bytes": 17_179_869_184}
            )
        }
    )
    current_policy = applied_policy.model_copy(
        update={
            "docker": RuntimeExecutionDockerModule(
                module_id=RuntimeExecutionModuleId.DOCKER,
                version=1,
                enabled=True,
                storage_mode=RuntimeExecutionStorageMode.EPHEMERAL,
                storage_capacity_bytes=17_179_869_184,
            ),
        }
    )
    source_versions = RuntimeExecutionSourceVersions(
        profile=4,
        workspace=3,
        agent=4,
    )
    resolution = resolve_runtime_execution_policy(
        profile_policy=current_policy,
        workspace_restriction=empty_runtime_execution_restriction(),
        agent_restriction=empty_runtime_execution_restriction(),
        source_versions=source_versions,
        provider_capabilities=_engine_provider_capabilities(),
        profile_active=True,
        profile_allowed=True,
        applied_policy=applied_policy,
    )
    target_digest = digest_runtime_execution_policy(applied_policy)
    target = dataclasses.replace(
        _snapshot(),
        execution_profile_id="system-standard",
        execution_profile_version=source_versions.profile,
        execution_workspace_version=source_versions.workspace,
        execution_agent_version=source_versions.agent,
        resolved_execution_policy_json=canonical_runtime_execution_policy_json(
            applied_policy
        ),
        execution_source_trace={},
        execution_provider_compatibility={},
        execution_target_digest=target_digest,
        execution_reported_digest=target_digest,
        application_state=RuntimePolicySnapshotApplicationState.APPLIED,
    )
    runtime = _runtime().model_copy(
        update={"applied_runtime_policy_snapshot_id": target.id}
    )
    return _ResolvedRuntimePolicy(
        runtime=runtime,
        target_snapshot=target,
        applied_snapshot=target,
        current_contract_revision_id="contract-1",
        provider_compatibility={
            "mode": "current_contract",
            "contract_revision_id": "contract-1",
        },
        profile_id="system-standard",
        resolution=resolution,
    )


def test_status_projection_requires_explicit_apply_for_saved_intent() -> None:
    """A configured intent mismatch is not presented as applied."""
    status = _build_status_projection(_resolved())

    assert status.status is RuntimeExecutionPolicyStatus.CONFIGURED
    assert status.required_action is RuntimeExecutionRequiredAction.APPLY
    assert status.reason_codes == ("explicit_apply_required",)


@pytest.mark.parametrize(
    ("source_versions", "target_source_versions"),
    [
        (
            RuntimeExecutionSourceVersions(
                profile=2,
                workspace=3,
                agent=4,
            ),
            RuntimeExecutionSourceVersions(
                profile=2,
                workspace=3,
                agent=4,
            ),
        ),
        (
            RuntimeExecutionSourceVersions(
                profile=2,
                workspace=4,
                agent=4,
            ),
            RuntimeExecutionSourceVersions(
                profile=2,
                workspace=3,
                agent=4,
            ),
        ),
    ],
)
def test_status_projection_requires_apply_for_upper_layer_expansion(
    source_versions: RuntimeExecutionSourceVersions,
    target_source_versions: RuntimeExecutionSourceVersions,
) -> None:
    """Platform or Workspace expansion never waits for automatic convergence."""
    status = _build_status_projection(
        _upper_layer_change_resolved(
            current_cpu=1_000,
            current_memory=1_000,
            source_versions=source_versions,
            target_source_versions=target_source_versions,
        )
    )

    assert status.status is RuntimeExecutionPolicyStatus.CONFIGURED
    assert status.required_action is RuntimeExecutionRequiredAction.APPLY
    assert status.reason_codes == ("explicit_apply_required",)


def test_status_projection_waits_while_mixed_change_removes_authority() -> None:
    """Mixed changes converge their restrictive subset before offering expansion."""
    status = _build_status_projection(
        _upper_layer_change_resolved(
            current_cpu=1_000,
            current_memory=500,
            source_versions=RuntimeExecutionSourceVersions(
                profile=2,
                workspace=3,
                agent=4,
            ),
            target_source_versions=RuntimeExecutionSourceVersions(
                profile=2,
                workspace=3,
                agent=4,
            ),
        )
    )

    assert status.status is RuntimeExecutionPolicyStatus.PENDING
    assert status.required_action is RuntimeExecutionRequiredAction.WAIT
    assert status.reason_codes == ("automatic_convergence_pending",)


def test_status_projection_offers_apply_after_restrictive_subset_converges() -> None:
    """A module expansion does not remain stuck in automatic convergence."""
    status = _build_status_projection(_storage_expansion_resolved())

    assert status.status is RuntimeExecutionPolicyStatus.CONFIGURED
    assert status.required_action is RuntimeExecutionRequiredAction.APPLY
    assert status.reason_codes == ("explicit_apply_required",)


def test_status_projection_marks_exact_target_pending_until_evidence() -> None:
    """An exact target remains pending before Provider and Runner evidence."""
    status = _build_status_projection(
        _targeted_resolved(
            state=RuntimePolicySnapshotApplicationState.PENDING,
            applied=False,
        )
    )

    assert status.status is RuntimeExecutionPolicyStatus.PENDING
    assert status.required_action is RuntimeExecutionRequiredAction.WAIT
    assert status.target is not None
    assert status.applied is None


def test_status_projection_recovers_pending_historical_applied_snapshot() -> None:
    """Migrated historical evidence does not become a user-actionable divergence."""
    status = _build_status_projection(
        _targeted_resolved(
            state=RuntimePolicySnapshotApplicationState.PENDING,
            applied=True,
        )
    )

    assert status.status is RuntimeExecutionPolicyStatus.PENDING
    assert status.required_action is RuntimeExecutionRequiredAction.WAIT
    assert status.reason_codes == ("application_pending",)


def test_status_projection_marks_only_promoted_exact_target_applied() -> None:
    """Applied status requires the exact promoted target pointer."""
    status = _build_status_projection(
        _targeted_resolved(
            state=RuntimePolicySnapshotApplicationState.APPLIED,
            applied=True,
        )
    )

    assert status.status is RuntimeExecutionPolicyStatus.APPLIED
    assert status.required_action is RuntimeExecutionRequiredAction.NONE
    assert status.applied is not None
    assert status.applied.digest == status.configured.digest


def test_status_projection_preserves_bounded_unavailability_reason() -> None:
    """Unavailable configured intent exposes only a bounded reason code."""
    status = _build_status_projection(_unavailable_resolved())

    assert status.status is RuntimeExecutionPolicyStatus.UNAVAILABLE
    assert status.required_action is RuntimeExecutionRequiredAction.ADMINISTRATOR_ACTION
    assert status.reason_codes == ("profile_retired",)


def test_status_projection_marks_snapshot_divergence() -> None:
    """A divergent target is never presented as pending or applied."""
    resolved = _targeted_resolved(
        state=RuntimePolicySnapshotApplicationState.DIVERGENT,
        applied=False,
    )

    status = _build_status_projection(resolved)

    assert status.status is RuntimeExecutionPolicyStatus.DIVERGENT
    assert status.required_action is RuntimeExecutionRequiredAction.ADMINISTRATOR_ACTION
    assert status.reason_codes == ("target_divergent",)


async def test_resolve_uses_current_contract_engine_capabilities() -> None:
    """Runtime resolution consumes typed authority from the current contract."""
    base = standard_runtime_execution_policy()
    docker_policy = base.model_copy(
        update={
            "docker": RuntimeExecutionDockerModule(
                module_id=RuntimeExecutionModuleId.DOCKER,
                version=1,
                enabled=True,
                storage_mode=RuntimeExecutionStorageMode.EPHEMERAL,
                storage_capacity_bytes=8_589_934_592,
            ),
            "resources": base.resources.model_copy(
                update={
                    "cpu_limit_millicores": 1_000,
                    "memory_limit_bytes": 1_073_741_824,
                    "ephemeral_storage_bytes": 8_589_934_592,
                }
            ),
        }
    )
    profile = RuntimeExecutionProfile(
        id="nested-engine",
        display_name="Nested engine",
        description="Qualified engine profile",
        lifecycle=RuntimeExecutionProfileLifecycle.ACTIVE,
        version=1,
        policy=docker_policy,
        digest=digest_runtime_execution_policy(docker_policy),
        reserved=False,
        system_key=None,
        updated_by_user_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    setting = AgentRuntimeExecutionSetting(
        agent_id="agent-1",
        profile_id=profile.id,
        version=1,
        restriction=empty_runtime_execution_restriction(),
        digest=digest_runtime_execution_policy(empty_runtime_execution_restriction()),
        updated_by_workspace_user_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    provider = Mock()
    provider.id = "provider-1"
    provider.current_contract_revision_id = "contract-2"
    contract_revision = Mock()
    contract_revision.id = "contract-2"
    contract_revision.provider_id = "provider-1"
    contract_revision.digest = "c" * 64
    contract_revision.contract = {
        "schema_version": 1,
        "implementation_key": "kubernetes",
        "implementation_version": "0.1.0",
        "protocol_version": "agent-runtime-provider-kubernetes-v1",
        "core_lifecycle_operations": [
            "start",
            "stop",
            "restart",
            "reset",
            "observe",
            "terminal_delete",
        ],
        "optional_capabilities": ["execution_policy_v1"],
        "persistence": {
            "kind": "persistent",
            "reset_destroys_workspace": True,
            "terminal_delete_destroys_workspace": True,
        },
        "configuration_fields": [],
        "execution_policy": {
            "schema_version": 1,
            "supported_modules": [
                {
                    "module_id": module_id.value,
                    "version": 1,
                }
                for module_id in RuntimeExecutionModuleId
            ],
            "storage_modes": ["none", "ephemeral"],
            "resource_maxima": None,
        },
    }
    configuration_fields = [
        {
            "name": "region",
            "scope": "platform",
            "type": "string",
            "application_impact": "immediate",
        }
    ]
    contract_revision.contract["configuration_fields"] = configuration_fields
    validated_contract_revision = Mock()
    validated_contract_revision.id = "contract-1"
    validated_contract_revision.provider_id = "provider-1"
    validated_contract_revision.contract = {
        **contract_revision.contract,
        "implementation_version": "0.0.9",
        "configuration_fields": configuration_fields,
    }
    policy_repository = Mock()
    workspace = Mock()
    workspace.restriction = empty_runtime_execution_restriction()
    workspace.allowed_profile_ids = frozenset({profile.id})
    workspace.version = 1
    policy_repository.get_agent_setting = AsyncMock(return_value=setting)
    policy_repository.get_workspace = AsyncMock(return_value=workspace)
    policy_repository.get_profile = AsyncMock(return_value=profile)
    snapshot_repository = Mock()
    snapshot_repository.get_contract_by_id = AsyncMock(
        side_effect=[contract_revision, validated_contract_revision]
    )
    snapshot_repository.get_snapshot = AsyncMock(
        return_value=dataclasses.replace(
            _snapshot(),
            config_revision_id="config-1",
        )
    )
    runtime_repository = Mock()
    runtime_repository.get_by_agent_id = AsyncMock(return_value=_runtime())
    provider_repository = Mock()
    provider_repository.get_by_id = AsyncMock(return_value=provider)
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=_session_manager,
        policy_repository=policy_repository,
        snapshot_repository=snapshot_repository,
        runtime_repository=runtime_repository,
        provider_repository=provider_repository,
        agent_admin_repository=Mock(),
    )

    resolved = await service._resolve_read(Mock(), agent_id="agent-1")

    assert resolved.resolution.available
    assert resolved.current_contract_revision_id == "contract-2"
    assert resolved.provider_compatibility["docker_supported"]


@pytest.mark.parametrize(
    (
        "current_fields",
        "validated_fields",
        "config_revision_id",
        "validated_revision_exists",
    ),
    [
        ([_REGION_CONFIGURATION_FIELD], [], None, True),
        ([], [_REGION_CONFIGURATION_FIELD], "config-1", True),
        (
            [_REGION_CONFIGURATION_FIELD],
            [_REGION_CONFIGURATION_FIELD],
            "config-1",
            False,
        ),
    ],
)
async def test_target_configuration_schema_transitions_fail_closed(
    current_fields: list[dict[str, object]],
    validated_fields: list[dict[str, object]],
    config_revision_id: str | None,
    validated_revision_exists: bool,
) -> None:
    """Schema transitions and missing history cannot reuse stale target evidence."""
    current_revision = _provider_contract_revision(
        "contract-2",
        configuration_fields=current_fields,
    )
    validated_revision = _provider_contract_revision(
        "contract-1",
        configuration_fields=validated_fields,
    )
    snapshot_repository = Mock()
    snapshot_repository.get_contract_by_id = AsyncMock(
        return_value=validated_revision if validated_revision_exists else None
    )
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=_session_manager,
        policy_repository=Mock(),
        snapshot_repository=snapshot_repository,
        runtime_repository=Mock(),
        provider_repository=Mock(),
        agent_admin_repository=Mock(),
    )
    target_snapshot = dataclasses.replace(
        _snapshot(),
        contract_revision_id=validated_revision.id,
        config_revision_id=config_revision_id,
    )

    with pytest.raises(
        RuntimeExecutionPolicyApplicationUnavailable,
        match="runtime_provider_configuration_contract_stale",
    ):
        await service._validate_target_configuration_contract(
            Mock(),
            provider_id="provider-1",
            current_contract_revision=current_revision,
            current_contract=RuntimeProviderCapabilityContract.model_validate(
                current_revision.contract
            ),
            target_snapshot=target_snapshot,
        )


async def test_status_read_uses_read_resolver_without_target_mutation() -> None:
    """Status reads never call target creation or convergence paths."""
    snapshot_repository = Mock()
    snapshot_repository.create_and_advance_target_snapshot = AsyncMock()
    policy_repository = Mock()
    policy_repository.append_audit_event = AsyncMock()
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=_session_manager,
        policy_repository=policy_repository,
        snapshot_repository=snapshot_repository,
        runtime_repository=Mock(),
        provider_repository=Mock(),
        agent_admin_repository=Mock(),
    )
    service._resolve_read = AsyncMock(return_value=_resolved())

    status = await service.get_status(agent_id="agent-1")

    assert status.status is RuntimeExecutionPolicyStatus.CONFIGURED
    service._resolve_read.assert_awaited_once()
    snapshot_repository.create_and_advance_target_snapshot.assert_not_awaited()
    policy_repository.append_audit_event.assert_not_awaited()


async def test_apply_requires_existing_agent_management_authority() -> None:
    policy_repository = Mock()
    policy_repository.get_agent_workspace_id = AsyncMock(return_value="workspace-1")
    agent_admin_repository = Mock()
    agent_admin_repository.is_admin = AsyncMock(return_value=False)
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=_session_manager,
        policy_repository=policy_repository,
        snapshot_repository=Mock(),
        runtime_repository=Mock(),
        provider_repository=Mock(),
        agent_admin_repository=agent_admin_repository,
    )

    with pytest.raises(
        RuntimeExecutionPolicyApplicationUnavailable,
        match="agent_access_denied",
    ):
        await service.apply_agent_for_manager(
            agent_id="agent-1",
            workspace_id="workspace-1",
            workspace_user_id="workspace-user-1",
            role=WorkspaceUserRole.MEMBER,
            actor_workspace_user_id="workspace-user-1",
            correlation_id="apply-1",
        )


async def test_explicit_apply_creates_next_generation_target_atomically() -> None:
    policy_repository = Mock()
    policy_repository.append_audit_event = AsyncMock()
    snapshot_repository = Mock()
    created_snapshot = _snapshot()
    created_snapshot = dataclasses.replace(
        created_snapshot,
        id="snapshot-2",
        target_desired_generation=3,
        execution_target_digest="b" * 64,
    )
    snapshot_repository.create_and_advance_target_snapshot = AsyncMock(
        return_value=created_snapshot
    )
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=Mock(),
        policy_repository=policy_repository,
        snapshot_repository=snapshot_repository,
        runtime_repository=Mock(),
        provider_repository=Mock(),
        agent_admin_repository=Mock(),
    )
    resolved = dataclasses.replace(
        _resolved(),
        current_contract_revision_id="contract-2",
        provider_compatibility={
            "mode": "current_contract",
            "contract_revision_id": "contract-2",
        },
    )

    result = await service._target_resolution(
        Mock(),
        resolved=resolved,
        effective_policy=resolved.resolution.effective_policy,
        classification=RuntimeExecutionChangeDirection.APPLICATION,
        actor_workspace_user_id="workspace-user-1",
        correlation_id="apply-1",
        system_authority=False,
        reason_code="agent_apply",
    )

    assert result.created
    call = snapshot_repository.create_and_advance_target_snapshot.await_args
    assert call.kwargs["create"].target_desired_generation == 3
    assert call.kwargs["create"].contract_revision_id == "contract-2"
    assert call.kwargs["create"].execution_provider_compatibility == (
        resolved.provider_compatibility
    )
    assert call.kwargs["expected_target_snapshot_id"] == "snapshot-1"
    assert call.kwargs["lifecycle_command"] is RuntimeLifecycleCommandType.RESTART
    policy_repository.append_audit_event.assert_awaited_once()


async def test_terminal_delete_targets_next_generation_with_bound_snapshot() -> None:
    """Terminal deletion advances one exact snapshot generation atomically."""
    resolved = _resolved()
    snapshot_repository = Mock()
    snapshot_repository.create_and_advance_target_snapshot = AsyncMock(
        return_value=dataclasses.replace(
            _snapshot(),
            id="snapshot-2",
            target_desired_generation=3,
        )
    )
    runtime_repository = Mock()
    runtime_repository.get_by_id = AsyncMock(
        return_value=resolved.runtime.model_copy(
            update={
                "runtime_policy_snapshot_id": "snapshot-2",
                "desired_state": RuntimeDesiredState.STOPPED,
                "desired_generation": 3,
                "terminal_delete_requested_generation": 3,
            }
        )
    )
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=_session_manager,
        policy_repository=Mock(),
        snapshot_repository=snapshot_repository,
        runtime_repository=runtime_repository,
        provider_repository=Mock(),
        agent_admin_repository=Mock(),
    )
    service._resolve_locked = AsyncMock(return_value=resolved)

    command = await service.target_lifecycle_command(
        agent_id="agent-1",
        command_type=RuntimeLifecycleCommandType.STOP,
        desired_state=RuntimeDesiredState.STOPPED,
        reset_final_desired_state=None,
        terminal_delete_requested=True,
    )

    call = snapshot_repository.create_and_advance_target_snapshot.await_args
    assert call.kwargs["create"].provider_id == "provider-1"
    assert call.kwargs["create"].target_desired_generation == 3
    assert call.kwargs["expected_target_snapshot_id"] == "snapshot-1"
    assert call.kwargs["lifecycle_command"] is RuntimeLifecycleCommandType.STOP
    assert call.kwargs["desired_state"] is RuntimeDesiredState.STOPPED
    assert call.kwargs["reset_final_desired_state"] is None
    assert call.kwargs["terminal_delete_requested"] is True
    assert command.desired_generation == 3
    assert command.runtime.terminal_delete_requested_generation == 3


async def test_terminal_delete_retry_reuses_current_generation() -> None:
    """Retrying terminal deletion never creates a newer target snapshot."""
    resolved = _resolved()
    resolved = dataclasses.replace(
        resolved,
        runtime=resolved.runtime.model_copy(
            update={
                "terminal_delete_requested_generation": (
                    resolved.runtime.desired_generation
                )
            }
        ),
    )
    snapshot_repository = Mock()
    snapshot_repository.create_and_advance_target_snapshot = AsyncMock()
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=_session_manager,
        policy_repository=Mock(),
        snapshot_repository=snapshot_repository,
        runtime_repository=Mock(),
        provider_repository=Mock(),
        agent_admin_repository=Mock(),
    )
    service._resolve_locked = AsyncMock(return_value=resolved)

    command = await service.target_lifecycle_command(
        agent_id="agent-1",
        command_type=RuntimeLifecycleCommandType.STOP,
        desired_state=RuntimeDesiredState.STOPPED,
        reset_final_desired_state=None,
        terminal_delete_requested=True,
    )

    assert command.desired_generation == resolved.runtime.desired_generation
    assert command.runtime.runtime_policy_snapshot_id == "snapshot-1"
    snapshot_repository.create_and_advance_target_snapshot.assert_not_awaited()


def test_automatic_convergence_requires_unchanged_agent_intent() -> None:
    """Profile ceiling changes may converge while Agent intent is unchanged."""
    resolved = _resolved()
    matching = dataclasses.replace(
        resolved,
        target_snapshot=dataclasses.replace(
            resolved.target_snapshot,
            execution_profile_version=2,
            execution_agent_version=4,
        ),
    )

    assert _automatic_convergence_source_allowed(matching)
    assert _automatic_convergence_source_allowed(
        dataclasses.replace(
            matching,
            target_snapshot=dataclasses.replace(
                matching.target_snapshot,
                execution_profile_version=1,
            ),
        )
    )
    assert not _automatic_convergence_source_allowed(
        dataclasses.replace(
            matching,
            target_snapshot=dataclasses.replace(
                matching.target_snapshot,
                execution_agent_version=3,
            ),
        )
    )


async def test_convergence_leaves_remaining_storage_expansion_for_apply() -> None:
    """An already-converged security meet does not create restart targets forever."""
    resolved = _storage_expansion_resolved()
    snapshot_repository = Mock()
    snapshot_repository.create_and_advance_target_snapshot = AsyncMock()
    runtime_repository = Mock()
    runtime_repository.get_by_id_for_update = AsyncMock(return_value=resolved.runtime)
    policy_repository = Mock()
    policy_repository.append_audit_event = AsyncMock()
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=_session_manager,
        policy_repository=policy_repository,
        snapshot_repository=snapshot_repository,
        runtime_repository=runtime_repository,
        provider_repository=Mock(),
        agent_admin_repository=Mock(),
    )
    service._resolve_locked = AsyncMock(return_value=resolved)

    outcome = await service._converge_runtime("runtime-1")

    assert outcome == "pending_expansion"
    snapshot_repository.create_and_advance_target_snapshot.assert_not_awaited()
    policy_repository.append_audit_event.assert_not_awaited()


async def test_incompatible_convergence_stops_with_a_new_exact_target() -> None:
    """Fail-closed stopping never advances generation without a target snapshot."""
    resolved = _unavailable_resolved()
    canonical_policy = resolved.target_snapshot.resolved_execution_policy_json
    assert canonical_policy is not None
    created_snapshot = dataclasses.replace(
        resolved.target_snapshot,
        id="snapshot-2",
        target_desired_generation=3,
    )
    snapshot_repository = Mock()
    snapshot_repository.create_and_advance_target_snapshot = AsyncMock(
        return_value=created_snapshot
    )
    runtime_repository = Mock()
    runtime_repository.get_by_id_for_update = AsyncMock(return_value=resolved.runtime)
    runtime_repository.get_by_id = AsyncMock(
        return_value=resolved.runtime.model_copy(
            update={
                "runtime_policy_snapshot_id": "snapshot-2",
                "desired_state": RuntimeDesiredState.STOPPED,
                "desired_generation": 3,
            }
        )
    )
    runtime_repository.set_desired_state = AsyncMock()
    policy_repository = Mock()
    policy_repository.append_audit_event = AsyncMock()
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=_session_manager,
        policy_repository=policy_repository,
        snapshot_repository=snapshot_repository,
        runtime_repository=runtime_repository,
        provider_repository=Mock(),
        agent_admin_repository=Mock(),
    )
    service._resolve_locked = AsyncMock(return_value=resolved)

    outcome = await service._converge_runtime("runtime-1")

    assert outcome == "stopped"
    call = snapshot_repository.create_and_advance_target_snapshot.await_args
    assert call.kwargs["create"].target_desired_generation == 3
    assert call.kwargs["create"].resolved_execution_policy_json == canonical_policy
    assert call.kwargs["lifecycle_command"] is RuntimeLifecycleCommandType.STOP
    assert call.kwargs["desired_state"] is RuntimeDesiredState.STOPPED
    assert call.kwargs["terminal_delete_requested"] is False
    runtime_repository.set_desired_state.assert_not_awaited()
    policy_repository.append_audit_event.assert_awaited_once()


async def test_unavailable_agent_intent_change_remains_pending_apply() -> None:
    """Agent Profile changes cannot trigger automatic fail-closed lifecycle."""
    resolved = _unavailable_resolved()
    resolved = dataclasses.replace(
        resolved,
        target_snapshot=dataclasses.replace(
            resolved.target_snapshot,
            execution_agent_version=3,
        ),
    )
    snapshot_repository = Mock()
    snapshot_repository.create_and_advance_target_snapshot = AsyncMock()
    runtime_repository = Mock()
    runtime_repository.get_by_id_for_update = AsyncMock(return_value=resolved.runtime)
    runtime_repository.set_desired_state = AsyncMock()
    policy_repository = Mock()
    policy_repository.append_audit_event = AsyncMock()
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=_session_manager,
        policy_repository=policy_repository,
        snapshot_repository=snapshot_repository,
        runtime_repository=runtime_repository,
        provider_repository=Mock(),
        agent_admin_repository=Mock(),
    )
    service._resolve_locked = AsyncMock(return_value=resolved)

    outcome = await service._converge_runtime("runtime-1")

    assert outcome == "pending_expansion"
    snapshot_repository.create_and_advance_target_snapshot.assert_not_awaited()
    runtime_repository.set_desired_state.assert_not_awaited()
    policy_repository.append_audit_event.assert_not_awaited()


def test_mixed_convergence_copies_only_restrictive_fields() -> None:
    standard = standard_runtime_execution_policy()
    applied = standard.model_copy(
        update={
            "docker": RuntimeExecutionDockerModule(
                module_id=RuntimeExecutionModuleId.DOCKER,
                version=1,
                enabled=True,
                storage_mode=RuntimeExecutionStorageMode.EPHEMERAL,
                storage_capacity_bytes=8_589_934_592,
            ),
            "resources": standard.resources.model_copy(
                update={"ephemeral_storage_bytes": 8_589_934_592}
            ),
        }
    )
    current = standard.model_copy(
        update={
            "resources": standard.resources.model_copy(
                update={"cpu_limit_millicores": 1_000}
            )
        }
    )
    change = classify_runtime_execution_change(applied, current)
    assert change.direction is RuntimeExecutionChangeDirection.MIXED

    projected = _restrictive_projection(applied, current)

    assert projected.docker.enabled is False
    assert projected.resources.cpu_limit_millicores == 1_000


def test_restrictive_projection_keeps_storage_mode_and_capacity_atomic() -> None:
    """Disabling Docker storage cannot retain the previously applied capacity."""
    standard = standard_runtime_execution_policy()
    applied = standard.model_copy(
        update={
            "docker": RuntimeExecutionDockerModule(
                module_id=RuntimeExecutionModuleId.DOCKER,
                version=1,
                enabled=True,
                storage_mode=RuntimeExecutionStorageMode.EPHEMERAL,
                storage_capacity_bytes=17_179_869_184,
            ),
            "resources": standard.resources.model_copy(
                update={"ephemeral_storage_bytes": 17_179_869_184}
            ),
        }
    )
    projected = _restrictive_projection(applied, standard)

    assert projected.docker.storage_mode is RuntimeExecutionStorageMode.NONE
    assert projected.docker.storage_capacity_bytes is None


def test_restrictive_projection_keeps_request_within_new_limit() -> None:
    """A new limit safely clamps a previously unbounded Kubernetes request."""
    standard = standard_runtime_execution_policy()
    applied = standard.model_copy(
        update={
            "resources": standard.resources.model_copy(
                update={"cpu_request_millicores": 2_000}
            )
        }
    )
    current = standard.model_copy(
        update={
            "resources": standard.resources.model_copy(
                update={"cpu_limit_millicores": 1_000}
            )
        }
    )
    projected = _restrictive_projection(applied, current)

    assert projected.resources.cpu_request_millicores == 1_000
    assert projected.resources.cpu_limit_millicores == 1_000


def test_restrictive_projection_does_not_split_expanding_storage_module() -> None:
    """A mixed change cannot produce a capacity with no Docker storage mode."""
    applied = standard_runtime_execution_policy()
    current = applied.model_copy(
        update={
            "docker": RuntimeExecutionDockerModule(
                module_id=RuntimeExecutionModuleId.DOCKER,
                version=1,
                enabled=True,
                storage_mode=RuntimeExecutionStorageMode.EPHEMERAL,
                storage_capacity_bytes=17_179_869_184,
            ),
            "resources": applied.resources.model_copy(
                update={
                    "cpu_limit_millicores": 1_000,
                    "ephemeral_storage_bytes": 17_179_869_184,
                }
            ),
        }
    )
    change = classify_runtime_execution_change(applied, current)
    assert change.direction is RuntimeExecutionChangeDirection.MIXED

    projected = _restrictive_projection(applied, current)

    assert projected.resources.cpu_limit_millicores == 1_000
    assert projected.docker.storage_mode is RuntimeExecutionStorageMode.NONE
    assert projected.docker.storage_capacity_bytes is None


def test_standard_only_capabilities_cannot_grant_docker_authority() -> None:
    capabilities = _legacy_provider_capabilities()

    assert capabilities.supported_modules == frozenset()
    assert capabilities.storage_modes == {RuntimeExecutionStorageMode.NONE}

    standard = standard_runtime_execution_policy()
    docker_policy = standard.model_copy(
        update={
            "docker": RuntimeExecutionDockerModule(
                module_id=RuntimeExecutionModuleId.DOCKER,
                version=1,
                enabled=True,
                storage_mode=RuntimeExecutionStorageMode.EPHEMERAL,
                storage_capacity_bytes=8_589_934_592,
            ),
            "resources": standard.resources.model_copy(
                update={"ephemeral_storage_bytes": 8_589_934_592}
            ),
        }
    )
    resolution = resolve_runtime_execution_policy(
        profile_policy=docker_policy,
        workspace_restriction=empty_runtime_execution_restriction(),
        agent_restriction=empty_runtime_execution_restriction(),
        source_versions=RuntimeExecutionSourceVersions(
            profile=1,
            workspace=1,
            agent=1,
        ),
        provider_capabilities=capabilities,
        profile_active=True,
        profile_allowed=True,
        applied_policy=None,
    )

    assert not resolution.available
    assert (
        resolution.availability_reason
        is RuntimeExecutionAvailabilityReason.PROVIDER_MODULE_UNSUPPORTED
    )
